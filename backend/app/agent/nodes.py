import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.agent.models.explanation import (
    AnalysisPlan,
    ChartSpec,
    EvaluationResult,
    Evidence,
    Explanation,
    ExplanationDraft,
    QuestionInterpretation,
    ReasoningStep,
)
from app.agent.state import AgentEvent, AgentState, Finding
from app.agent.tools.analytics import (
    compare_periods,
    create_chart_spec,
    get_schema,
    run_sql,
    top_contributors,
)
from app.llm.base import Message, get_llm_provider


def _emit(state: AgentState, event: AgentEvent) -> list[AgentEvent]:
    events = list(state.get("events", []))
    events.append(event)
    return events


def _trace(state: AgentState, node: str, description: str, output_summary: str) -> list[ReasoningStep]:
    trace = list(state.get("reasoning_trace", []))
    trace.append(
        ReasoningStep(
            order=len(trace) + 1,
            node=node,
            description=description,
            output_summary=output_summary,
        )
    )
    return trace


async def profile_dataset_node(state: AgentState) -> dict:
    profile = state["schema_profile"]
    events = _emit(
        state,
        {
            "type": "node_start",
            "node": "profile_dataset",
            "message": f"Loaded dataset with {profile.get('row_count', 0)} rows",
        },
    )
    trace = _trace(
        state,
        "profile_dataset",
        "Profile uploaded CSV",
        f"{profile.get('column_count')} columns, {profile.get('row_count')} rows",
    )
    return {"events": events, "reasoning_trace": trace}


async def interpret_question_node(state: AgentState) -> dict:
    llm = get_llm_provider()
    profile = state["schema_profile"]
    question = state["question"]

    events = _emit(
        state,
        {"type": "node_start", "node": "interpret_question", "message": "Interpreting your question..."},
    )

    prompt = f"""Analyze this data analytics question against the dataset schema.

Question: {question}

Schema:
{json.dumps(get_schema(profile), indent=2)}

Identify the metric, time periods, comparison period, and intent.
Pick column names from the schema when possible for metric_column and dimensions."""

    interpretation = await llm.complete(
        [Message("system", "You are a data analyst interpreting user questions."), Message("user", prompt)],
        response_format=QuestionInterpretation,
    )
    assert isinstance(interpretation, QuestionInterpretation)

    events = _emit(
        {**state, "events": events},
        {
            "type": "node_start",
            "node": "interpret_question",
            "message": f"Identified metric: {interpretation.metric}, period: {interpretation.period}",
        },
    )
    trace = _trace(
        state,
        "interpret_question",
        "Parse user question",
        f"Metric={interpretation.metric}, period={interpretation.period}, intent={interpretation.intent}",
    )
    return {"interpretation": interpretation, "events": events, "reasoning_trace": trace}


async def plan_analysis_node(state: AgentState) -> dict:
    llm = get_llm_provider()
    interpretation = state["interpretation"]
    profile = state["schema_profile"]

    events = _emit(
        state,
        {"type": "node_start", "node": "plan_analysis", "message": "Planning analysis steps..."},
    )

    prompt = f"""Create an analysis plan with 2-5 steps for this question.

Question: {state['question']}
Interpretation: {interpretation.model_dump_json()}
Schema: {json.dumps(get_schema(profile), indent=2)}

Use tools: compare_periods, top_contributors, or run_sql.
Each step needs: id (s1, s2...), goal, tool, and params object.

params must include ALL keys (use "" for unused strings, 10 for unused limit):
metric_col, date_col, period_a_label, period_a_filter, period_b_label, period_b_filter,
group_by, dimension_col, limit, sql.
- compare_periods: fill metric/date/period labels+filters; group_by optional else ""
- top_contributors: fill metric/date/dimension/period filters; labels optional else ""
- run_sql: fill sql; leave other strings ""

Filters are SQL WHERE clauses without the WHERE keyword.
Use DuckDB SQL filters referencing column names in double quotes."""

    plan_result = await llm.complete(
        [Message("system", "You plan data analysis steps."), Message("user", prompt)],
        response_format=AnalysisPlan,
    )
    assert isinstance(plan_result, AnalysisPlan)

    events = _emit(
        {**state, "events": events},
        {
            "type": "node_start",
            "node": "plan_analysis",
            "message": f"Planned {len(plan_result.steps)} analysis steps",
        },
    )
    trace = _trace(
        state,
        "plan_analysis",
        "Create analysis plan",
        "; ".join(s.goal for s in plan_result.steps),
    )
    return {
        "plan": plan_result.steps,
        "current_step_index": 0,
        "events": events,
        "reasoning_trace": trace,
    }


