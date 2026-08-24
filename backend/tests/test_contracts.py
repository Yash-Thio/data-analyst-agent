"""Contracts the LLM boundary depends on.

Groq's strict JSON-schema mode rejects unions, optional properties and
free-form objects, so every model the agent asks the LLM to fill in has to
stay inside that subset.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool

from app.agent.models.explanation import (
    AnalysisPlan,
    AnalysisStep,
    EvaluationResult,
    ExplanationDraft,
    QuestionInterpretation,
    SqlFix,
)

LLM_FACING_MODELS = [
    QuestionInterpretation,
    AnalysisPlan,
    EvaluationResult,
    ExplanationDraft,
    SqlFix,
]


def _walk(obj: Any, path: str = "$") -> list[tuple[str, dict]]:
    found: list[tuple[str, dict]] = []
    if isinstance(obj, dict):
        found.append((path, obj))
        for key, value in obj.items():
            found.extend(_walk(value, f"{path}.{key}"))
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            found.extend(_walk(value, f"{path}[{i}]"))
    return found


@pytest.mark.parametrize("model", LLM_FACING_MODELS, ids=lambda m: m.__name__)
def test_structured_output_models_are_strict(model: type) -> None:
    schema = convert_to_openai_tool(model, strict=True)["function"]["parameters"]
    issues: list[str] = []

    for path, node in _walk(schema):
        if node.get("anyOf"):
            issues.append(f"{path}: unions are not supported ({node['anyOf']})")
        if "properties" in node:
            if node.get("additionalProperties") is not False:
                issues.append(f"{path}: additionalProperties must be false")
            missing = set(node["properties"]) - set(node.get("required") or [])
            if missing:
                issues.append(f"{path}: optional properties {sorted(missing)}")

    assert not issues, "\n".join(issues)


def test_analysis_step_carries_sql_not_template_parameters() -> None:
    fields = set(AnalysisStep.model_fields)
    assert "sql" in fields
    assert not fields & {"tool", "params"}


def test_interpretation_can_decline_a_question() -> None:
    fields = set(QuestionInterpretation.model_fields)
    assert {"answerable", "clarification"} <= fields


def test_interpretation_supports_non_temporal_intents() -> None:
    intents = QuestionInterpretation.model_fields["intent"].annotation.__args__
    assert {"aggregate", "ranking", "distribution", "correlation", "lookup"} <= set(intents)


def test_evaluation_can_request_follow_up_work() -> None:
    assert "follow_up_goals" in EvaluationResult.model_fields


def test_template_tools_are_gone() -> None:
    """The rigid period-comparison helpers must not come back."""
    import app.agent.tools.analytics as analytics

    for removed in ("compare_periods", "top_contributors", "run_sql"):
        assert not hasattr(analytics, removed), removed

    with pytest.raises(ModuleNotFoundError):
        import app.agent.plan_repair  # noqa: F401
