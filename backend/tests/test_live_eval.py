"""End-to-end evaluation against a real LLM.

Deselected by default. Run with an API key configured:

    pytest -m live
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from app.agent.graph import build_graph
from app.config import settings
from app.data.profiler import profile_dataset

REPO_ROOT = Path(__file__).resolve().parents[2]
BANK = yaml.safe_load((Path(__file__).resolve().parent / "eval" / "questions.yaml").read_text())

pytestmark = pytest.mark.live


def _has_key() -> bool:
    provider = settings.llm_provider.lower()
    return bool(
        {
            "groq": settings.groq_api_key,
            "openai": settings.openai_api_key,
            "anthropic": settings.anthropic_api_key,
        }.get(provider)
    )


@pytest.fixture(scope="module")
def profiles() -> dict[str, tuple[Path, dict[str, Any]]]:
    out = {}
    for name, spec in BANK["datasets"].items():
        path = REPO_ROOT / spec["file"]
        out[name] = (path, profile_dataset(path))
    return out


@pytest.mark.asyncio
@pytest.mark.parametrize("case", BANK["questions"], ids=lambda c: c["id"])
async def test_question(case: dict[str, Any], profiles) -> None:
    if not _has_key():
        pytest.skip(f"no API key for LLM_PROVIDER={settings.llm_provider}")

    csv_path, profile = profiles[case["dataset"]]
    final = await build_graph().ainvoke(
        {
            "dataset_id": case["dataset"],
            "session_id": case["id"],
            "question": case["question"],
            "csv_path": str(csv_path),
            "schema_profile": profile,
            "findings": [],
            "charts": [],
            "reasoning_trace": [],
            "events": [],
            "current_step_index": 0,
            "status": "running",
        },
        {"recursion_limit": 50},
    )
    expect = case["expect"]

    # A run must always terminate cleanly, even when it cannot answer.
    assert final.get("status") in ("done", "degraded"), final.get("error")

    if expect.get("answerable") is False:
        interpretation = final.get("interpretation")
        clarified = interpretation is not None and not interpretation.answerable
        explanation = final.get("explanation")
        hedged = explanation is not None and (
            not explanation.claims or explanation.limitations
        )
        assert clarified or hedged, "agent should decline or hedge, not invent an answer"
        return

    findings = [f for f in final.get("findings", []) if f.get("status") != "failed"]
    assert len(findings) >= expect.get("min_findings", 1)

    if intents := expect.get("intents"):
        assert final["interpretation"].intent in intents

    if columns := expect.get("columns_any"):
        all_sql = " ".join(f["sql"] for f in findings)
        assert any(c in all_sql for c in columns), all_sql

    if expect.get("requires_long_view"):
        assert any("data_long" in f["sql"] for f in findings)

    if forbidden := expect.get("forbids_measures"):
        all_sql = " ".join(f["sql"] for f in findings)
        for col in forbidden:
            for agg in ("SUM", "AVG"):
                assert f'{agg}("{col}")' not in all_sql.upper().replace("SUM (", "SUM("), (
                    f"{col} is an identifier and must not be aggregated"
                )

    explanation = final.get("explanation")
    assert explanation is not None
    for claim in explanation.claims:
        assert claim.evidence_ids
