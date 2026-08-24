"""Structured contracts between the agent's nodes and the UI.

Models the LLM fills in are constrained for strict JSON-schema providers
(Groq in particular): every property required, no unions, no free-form objects.
Models assembled in Python are free to be richer.
"""

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

Intent = Literal[
    "aggregate",
    "comparison",
    "trend",
    "ranking",
    "distribution",
    "correlation",
    "root_cause",
    "lookup",
    "summary",
]

Confidence = Literal["high", "medium", "low"]


# --------------------------------------------------------------------------
# LLM-facing models (strict schema)
# --------------------------------------------------------------------------


class QuestionInterpretation(BaseModel):
    """What the user is actually asking of *this* dataset.

    `answerable` is the important field: a question about data that is not in
    the CSV should produce a clarification, never an invented analysis.
    """

    model_config = ConfigDict(extra="forbid")

    intent: Intent
    metric: str
    metric_columns: list[str]
    dimensions: list[str]
    time_scope: str
    comparison_scope: str
    answerable: bool
    clarification: str
    notes: str


class AnalysisStep(BaseModel):
    """One query. The planner writes SQL directly - there are no templates."""

    model_config = ConfigDict(extra="forbid")

    id: str
    goal: str
    sql: str
    expected_shape: Literal["scalar", "series", "table"]
    rationale: str


class AnalysisPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: list[AnalysisStep]


class SqlFix(BaseModel):
    """A repaired query plus what was wrong with the previous attempt."""

    model_config = ConfigDict(extra="forbid")

    sql: str
    explanation: str


class EvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sufficient: bool
    reason: str
    follow_up_goals: list[str]


class Claim(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    text: str
    evidence_ids: list[str]
    confidence: Confidence

    @field_validator("evidence_ids")
    @classmethod
    def non_empty_evidence(cls, value: list[str]) -> list[str]:
        if not value:
            raise ValueError("Claim must reference at least one evidence record")
        return value


class ExplanationDraft(BaseModel):
    """The narrative half of the report. Evidence is assembled in Python."""

    model_config = ConfigDict(extra="forbid")

    summary: str
    claims: list[Claim]
    limitations: list[str]
    markdown: str


# --------------------------------------------------------------------------
# Python-assembled models
# --------------------------------------------------------------------------


class Evidence(BaseModel):
    id: str
    finding_id: str
    sql: str
    result_preview: list[dict]
    metrics: dict[str, float | str | int | None]
    row_count: int = 0
    truncated: bool = False
    chart_id: str | None = None


class ReasoningStep(BaseModel):
    order: int
    node: str
    description: str
    output_summary: str


class ClaimCheck(BaseModel):
    """Result of checking a claim's numbers against its own evidence."""

    claim_id: str
    status: Literal["verified", "unverified", "rejected"]
    detail: str
    unmatched_numbers: list[float] = []


class ChartSpec(BaseModel):
    id: str
    finding_id: str
    type: Literal["bar", "line", "area"]
    title: str
    data: list[dict]
    x_key: str
    y_key: str


class Explanation(BaseModel):
    summary: str
    claims: list[Claim]
    evidence: list[Evidence]
    reasoning_trace: list[ReasoningStep]
    limitations: list[str]
    markdown: str
    checks: list[ClaimCheck] = []
    degraded: bool = False

    @model_validator(mode="after")
    def validate_claim_evidence_links(self) -> "Explanation":
        evidence_ids = {e.id for e in self.evidence}
        for claim in self.claims:
            for eid in claim.evidence_ids:
                if eid not in evidence_ids:
                    raise ValueError(f"Claim {claim.id} references unknown evidence {eid}")
        return self
