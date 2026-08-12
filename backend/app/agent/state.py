from typing import Annotated, Any, Literal, TypedDict

from langgraph.graph.message import add_messages

from app.agent.models.explanation import (
    AnalysisStep,
    ChartSpec,
    Explanation,
    QuestionInterpretation,
    ReasoningStep,
)


class Finding(TypedDict):
    id: str
    step_id: str
    goal: str
    tool: str
    sql: str
    result_rows: list[dict]
    result_summary: str
    computed_metrics: dict[str, float | str | int | None]


class AgentEvent(TypedDict, total=False):
    type: str
    node: str
    message: str
    tool: str
    sql: str
    row_count: int
    id: str
    summary: str
    spec: dict
    finding_id: str
    text: str
    evidence_ids: list[str]
    content: str
    session_id: str
    explanation_id: str
    limitations: list[str]


class AgentState(TypedDict, total=False):
    dataset_id: str
    session_id: str
    question: str
    csv_path: str
    schema_profile: dict
    interpretation: QuestionInterpretation
    plan: list[AnalysisStep]
    current_step_index: int
    findings: list[Finding]
    charts: list[ChartSpec]
    explanation: Explanation
    reasoning_trace: list[ReasoningStep]
    events: list[AgentEvent]
    evaluation: dict
    messages: Annotated[list, add_messages]
    status: Literal["running", "done", "error"]
    error: str
