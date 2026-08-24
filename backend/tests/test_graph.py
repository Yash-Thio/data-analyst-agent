"""Whole-graph behaviour with a scripted LLM."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.agent.graph import build_graph
from app.agent.models.explanation import (
    AnalysisPlan,
    AnalysisStep,
    Claim,
    EvaluationResult,
    ExplanationDraft,
    QuestionInterpretation,
    SqlFix,
)

TOTAL_SQL = 'SELECT SUM("revenue") AS total FROM data'
BY_REGION_SQL = (
    'SELECT "region", SUM("revenue") AS total FROM data GROUP BY 1 ORDER BY total DESC'
)


def interpretation(**overrides: Any) -> QuestionInterpretation:
    base = dict(
        intent="comparison",
        metric="revenue",
        metric_columns=["revenue"],
        dimensions=["region"],
        time_scope="Q2 vs Q3 2024",
        comparison_scope="Q2 2024",
        answerable=True,
        clarification="",
        notes="",
    )
    base.update(overrides)
    return QuestionInterpretation(**base)  # type: ignore[arg-type]


def plan(*sql: str) -> AnalysisPlan:
    return AnalysisPlan(
        steps=[
            AnalysisStep(
                id=f"s{i + 1}",
                goal=f"Step {i + 1}",
                sql=s,
                expected_shape="table",
                rationale="because",
            )
            for i, s in enumerate(sql)
        ]
    )


def draft(text: str = "Revenue totalled 1,630,000.", evidence_id: str = "ev-1") -> ExplanationDraft:
    return ExplanationDraft(
        summary="Revenue is concentrated in a few regions.",
        claims=[Claim(id="c-1", text=text, evidence_ids=[evidence_id], confidence="high")],
        limitations=["Sample data only."],
        markdown="Revenue is concentrated [c-1].",
    )


def initial(csv: Path, profile: dict, question: str = "Why did revenue drop in Q3?") -> dict:
    return {
        "dataset_id": "test",
        "session_id": "s-1",
        "question": question,
        "csv_path": str(csv),
        "schema_profile": profile,
        "findings": [],
        "charts": [],
        "reasoning_trace": [],
        "events": [],
        "current_step_index": 0,
        "status": "running",
    }


@pytest.fixture
def graph():
    return build_graph()


@pytest.fixture(autouse=True)
def _llm(monkeypatch: pytest.MonkeyPatch, fake_llm):
    monkeypatch.setattr("app.agent.nodes.get_llm_provider", lambda: fake_llm)
    return fake_llm


def test_graph_has_a_replan_node(graph) -> None:
    assert "replan_analysis" in set(graph.nodes)


@pytest.mark.asyncio
async def test_happy_path(graph, _llm, sales_csv, sales_profile) -> None:
    _llm.on(QuestionInterpretation, interpretation())
    _llm.on(AnalysisPlan, plan(TOTAL_SQL, BY_REGION_SQL))
    _llm.on(EvaluationResult, EvaluationResult(sufficient=True, reason="enough", follow_up_goals=[]))
    _llm.on(ExplanationDraft, draft())

    final = await graph.ainvoke(initial(sales_csv, sales_profile))

    assert final["status"] == "done"
    assert len(final["findings"]) == 2
    assert all(f["status"] == "ok" for f in final["findings"])
    explanation = final["explanation"]
    assert explanation.claims[0].evidence_ids == ["ev-1"]
    assert explanation.degraded is False
    assert explanation.checks[0].status == "verified"


@pytest.mark.asyncio
async def test_unanswerable_question_declines_instead_of_inventing(
    graph, _llm, sales_csv, sales_profile
) -> None:
    _llm.on(
        QuestionInterpretation,
        interpretation(answerable=False, clarification="There is no marketing spend column."),
    )

    final = await graph.ainvoke(
        initial(sales_csv, sales_profile, "What did we spend on Facebook ads?")
    )

    assert final["status"] == "done"
    assert final["explanation"].claims == []
    assert "no marketing spend column" in " ".join(final["explanation"].limitations)
    # No SQL should have been planned or run.
    assert not final.get("findings")
    assert _llm.prompts_for(AnalysisPlan) == []


@pytest.mark.asyncio
async def test_insufficient_evidence_triggers_one_replan(
    graph, _llm, sales_csv, sales_profile
) -> None:
    evaluations = [
        EvaluationResult(sufficient=False, reason="no breakdown", follow_up_goals=["break down by region"]),
        EvaluationResult(sufficient=True, reason="now complete", follow_up_goals=[]),
    ]
    _llm.on(QuestionInterpretation, interpretation())
    _llm.on(AnalysisPlan, [plan(TOTAL_SQL), plan(BY_REGION_SQL)])
    _llm.on(EvaluationResult, lambda _: evaluations.pop(0) if len(evaluations) > 1 else evaluations[0])
    _llm.on(ExplanationDraft, draft())

    final = await graph.ainvoke(initial(sales_csv, sales_profile))

    assert final["replans"] == 1
    assert len(final["findings"]) == 2
    assert final["status"] == "done"


@pytest.mark.asyncio
async def test_replanning_is_bounded(graph, _llm, sales_csv, sales_profile) -> None:
    """A model that is never satisfied must still terminate."""
    _llm.on(QuestionInterpretation, interpretation())
    _llm.on(AnalysisPlan, plan(TOTAL_SQL))
    _llm.on(
        EvaluationResult,
        EvaluationResult(sufficient=False, reason="never enough", follow_up_goals=["more"]),
    )
    _llm.on(ExplanationDraft, draft())

    final = await graph.ainvoke(initial(sales_csv, sales_profile))

    assert final["status"] in ("done", "degraded")
    assert final["replans"] <= 1


@pytest.mark.asyncio
async def test_failing_step_degrades_the_report_but_still_answers(
    graph, _llm, sales_csv, sales_profile
) -> None:
    counter = iter(range(100))
    _llm.on(QuestionInterpretation, interpretation())
    _llm.on(AnalysisPlan, plan(BY_REGION_SQL, 'SELECT "nonsense" FROM data'))
    _llm.on(SqlFix, lambda _: SqlFix(sql=f'SELECT "n{next(counter)}" FROM data', explanation="?"))
    _llm.on(EvaluationResult, EvaluationResult(sufficient=True, reason="ok", follow_up_goals=[]))
    _llm.on(ExplanationDraft, draft())

    final = await graph.ainvoke(initial(sales_csv, sales_profile))

    explanation = final["explanation"]
    assert final["status"] == "degraded"
    assert explanation.degraded is True
    assert explanation.claims, "a partial answer is still produced"
    assert any("Could not complete" in limit for limit in explanation.limitations)
    # Only the successful step becomes evidence.
    assert len(explanation.evidence) == 1


@pytest.mark.asyncio
async def test_every_step_failing_reports_failure_rather_than_guessing(
    graph, _llm, sales_csv, sales_profile
) -> None:
    counter = iter(range(100))
    _llm.on(QuestionInterpretation, interpretation())
    _llm.on(AnalysisPlan, plan('SELECT "nope" FROM data'))
    _llm.on(SqlFix, lambda _: SqlFix(sql=f'SELECT "n{next(counter)}" FROM data', explanation="?"))
    _llm.on(ExplanationDraft, draft())

    final = await graph.ainvoke(initial(sales_csv, sales_profile))

    assert final["status"] == "degraded"
    assert final["explanation"].claims == []
    assert final["explanation"].evidence == []
    # The narrative model is never asked to write a report with no evidence.
    assert _llm.prompts_for(ExplanationDraft) == []


@pytest.mark.asyncio
async def test_invented_numbers_are_demoted(graph, _llm, sales_csv, sales_profile) -> None:
    _llm.on(QuestionInterpretation, interpretation())
    _llm.on(AnalysisPlan, plan(TOTAL_SQL))
    _llm.on(EvaluationResult, EvaluationResult(sufficient=True, reason="ok", follow_up_goals=[]))
    _llm.on(ExplanationDraft, draft(text="Revenue was exactly 999,999."))

    final = await graph.ainvoke(initial(sales_csv, sales_profile))

    explanation = final["explanation"]
    assert explanation.checks[0].status == "unverified"
    assert explanation.claims[0].confidence == "low"
    assert any("could not be traced" in limit for limit in explanation.limitations)


@pytest.mark.asyncio
async def test_claim_citing_missing_evidence_is_retried_then_dropped(
    graph, _llm, sales_csv, sales_profile
) -> None:
    _llm.on(QuestionInterpretation, interpretation())
    _llm.on(AnalysisPlan, plan(TOTAL_SQL))
    _llm.on(EvaluationResult, EvaluationResult(sufficient=True, reason="ok", follow_up_goals=[]))
    _llm.on(ExplanationDraft, draft(evidence_id="ev-99"))

    final = await graph.ainvoke(initial(sales_csv, sales_profile))

    # Retried once, then the bad citation is stripped rather than crashing.
    assert len(_llm.prompts_for(ExplanationDraft)) == 2
    assert final["explanation"].claims == []
    assert final["status"] in ("done", "degraded")


@pytest.mark.asyncio
async def test_wide_dataset_runs_end_to_end(
    graph, _llm, unemployment_csv, unemployment_profile
) -> None:
    """The dataset that used to abort the run before any query executed."""
    sql = (
        'SELECT "Region Name", ROUND(AVG("value"), 2) AS avg_rate '
        'FROM data_long GROUP BY 1 ORDER BY avg_rate DESC LIMIT 5'
    )
    _llm.on(QuestionInterpretation, interpretation(intent="ranking", metric="unemployment rate"))
    _llm.on(AnalysisPlan, plan(sql))
    _llm.on(EvaluationResult, EvaluationResult(sufficient=True, reason="ok", follow_up_goals=[]))
    _llm.on(
        ExplanationDraft,
        ExplanationDraft(
            summary="A handful of areas have persistently high unemployment.",
            claims=[
                Claim(id="c-1", text="The highest areas exceed 15%.", evidence_ids=["ev-1"], confidence="medium")
            ],
            limitations=["Monthly averages only."],
            markdown="High unemployment is concentrated [c-1].",
        ),
    )

    final = await graph.ainvoke(
        initial(unemployment_csv, unemployment_profile, "What is the average unemployment by region?")
    )

    assert final["status"] == "done"
    assert final["findings"][0]["row_count"] == 5
    assert "data_long" in final["findings"][0]["sql"]


@pytest.mark.asyncio
async def test_schema_card_reaches_the_planner(graph, _llm, financial_csv, financial_profile) -> None:
    _llm.on(QuestionInterpretation, interpretation())
    _llm.on(AnalysisPlan, plan('SELECT SUM("Sales") AS total FROM data'))
    _llm.on(EvaluationResult, EvaluationResult(sufficient=True, reason="ok", follow_up_goals=[]))
    _llm.on(ExplanationDraft, draft(text="Sales are concentrated."))

    await graph.ainvoke(initial(financial_csv, financial_profile, "How are sales doing?"))

    prompt = _llm.prompts_for(AnalysisPlan)[0]
    assert '"Gross Sales"' in prompt
    assert "never aggregate" in prompt or "identifier" in prompt
    assert "UPPER(TRIM" in prompt, "casing hazard must be advertised to the planner"
