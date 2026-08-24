"""LangGraph nodes.

Two principles run through this file:

* **Nothing aborts the run.** Every node is wrapped so a failure becomes a
  recorded error and a degraded answer, not a dead session. A partial result
  with honest caveats is more useful than a stack trace.
* **The LLM never supplies numbers.** It writes SQL and prose; every figure in
  the report comes from a query result and is checked back against it.
"""

from __future__ import annotations

import functools
import json
import logging
from pathlib import Path
from typing import Awaitable, Callable

from app.agent.models.explanation import (
    AnalysisPlan,
    AnalysisStep,
    ChartSpec,
    EvaluationResult,
    Evidence,
    Explanation,
    ExplanationDraft,
    QuestionInterpretation,
    ReasoningStep,
)
from app.agent.schema_card import build_schema_card
from app.agent.skills import load_skill
from app.agent.sql_repair import RepairAttempt, execute_with_repair
from app.agent.state import AgentEvent, AgentState, Finding
from app.agent.tools.analytics import (
    choose_chart,
    create_chart_spec,
    derive_metrics,
    summarise_result,
)
from app.agent.verify import verify_claims
from app.data.duckdb_engine import DuckDBEngine
from app.llm.base import Message, get_llm_provider

logger = logging.getLogger(__name__)

MAX_PLAN_STEPS = 5
MAX_TOTAL_STEPS = 8
MAX_REPLANS = 1
EVIDENCE_PREVIEW_ROWS = 10


# --------------------------------------------------------------------------
# infrastructure
# --------------------------------------------------------------------------


def node_guard(name: str) -> Callable:
    """Turn a node failure into a recorded error instead of a dead graph."""

    def decorator(func: Callable[[AgentState], Awaitable[dict]]):
        @functools.wraps(func)
        async def wrapper(state: AgentState) -> dict:
            try:
                return await func(state)
            except Exception as exc:  # noqa: BLE001 - deliberate catch-all
                logger.exception("node %s failed", name)
                message = f"{type(exc).__name__}: {exc}".strip()
                return {
                    "events": _append(
                        state,
                        {
                            # Deliberately not "error": that type terminates the
                            # SSE stream, and this run is still going.
                            "type": "step_error",
                            "node": name,
                            "message": f"Step '{name}' failed: {message}",
                            "recoverable": True,
                        },
                    ),
                    "reasoning_trace": _trace(state, name, "Recover from failure", message),
                    "node_errors": [*state.get("node_errors", []), f"{name}: {message}"],
                }

        return wrapper

    return decorator


def _append(state: AgentState, *events: AgentEvent) -> list[AgentEvent]:
    return [*state.get("events", []), *events]


def _trace(state: AgentState, node: str, description: str, summary: str) -> list[ReasoningStep]:
    trace = list(state.get("reasoning_trace", []))
    trace.append(
        ReasoningStep(
            order=len(trace) + 1, node=node, description=description, output_summary=summary
        )
    )
    return trace


def _schema_card(state: AgentState) -> str:
    return build_schema_card(state["schema_profile"])


# --------------------------------------------------------------------------
# nodes
# --------------------------------------------------------------------------


@node_guard("profile_dataset")
async def profile_dataset_node(state: AgentState) -> dict:
    profile = state["schema_profile"]
    layout = profile.get("layout", "long")
    detail = (
        f"{profile.get('row_count', 0):,} rows, {profile.get('column_count', 0)} columns"
    )
    if layout == "wide":
        detail += " (wide layout - an unpivoted view is available)"

    events = _append(
        state,
        {"type": "node_start", "node": "profile_dataset", "message": f"Loaded dataset: {detail}"},
    )

    quality = profile.get("quality") or {}
    for warning in quality.get("warnings", []):
        if warning.get("severity") in ("warning", "error"):
            events.append(
                {"type": "warning", "node": "profile_dataset", "message": warning["message"]}
            )

    return {"events": events, "reasoning_trace": _trace(state, "profile_dataset", "Profile dataset", detail)}