async def execute_step_node(state: AgentState) -> dict:
    plan = state.get("plan", [])
    idx = state.get("current_step_index", 0)
    if idx >= len(plan):
        return {}

    step = plan[idx]
    csv_path = Path(state["csv_path"])
    findings = list(state.get("findings", []))
    events = list(state.get("events", []))

    events.append(
        {
            "type": "node_start",
            "node": "execute_step",
            "message": f"Executing: {step.goal}",
        }
    )

    tool_kwargs = step.params.to_tool_kwargs(step.tool)
    result: dict[str, Any]
    if step.tool == "compare_periods":
        result = compare_periods(csv_path, **tool_kwargs)
    elif step.tool == "top_contributors":
        result = top_contributors(csv_path, **tool_kwargs)
    elif step.tool == "run_sql":
        result = run_sql(csv_path, tool_kwargs["sql"])
        result["metrics"] = {}
        result["summary"] = f"Query returned {result['row_count']} rows"
    else:
        raise ValueError(f"Unknown tool: {step.tool}")

    finding_id = f"f-{len(findings) + 1}"
    finding: Finding = {
        "id": finding_id,
        "step_id": step.id,
        "goal": step.goal,
        "tool": step.tool,
        "sql": result["sql"],
        "result_rows": result.get("rows", result.get("rows", []))[:10],
        "result_summary": result.get("summary", ""),
        "computed_metrics": result.get("metrics", {}),
    }
    findings.append(finding)

    events.append(
        {
            "type": "tool_call",
            "tool": step.tool,
            "sql": result["sql"],
            "row_count": len(result.get("rows", [])),
        }
    )
    events.append(
        {
            "type": "finding",
            "id": finding_id,
            "summary": finding["result_summary"],
            "sql": finding["sql"],
        }
    )

    trace = _trace(state, "execute_step", step.goal, finding["result_summary"])

    return {
        "findings": findings,
        "current_step_index": idx + 1,
        "events": events,
        "reasoning_trace": trace,
    }


async def evaluate_step_node(state: AgentState) -> dict:
    llm = get_llm_provider()
    plan = state.get("plan", [])
    idx = state.get("current_step_index", 0)
    findings = state.get("findings", [])

    events = _emit(
        state,
        {"type": "node_start", "node": "evaluate_step", "message": "Evaluating evidence..."},
    )

    if idx < len(plan):
        return {"evaluation": {"sufficient": False, "reason": "more steps remaining"}, "events": events}

    prompt = f"""Evaluate if we have sufficient evidence to answer the question.

Question: {state['question']}
Findings: {json.dumps(findings, default=str, indent=2)}

Return sufficient=true if findings cover the main metric change and key drivers."""

    evaluation = await llm.complete(
        [Message("system", "You evaluate analysis completeness."), Message("user", prompt)],
        response_format=EvaluationResult,
    )
    assert isinstance(evaluation, EvaluationResult)

    trace = _trace(state, "evaluate_step", "Check evidence sufficiency", evaluation.reason)

    return {
        "evaluation": evaluation.model_dump(),
        "events": events,
        "reasoning_trace": trace,
    }


def route_after_evaluate(state: AgentState) -> str:
    evaluation = state.get("evaluation", {})
    if evaluation.get("sufficient"):
        return "generate_charts"
    plan = state.get("plan", [])
    idx = state.get("current_step_index", 0)
    if idx < len(plan):
        return "execute_step"
    return "generate_charts"


