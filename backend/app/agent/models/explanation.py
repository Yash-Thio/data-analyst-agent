from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator


class Evidence(BaseModel):
    id: str
    finding_id: str
    sql: str
    result_preview: list[dict]
    metrics: dict[str, float | str | int | None]
    chart_id: str | None = None


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    evidence_ids: list[str]
    confidence: Literal["high", "medium", "low"]

    @field_validator("evidence_ids")
    @classmethod
    def non_empty_evidence(cls, v: list[str]) -> list[str]:
        if not v:
            raise ValueError("Claim must reference at least one evidence record")
        return v


class ReasoningStep(BaseModel):
    order: int
    node: str
    description: str
    output_summary: str


class ExplanationDraft(BaseModel):
    """LLM-generated portion of the explanation."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    claims: list[Claim]
    limitations: list[str]
    markdown: str


class Explanation(BaseModel):
    summary: str
    claims: list[Claim]
    evidence: list[Evidence]
    reasoning_trace: list[ReasoningStep]
    limitations: list[str]
    markdown: str

    @model_validator(mode="after")
    def validate_claim_evidence_links(self) -> "Explanation":
        evidence_ids = {e.id for e in self.evidence}
        for claim in self.claims:
            for eid in claim.evidence_ids:
                if eid not in evidence_ids:
                    raise ValueError(f"Claim {claim.id} references unknown evidence {eid}")
        return self


class QuestionInterpretation(BaseModel):
    """All fields required for Groq/OpenAI strict JSON schema compatibility."""

    model_config = ConfigDict(extra="forbid")

    metric: str
    metric_column: str | None
    period: str
    comparison_period: str
    intent: Literal["root_cause", "trend", "comparison", "summary", "other"]
    dimensions_of_interest: list[str]
    notes: str


class StepParams(BaseModel):
    """Explicit tool args — free-form dicts break Groq strict structured output.

    All fields are required for strict JSON schema. Unused string fields should be "".
    """

    model_config = ConfigDict(extra="forbid")

    metric_col: str
    date_col: str
    period_a_label: str
    period_a_filter: str
    period_b_label: str
    period_b_filter: str
    group_by: str
    dimension_col: str
    limit: int
    sql: str

    def to_tool_kwargs(self, tool: str) -> dict[str, Any]:
        if tool == "run_sql":
            return {"sql": self.sql}
        if tool == "compare_periods":
            kwargs: dict[str, Any] = {
                "metric_col": self.metric_col,
                "date_col": self.date_col,
                "period_a_label": self.period_a_label,
                "period_a_filter": self.period_a_filter,
                "period_b_label": self.period_b_label,
                "period_b_filter": self.period_b_filter,
            }
            if self.group_by.strip():
                kwargs["group_by"] = self.group_by
            return kwargs
        if tool == "top_contributors":
            return {
                "metric_col": self.metric_col,
                "date_col": self.date_col,
                "dimension_col": self.dimension_col,
                "period_a_filter": self.period_a_filter,
                "period_b_filter": self.period_b_filter,
                "period_a_label": self.period_a_label or "period_a",
                "period_b_label": self.period_b_label or "period_b",
                "limit": self.limit if self.limit > 0 else 10,
            }
        raise ValueError(f"Unknown tool: {tool}")


class AnalysisStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    goal: str
    tool: Literal["compare_periods", "top_contributors", "run_sql"]
    params: StepParams


class AnalysisPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[AnalysisStep]


class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sufficient: bool
    reason: str


class ChartSpec(BaseModel):
    id: str
    finding_id: str
    type: Literal["bar", "line", "area"]
    title: str
    data: list[dict]
    x_key: str
    y_key: str


class ExplanationDraftInput(BaseModel):
    summary: str
    claims: list[Claim]
    limitations: list[str]
    markdown: str