@node_guard("interpret_question")
async def interpret_question_node(state: AgentState) -> dict:
    llm = get_llm_provider()
    events = _append(
        state,
        {"type": "node_start", "node": "interpret_question", "message": "Interpreting your question..."},
    )

    prompt = f"""Work out what this question is asking of this specific dataset.

Question: {state['question']}

{_schema_card(state)}

Decide:
- intent: the kind of analysis required
- metric: what is being measured, in plain language
- metric_columns / dimensions: exact column names from the table above, or empty lists
- time_scope / comparison_scope: the periods involved, or "" if the question is not about time
- answerable: false if the dataset simply does not contain what was asked for,
  or if the question is too vague to act on. Be honest - an unanswerable
  question must not be answered with an unrelated analysis.
- clarification: when answerable is false, what you would need to proceed"""

    interpretation = await llm.complete(
        [
            Message("system", "You interpret analytics questions against a known schema."),
            Message("user", prompt),
        ],
        response_format=QuestionInterpretation,
    )
    if not isinstance(interpretation, QuestionInterpretation):
        raise TypeError("interpret_question did not return a QuestionInterpretation")

    if interpretation.answerable:
        message = f"Intent: {interpretation.intent}; metric: {interpretation.metric}"
    else:
        message = f"Cannot answer from this dataset: {interpretation.clarification}"
    events.append({"type": "node_start", "node": "interpret_question", "message": message})

    return {
        "interpretation": interpretation,
        "events": events,
        "reasoning_trace": _trace(state, "interpret_question", "Interpret question", message),
    }


def route_after_interpret(state: AgentState) -> str:
    interpretation = state.get("interpretation")
    if interpretation is not None and not interpretation.answerable:
        return "build_explanation"
    return "plan_analysis"


@node_guard("plan_analysis")
async def plan_analysis_node(state: AgentState) -> dict:
    llm = get_llm_provider()
    interpretation = state.get("interpretation")
    events = _append(
        state, {"type": "node_start", "node": "plan_analysis", "message": "Planning analysis steps..."}
    )

    plan = await _request_plan(
        llm,
        question=state["question"],
        interpretation=interpretation,
        schema_card=_schema_card(state),
        goals=[],
        existing=[],
    )
    steps = plan.steps[:MAX_PLAN_STEPS]

    events.append(
        {"type": "node_start", "node": "plan_analysis", "message": f"Planned {len(steps)} steps"}
    )
    return {
        "plan": steps,
        "current_step_index": 0,
        "events": events,
        "reasoning_trace": _trace(
            state, "plan_analysis", "Plan analysis", "; ".join(s.goal for s in steps) or "no steps"
        ),
    }


@node_guard("replan_analysis")
async def replan_analysis_node(state: AgentState) -> dict:
    """Extend the plan when the evidence gathered so far is not enough."""
    llm = get_llm_provider()
    evaluation = state.get("evaluation") or {}
    goals = evaluation.get("follow_up_goals") or []
    existing = list(state.get("plan", []))

    events = _append(
        state,
        {
            "type": "node_start",
            "node": "replan_analysis",
            "message": f"Evidence incomplete ({evaluation.get('reason', 'unspecified')}); planning further steps",
        },
    )

    remaining = MAX_TOTAL_STEPS - len(existing)
    if remaining <= 0:
        return {
            "events": events,
            "replans": state.get("replans", 0) + 1,
            "reasoning_trace": _trace(
                state, "replan_analysis", "Replan", "Step budget exhausted; answering with what we have."
            ),
        }

    plan = await _request_plan(
        llm,
        question=state["question"],
        interpretation=state.get("interpretation"),
        schema_card=_schema_card(state),
        goals=goals,
        existing=state.get("findings", []),
    )

    offset = len(existing)
    extra = [
        step.model_copy(update={"id": f"s{offset + i + 1}"})
        for i, step in enumerate(plan.steps[:remaining])
    ]
    events.append(
        {"type": "node_start", "node": "replan_analysis", "message": f"Added {len(extra)} step(s)"}
    )

    return {
        "plan": existing + extra,
        "events": events,
        "replans": state.get("replans", 0) + 1,
        "reasoning_trace": _trace(
            state, "replan_analysis", "Extend plan", "; ".join(s.goal for s in extra) or "no new steps"
        ),
    }


