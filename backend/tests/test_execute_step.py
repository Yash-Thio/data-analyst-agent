"""`execute_step` must produce evidence or a recorded failure - never an abort."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.models.explanation import AnalysisStep, SqlFix
from app.agent.nodes import execute_step_node

GOOD = 'SELECT "region", SUM("revenue") AS total FROM data GROUP BY 1 ORDER BY total DESC'


def step(sql: str, goal: str = "Revenue by region", shape: str = "table") -> AnalysisStep:
    return AnalysisStep(id="s1", goal=goal, sql=sql, expected_shape=shape, rationale="because")


def state(csv: Path, sql: str, profile: dict) -> dict:
    return {
        "csv_path": str(csv),
        "schema_profile": profile,
        "plan": [step(sql)],
        "current_step_index": 0,
        "findings": [],
        "events": [],
        "reasoning_trace": [],
        "question": "Which region earns most?",
    }


@pytest.fixture(autouse=True)
def _llm(monkeypatch: pytest.MonkeyPatch, fake_llm):
    monkeypatch.setattr("app.agent.nodes.get_llm_provider", lambda: fake_llm)
    return fake_llm


@pytest.mark.asyncio
async def test_successful_step_records_evidence(sales_csv, sales_profile) -> None:
    result = await execute_step_node(state(sales_csv, GOOD, sales_profile))

    finding = result["findings"][0]
    assert finding["status"] == "ok"
    assert finding["result_rows"]
    assert finding["computed_metrics"]
    assert finding["sql"]
    assert result["current_step_index"] == 1


@pytest.mark.asyncio
async def test_metrics_come_from_the_data(sales_csv, sales_profile) -> None:
    result = await execute_step_node(
        state(sales_csv, 'SELECT SUM("revenue") AS total FROM data', sales_profile)
    )
    metrics = result["findings"][0]["computed_metrics"]
    assert metrics["total"] == 1_630_000


@pytest.mark.asyncio
async def test_broken_sql_is_repaired_and_reported(sales_csv, sales_profile, _llm) -> None:
    _llm.on(SqlFix, SqlFix(sql=GOOD, explanation="fixed the column name"))

    result = await execute_step_node(state(sales_csv, 'SELECT "revenues" FROM data', sales_profile))

    assert result["findings"][0]["status"] == "ok"
    retries = [e for e in result["events"] if e["type"] == "step_retry"]
    assert len(retries) == 1
    assert "revenues" in retries[0]["sql"]


@pytest.mark.asyncio
async def test_unfixable_step_degrades_instead_of_raising(sales_csv, sales_profile, _llm) -> None:
    """The old implementation raised here and killed the entire run."""
    counter = iter(range(100))
    _llm.on(SqlFix, lambda _: SqlFix(sql=f'SELECT "x{next(counter)}" FROM data', explanation="?"))

    result = await execute_step_node(state(sales_csv, 'SELECT "missing" FROM data', sales_profile))

    finding = result["findings"][0]
    assert finding["status"] == "failed"
    assert finding["result_rows"] == []
    assert "Could not be computed" in finding["result_summary"]
    assert any(e["type"] == "step_error" and e["recoverable"] for e in result["events"])
    # Crucially, the run continues.
    assert result["current_step_index"] == 1


@pytest.mark.asyncio
async def test_dangerous_sql_never_executes(sales_csv, sales_profile, _llm) -> None:
    _llm.on(SqlFix, SqlFix(sql="DROP TABLE data", explanation="no"))

    result = await execute_step_node(state(sales_csv, "DROP TABLE data", sales_profile))

    assert result["findings"][0]["status"] == "failed"


@pytest.mark.asyncio
async def test_wide_dataset_step_uses_the_long_view(
    unemployment_csv, unemployment_profile
) -> None:
    sql = (
        'SELECT "Region Name", ROUND(AVG("value"), 2) AS avg_rate '
        'FROM data_long GROUP BY 1 ORDER BY avg_rate DESC LIMIT 5'
    )
    result = await execute_step_node(state(unemployment_csv, sql, unemployment_profile))

    finding = result["findings"][0]
    assert finding["status"] == "ok"
    assert len(finding["result_rows"]) == 5


@pytest.mark.asyncio
async def test_currency_and_dates_are_already_typed(financial_csv, financial_profile) -> None:
    """No casting in the SQL, and the dates span the real range."""
    sql = (
        'SELECT date_trunc(\'month\', "Date") AS month, SUM("Sales") AS total '
        'FROM data WHERE "Date" IS NOT NULL GROUP BY 1 ORDER BY 1'
    )
    result = await execute_step_node(state(financial_csv, sql, financial_profile))

    rows = result["findings"][0]["result_rows"]
    assert result["findings"][0]["row_count"] >= 12
    assert all(isinstance(r["total"], float) for r in rows)


@pytest.mark.asyncio
async def test_step_beyond_the_plan_is_a_no_op(sales_csv, sales_profile) -> None:
    base = state(sales_csv, GOOD, sales_profile)
    base["current_step_index"] = 5
    assert await execute_step_node(base) == {}
