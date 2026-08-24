"""The bounded repair loop around every generated query."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.models.explanation import SqlFix
from app.agent.sql_repair import execute_with_repair
from app.data.duckdb_engine import DuckDBEngine

GOOD = 'SELECT "region", SUM("revenue") AS total FROM data GROUP BY 1'


@pytest.fixture
def engine(sales_csv: Path):
    with DuckDBEngine(sales_csv) as e:
        yield e


async def _run(engine, sql, llm, **kwargs):
    return await execute_with_repair(
        engine,
        sql,
        goal="Revenue by region",
        question="Which region earns most?",
        schema_card="(schema)",
        llm=llm,
        **kwargs,
    )


@pytest.mark.asyncio
async def test_valid_query_runs_without_calling_the_model(engine, fake_llm) -> None:
    outcome = await _run(engine, GOOD, fake_llm)
    assert outcome.status == "ok"
    assert outcome.rows
    assert outcome.attempts == []
    assert fake_llm.calls == []


@pytest.mark.asyncio
async def test_bad_column_is_repaired(engine, fake_llm) -> None:
    fake_llm.on(SqlFix, SqlFix(sql=GOOD, explanation="renamed revenues to revenue"))

    outcome = await _run(engine, 'SELECT "revenues" FROM data', fake_llm)

    assert outcome.status == "ok"
    assert outcome.rows
    assert len(outcome.attempts) == 1
    assert outcome.attempts[0].stage == "identifiers"


@pytest.mark.asyncio
async def test_repair_prompt_carries_the_error_and_suggestions(engine, fake_llm) -> None:
    fake_llm.on(SqlFix, SqlFix(sql=GOOD, explanation="fixed"))

    await _run(engine, 'SELECT "revenues" FROM data', fake_llm)

    prompt = fake_llm.prompts_for(SqlFix)[0]
    assert "revenues" in prompt
    assert "revenue" in prompt
    assert "Which region earns most?" in prompt


@pytest.mark.asyncio
async def test_gives_up_after_the_attempt_budget(engine, fake_llm) -> None:
    """A model that keeps proposing new but still-broken SQL must not loop forever."""
    counter = iter(range(100))
    fake_llm.on(
        SqlFix,
        lambda _: SqlFix(sql=f'SELECT "nope{next(counter)}" FROM data', explanation="try"),
    )

    outcome = await _run(engine, 'SELECT "missing" FROM data', fake_llm, max_attempts=3)

    assert outcome.status == "failed"
    assert len(outcome.attempts) == 3
    assert outcome.error


@pytest.mark.asyncio
async def test_stops_when_the_model_repeats_itself(engine, fake_llm) -> None:
    broken = 'SELECT "missing" FROM data'
    fake_llm.on(SqlFix, SqlFix(sql=broken, explanation="unchanged"))

    outcome = await _run(engine, broken, fake_llm)

    assert outcome.status == "failed"
    assert len(outcome.attempts) == 1


@pytest.mark.asyncio
async def test_empty_result_triggers_one_retry(engine, fake_llm) -> None:
    """Zero rows cannot support a claim, so a too-narrow filter gets one more go."""
    empty = "SELECT * FROM data WHERE \"region\" = 'Atlantis'"
    fake_llm.on(SqlFix, SqlFix(sql=GOOD, explanation="widened the filter"))

    outcome = await _run(engine, empty, fake_llm)

    assert outcome.status == "ok"
    assert outcome.attempts[0].stage == "empty"


@pytest.mark.asyncio
async def test_persistently_empty_result_is_reported_not_failed(engine, fake_llm) -> None:
    empty = "SELECT * FROM data WHERE \"region\" = 'Atlantis'"
    fake_llm.on(SqlFix, SqlFix(sql=empty.replace("Atlantis", "Narnia"), explanation="tried"))

    outcome = await _run(engine, empty, fake_llm)

    assert outcome.status == "empty"
    assert outcome.rows == []


@pytest.mark.asyncio
async def test_forbidden_sql_is_not_retried_into_existence(engine, fake_llm) -> None:
    fake_llm.on(SqlFix, SqlFix(sql="DROP TABLE data", explanation="still bad"))

    outcome = await _run(engine, "DROP TABLE data", fake_llm)

    assert outcome.status == "failed"


@pytest.mark.asyncio
async def test_model_failure_ends_the_loop_cleanly(engine) -> None:
    class Broken:
        async def complete(self, messages, *, response_format=None):
            raise RuntimeError("provider is down")

    outcome = await _run(engine, 'SELECT "missing" FROM data', Broken())

    assert outcome.status == "failed"
    assert "provider is down" in outcome.attempts[-1].note