async def _request_plan(
    llm,
    *,
    question: str,
    interpretation: QuestionInterpretation | None,
    schema_card: str,
    goals: list[str],
    existing: list[dict],
) -> AnalysisPlan:
    context = ""
    if existing:
        done = "\n".join(f"- {f['goal']}: {f['result_summary']}" for f in existing)
        context = f"\n\nAlready established:\n{done}\n\nDo not repeat these."
    if goals:
        context += "\n\nStill needed:\n" + "\n".join(f"- {g}" for g in goals)

    interp = interpretation.model_dump_json() if interpretation else "{}"
    prompt = f"""Write a short analysis plan. Each step is one DuckDB SELECT query.

Question: {question}
Interpretation: {interp}{context}

{schema_card}

{load_skill("duckdb_sql")}

Produce 1 to {MAX_PLAN_STEPS} steps. Each step needs:
- id: s1, s2, ...
- goal: what the query establishes, in plain language
- sql: one complete SELECT statement
- expected_shape: scalar (one number), series (a period or category breakdown), or table
- rationale: why this step helps answer the question

Start with the headline number, then break it down by the dimensions that
explain it. Every step must be independently runnable."""

    plan = await llm.complete(
        [
            Message("system", "You plan data analyses as concrete DuckDB queries."),
            Message("user", prompt),
        ],
        response_format=AnalysisPlan,
    )
    if not isinstance(plan, AnalysisPlan):
        raise TypeError("plan_analysis did not return an AnalysisPlan")
    return plan


@node_guard("execute_step")
async def execute_step_node(state: AgentState) -> dict:
    plan: list[AnalysisStep] = state.get("plan", [])
    index = state.get("current_step_index", 0)
    if index >= len(plan):
        return {}

    step = plan[index]
    findings = list(state.get("findings", []))
    events = _append(
        state, {"type": "node_start", "node": "execute_step", "message": f"Running: {step.goal}"}
    )
    retries: list[RepairAttempt] = []

    with DuckDBEngine(Path(state["csv_path"])) as engine:
        outcome = await execute_with_repair(
            engine,
            step.sql,
            goal=step.goal,
            question=state["question"],
            schema_card=_schema_card(state),
            llm=get_llm_provider(),
            on_attempt=retries.append,
        )

    for attempt in retries:
        events.append(
            {
                "type": "step_retry",
                "node": "execute_step",
                "id": step.id,
                "attempt": attempt.attempt,
                "message": f"Attempt {attempt.attempt} failed ({attempt.stage}): {attempt.error}",
                "sql": attempt.sql,
            }
        )

    finding_id = f"f-{len(findings) + 1}"
    rows = outcome.rows
    truncated = bool(outcome.result and outcome.result.truncated)

    if outcome.status == "failed":
        finding: Finding = {
            "id": finding_id,
            "step_id": step.id,
            "goal": step.goal,
            "sql": outcome.sql,
            "result_rows": [],
            "result_summary": f"Could not be computed: {outcome.error}",
            "computed_metrics": {},
            "row_count": 0,
            "truncated": False,
            "status": "failed",
            "attempts": len(retries) + 1,
        }
        events.append(
            {
                "type": "step_error",
                "node": "execute_step",
                "message": f"Step '{step.goal}' could not be completed: {outcome.error}",
                "recoverable": True,
            }
        )
    else:
        summary = summarise_result(step.goal, rows, truncated)
        finding = {
            "id": finding_id,
            "step_id": step.id,
            "goal": step.goal,
            "sql": outcome.sql,
            "result_rows": rows[:EVIDENCE_PREVIEW_ROWS],
            "result_summary": summary,
            "computed_metrics": derive_metrics(rows),
            "row_count": len(rows),
            "truncated": truncated,
            "status": outcome.status,
            "attempts": len(retries) + 1,
        }
        events.append(
            {"type": "tool_call", "tool": "run_sql", "sql": outcome.sql, "row_count": len(rows)}
        )
        events.append(
            {"type": "finding", "id": finding_id, "summary": summary, "sql": outcome.sql}
        )
        if truncated:
            events.append(
                {
                    "type": "warning",
                    "node": "execute_step",
                    "message": f"'{step.goal}' returned more rows than can be shown; the preview is truncated.",
                }
            )

    findings.append(finding)
    return {
        "findings": findings,
        "current_step_index": index + 1,
        "events": events,
        "reasoning_trace": _trace(state, "execute_step", step.goal, finding["result_summary"]),
    }