async def generate_charts_node(state: AgentState) -> dict:
    findings = state.get("findings", [])
    charts: list[ChartSpec] = []
    events = list(state.get("events", []))

    events.append({"type": "node_start", "node": "generate_charts", "message": "Generating charts..."})

    for finding in findings:
        rows = finding.get("result_rows", [])
        if not rows:
            continue

        keys = list(rows[0].keys())
        if len(keys) < 2:
            continue

        x_key = keys[0]
        y_key = next((k for k in keys if k in ("total", "delta", "delta_pct", finding.get("goal", ""))), keys[1])
        for k in ("total", "delta", "delta_pct"):
            if k in keys:
                y_key = k
                break

        chart_type = "bar" if finding["tool"] in ("top_contributors", "compare_periods") else "line"
        spec = create_chart_spec(
            finding_id=finding["id"],
            chart_type=chart_type,
            title=finding["goal"],
            data=rows[:20],
            x_key=x_key if x_key != y_key else keys[0],
            y_key=y_key,
        )
        charts.append(ChartSpec(**spec))
        events.append({"type": "chart", "spec": spec, "finding_id": finding["id"]})

    trace = _trace(state, "generate_charts", "Build visualizations", f"{len(charts)} charts created")

    return {"charts": charts, "events": events, "reasoning_trace": trace}


async def build_explanation_node(state: AgentState) -> dict:
    llm = get_llm_provider()
    findings = state.get("findings", [])
    charts = state.get("charts", [])
    events = list(state.get("events", []))

    events.append({"type": "node_start", "node": "build_explanation", "message": "Building explainable report..."})

    evidence_list: list[Evidence] = []
    for i, finding in enumerate(findings):
        chart_id = next((c.id for c in charts if c.finding_id == finding["id"]), None)
        evidence_list.append(
            Evidence(
                id=f"ev-{i + 1}",
                finding_id=finding["id"],
                sql=finding["sql"],
                result_preview=finding["result_rows"][:10],
                metrics=finding.get("computed_metrics", {}),
                chart_id=chart_id,
            )
        )

    evidence_json = json.dumps([e.model_dump() for e in evidence_list], indent=2, default=str)
    prompt = f"""Create an explainable analysis report.

Question: {state['question']}

Evidence (use ONLY these evidence ids in claims):
{evidence_json}

Rules:
- Every claim MUST reference at least one evidence id from the list above
- Use exact numbers from evidence metrics, do not invent values
- Include limitations about period definitions and data scope
- markdown should use [c-1], [c-2] citation markers matching claim ids
- claims ids should be c-1, c-2, etc."""

    draft = await llm.complete(
        [Message("system", "You write evidence-backed analytical reports."), Message("user", prompt)],
        response_format=ExplanationDraft,
    )
    assert isinstance(draft, ExplanationDraft)

    explanation = Explanation(
        summary=draft.summary,
        claims=draft.claims,
        evidence=evidence_list,
        reasoning_trace=state.get("reasoning_trace", []),
        limitations=draft.limitations,
        markdown=draft.markdown,
    )

    for claim in explanation.claims:
        events.append(
            {
                "type": "claim",
                "id": claim.id,
                "text": claim.text,
                "evidence_ids": claim.evidence_ids,
            }
        )

    events.append(
        {
            "type": "explanation",
            "summary": explanation.summary,
            "limitations": explanation.limitations,
        }
    )
    events.append({"type": "report_chunk", "content": explanation.markdown})
    events.append(
        {
            "type": "done",
            "session_id": state.get("session_id", ""),
            "explanation_id": state.get("session_id", ""),
        }
    )

    trace = _trace(state, "build_explanation", "Synthesize explainable report", explanation.summary)

    return {
        "explanation": explanation,
        "events": events,
        "reasoning_trace": trace,
        "status": "done",
    }