@node_guard("evaluate_step")
async def evaluate_step_node(state: AgentState) -> dict:
    plan = state.get("plan", [])
    index = state.get("current_step_index", 0)
    findings = state.get("findings", [])

    if index < len(plan):
        return {"evaluation": {"sufficient": False, "reason": "steps remaining", "follow_up_goals": []}}

    events = _append(
        state, {"type": "node_start", "node": "evaluate_step", "message": "Checking the evidence..."}
    )
    usable = [f for f in findings if f.get("status") == "ok"]

    if not usable:
        evaluation = {
            "sufficient": True,
            "reason": "No step produced usable data; reporting the failure rather than guessing.",
            "follow_up_goals": [],
        }
        return {
            "evaluation": evaluation,
            "events": events,
            "reasoning_trace": _trace(state, "evaluate_step", "Check evidence", evaluation["reason"]),
        }

    llm = get_llm_provider()
    summary = json.dumps(
        [
            {"goal": f["goal"], "summary": f["result_summary"], "metrics": f["computed_metrics"]}
            for f in usable
        ],
        default=str,
        indent=2,
    )
    result = await llm.complete(
        [
            Message("system", "You judge whether an analysis is complete."),
            Message(
                "user",
                f"""Question: {state['question']}

Findings so far:
{summary}

Is this enough to answer the question directly and defensibly?
If not, list the specific follow-up analyses still needed (follow_up_goals).
Say yes when the headline figure and its main drivers are covered - more
detail for its own sake is not worth another query.""",
            ),
        ],
        response_format=EvaluationResult,
    )
    if not isinstance(result, EvaluationResult):
        raise TypeError("evaluate_step did not return an EvaluationResult")

    return {
        "evaluation": result.model_dump(),
        "events": events,
        "reasoning_trace": _trace(state, "evaluate_step", "Check evidence", result.reason),
    }


def route_after_evaluate(state: AgentState) -> str:
    """Honour the evaluation, bounded by a step and replan budget."""
    plan = state.get("plan", [])
    index = state.get("current_step_index", 0)
    if index < len(plan):
        return "execute_step"

    evaluation = state.get("evaluation") or {}
    if evaluation.get("sufficient"):
        return "generate_charts"
    if state.get("replans", 0) >= MAX_REPLANS or len(plan) >= MAX_TOTAL_STEPS:
        return "generate_charts"
    return "replan_analysis"


def route_after_replan(state: AgentState) -> str:
    plan = state.get("plan", [])
    if state.get("current_step_index", 0) < len(plan):
        return "execute_step"
    return "generate_charts"


@node_guard("generate_charts")
async def generate_charts_node(state: AgentState) -> dict:
    findings = state.get("findings", [])
    column_roles = {c["name"]: c["role"] for c in state["schema_profile"].get("columns", [])}
    events = _append(
        state, {"type": "node_start", "node": "generate_charts", "message": "Building charts..."}
    )

    charts: list[ChartSpec] = []
    for finding in findings:
        if finding.get("status") != "ok":
            continue
        rows = finding.get("result_rows") or []
        axes = choose_chart(rows, column_roles)
        if axes is None:
            continue
        spec = create_chart_spec(
            finding_id=finding["id"],
            chart_type=axes["type"],
            title=finding["goal"],
            data=rows,
            x_key=axes["x_key"],
            y_key=axes["y_key"],
        )
        charts.append(ChartSpec(**spec))
        events.append({"type": "chart", "spec": spec, "finding_id": finding["id"]})

    return {
        "charts": charts,
        "events": events,
        "reasoning_trace": _trace(state, "generate_charts", "Build charts", f"{len(charts)} chart(s)"),
    }


@node_guard("build_explanation")
async def build_explanation_node(state: AgentState) -> dict:
    findings = state.get("findings", [])
    charts = state.get("charts", [])
    interpretation = state.get("interpretation")
    events = _append(
        state, {"type": "node_start", "node": "build_explanation", "message": "Writing the report..."}
    )

    if interpretation is not None and not interpretation.answerable:
        return _clarification_result(state, events, interpretation)

    evidence = _build_evidence(findings, charts)
    failed = [f for f in findings if f.get("status") != "ok"]
    degraded = bool(failed or state.get("node_errors"))

    if not evidence:
        return _no_evidence_result(state, events)

    draft = await _draft_explanation(state, evidence, attempt=1)
    verification = verify_claims(draft.claims, evidence)

    limitations = list(draft.limitations)
    limitations.extend(_dataset_caveats(state))
    limitations.extend(verification.notes)
    for item in failed:
        limitations.append(f"Could not complete: {item['goal']} ({item['result_summary']}).")

    explanation = Explanation(
        summary=draft.summary,
        claims=verification.kept,
        evidence=evidence,
        reasoning_trace=state.get("reasoning_trace", []),
        limitations=_dedupe(limitations),
        markdown=draft.markdown,
        checks=verification.checks,
        degraded=degraded,
    )

    events.extend(_explanation_events(state, explanation))
    return {
        "explanation": explanation,
        "events": events,
        "reasoning_trace": _trace(state, "build_explanation", "Write report", explanation.summary),
        "status": "degraded" if degraded else "done",
    }


# --------------------------------------------------------------------------
# build_explanation helpers
# --------------------------------------------------------------------------


def _build_evidence(findings: list[Finding], charts: list[ChartSpec]) -> list[Evidence]:
    evidence: list[Evidence] = []
    for finding in findings:
        if finding.get("status") != "ok":
            continue
        chart_id = next((c.id for c in charts if c.finding_id == finding["id"]), None)
        evidence.append(
            Evidence(
                id=f"ev-{len(evidence) + 1}",
                finding_id=finding["id"],
                sql=finding["sql"],
                result_preview=finding.get("result_rows", [])[:EVIDENCE_PREVIEW_ROWS],
                metrics=finding.get("computed_metrics", {}),
                row_count=finding.get("row_count", 0),
                truncated=finding.get("truncated", False),
                chart_id=chart_id,
            )
        )
    return evidence


async def _draft_explanation(
    state: AgentState, evidence: list[Evidence], attempt: int
) -> ExplanationDraft:
    """Ask for the narrative, retrying once if the model breaks the contract."""
    llm = get_llm_provider()
    payload = json.dumps([e.model_dump() for e in evidence], indent=2, default=str)
    valid_ids = ", ".join(e.id for e in evidence)

    prompt = f"""Write an evidence-backed answer.

Question: {state['question']}

Evidence:
{payload}

Rules:
- Answer the question directly in `summary`, in two or three sentences.
- Every claim must cite at least one evidence id. Valid ids: {valid_ids}.
- Use only figures that appear in the evidence above. Do not compute new ones
  or round so heavily that they no longer match.
- Claim ids are c-1, c-2, ... and `markdown` cites them as [c-1].
- `limitations` covers what the data cannot tell us: period definitions,
  missing values, and anything the evidence does not cover."""

    if attempt > 1:
        prompt += (
            "\n\nYour previous attempt was rejected for citing an evidence id that "
            "does not exist. Use only the ids listed above."
        )

    draft = await llm.complete(
        [
            Message("system", "You write precise, evidence-backed analytical reports."),
            Message("user", prompt),
        ],
        response_format=ExplanationDraft,
    )
    if not isinstance(draft, ExplanationDraft):
        raise TypeError("build_explanation did not return an ExplanationDraft")

    known = {e.id for e in evidence}
    unknown = [eid for c in draft.claims for eid in c.evidence_ids if eid not in known]
    if unknown and attempt == 1:
        return await _draft_explanation(state, evidence, attempt=2)
    if unknown:
        # Second failure: keep what is valid rather than losing the report.
        cleaned = [
            c.model_copy(update={"evidence_ids": [e for e in c.evidence_ids if e in known]})
            for c in draft.claims
        ]
        draft = draft.model_copy(
            update={"claims": [c for c in cleaned if c.evidence_ids]}
        )
    return draft


def _clarification_result(
    state: AgentState, events: list[AgentEvent], interpretation: QuestionInterpretation
) -> dict:
    """The dataset cannot answer the question - say so instead of inventing."""
    question = state["question"]
    clarification = interpretation.clarification or (
        "The uploaded dataset does not contain the information this question needs."
    )
    markdown = (
        f"I can't answer that from this dataset.\n\n{clarification}\n\n"
        "Here is what the data does contain:\n"
        + "\n".join(
            f"- `{c['name']}` ({c['role']})" for c in state["schema_profile"].get("columns", [])[:12]
        )
    )
    explanation = Explanation(
        summary=f"This dataset cannot answer: {question}",
        claims=[],
        evidence=[],
        reasoning_trace=state.get("reasoning_trace", []),
        limitations=[clarification, *_dataset_caveats(state)],
        markdown=markdown,
        degraded=False,
    )
    events.append(
        {"type": "explanation", "summary": explanation.summary, "limitations": explanation.limitations}
    )
    events.append({"type": "report_chunk", "content": markdown})
    events.append({"type": "done", "session_id": state.get("session_id", "")})
    return {
        "explanation": explanation,
        "events": events,
        "reasoning_trace": _trace(state, "build_explanation", "Decline", explanation.summary),
        "status": "done",
    }


def _no_evidence_result(state: AgentState, events: list[AgentEvent]) -> dict:
    reasons = [
        f["result_summary"] for f in state.get("findings", []) if f.get("status") != "ok"
    ] or ["No analysis steps produced results."]
    explanation = Explanation(
        summary="The analysis could not be completed against this dataset.",
        claims=[],
        evidence=[],
        reasoning_trace=state.get("reasoning_trace", []),
        limitations=_dedupe([*reasons, *state.get("node_errors", []), *_dataset_caveats(state)]),
        markdown=(
            "No query produced usable results, so there is nothing to report.\n\n"
            + "\n".join(f"- {r}" for r in reasons)
        ),
        degraded=True,
    )
    events.append(
        {"type": "explanation", "summary": explanation.summary, "limitations": explanation.limitations}
    )
    events.append({"type": "report_chunk", "content": explanation.markdown})
    events.append({"type": "done", "session_id": state.get("session_id", "")})
    return {
        "explanation": explanation,
        "events": events,
        "reasoning_trace": _trace(state, "build_explanation", "Report failure", explanation.summary),
        "status": "degraded",
    }


def _explanation_events(state: AgentState, explanation: Explanation) -> list[AgentEvent]:
    events: list[AgentEvent] = []
    for claim in explanation.claims:
        events.append(
            {
                "type": "claim",
                "id": claim.id,
                "text": claim.text,
                "evidence_ids": claim.evidence_ids,
                "confidence": claim.confidence,
            }
        )
    events.append(
        {
            "type": "explanation",
            "summary": explanation.summary,
            "limitations": explanation.limitations,
            "degraded": explanation.degraded,
        }
    )
    events.append({"type": "report_chunk", "content": explanation.markdown})
    events.append({"type": "done", "session_id": state.get("session_id", "")})
    return events


def _dataset_caveats(state: AgentState) -> list[str]:
    quality = (state.get("schema_profile") or {}).get("quality") or {}
    caveats = [
        w["message"] for w in quality.get("warnings", []) if w.get("severity") in ("warning", "error")
    ]
    if duplicates := quality.get("duplicate_rows"):
        caveats.append(
            f"{duplicates} fully duplicated rows are present and are counted more "
            "than once by aggregates."
        )
    return caveats


def _dedupe(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            result.append(item)
    return result
