"""Bounded self-repair for generated SQL.

A first-attempt query fails for mundane reasons - a column named slightly
differently, a filter that excludes everything, an aggregate over text. None of
those should end the analysis, so each step gets a few attempts with the exact
error (and any "did you mean" hints) fed back.

An empty result counts as a failure worth retrying once: a query that returns
no rows cannot support a claim, and it is usually an over-tight filter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from app.agent.models.explanation import SqlFix
from app.agent.sql_guard import GuardError, guard
from app.data.duckdb_engine import DuckDBEngine, QueryResult
from app.llm.base import Message

MAX_ATTEMPTS = 3

AttemptCallback = Callable[["RepairAttempt"], None]


@dataclass
class RepairAttempt:
    attempt: int
    sql: str
    error: str
    stage: str
    suggestions: list[str] = field(default_factory=list)
    fixed_sql: str = ""
    note: str = ""


@dataclass
class ExecutionOutcome:
    status: str  # "ok" | "empty" | "failed"
    sql: str
    result: QueryResult | None = None
    error: str = ""
    attempts: list[RepairAttempt] = field(default_factory=list)

    @property
    def rows(self) -> list[dict]:
        return self.result.rows if self.result else []

    @property
    def succeeded(self) -> bool:
        return self.status == "ok"


_SYSTEM = (
    "You repair DuckDB SQL. Return one corrected SELECT statement that answers "
    "the stated goal against the given schema. Change only what is necessary."
)


async def execute_with_repair(
    engine: DuckDBEngine,
    sql: str,
    *,
    goal: str,
    question: str,
    schema_card: str,
    llm,
    max_attempts: int = MAX_ATTEMPTS,
    on_attempt: AttemptCallback | None = None,
    allow_empty_retry: bool = True,
) -> ExecutionOutcome:
    attempts: list[RepairAttempt] = []
    current = sql
    empty_retried = False

    for attempt in range(1, max_attempts + 1):
        error, stage, suggestions = "", "", []
        result: QueryResult | None = None

        try:
            checked = guard(current, engine)
            result = engine.execute(checked)
        except GuardError as exc:
            error, stage, suggestions = str(exc), exc.stage, list(exc.suggestions)
        except TimeoutError as exc:
            # Retrying an identical slow query will not help; ask for a cheaper one.
            error, stage = str(exc), "timeout"
        except Exception as exc:
            error, stage = _first_line(str(exc)), "runtime"

        if result is not None and (result.rows or not allow_empty_retry or empty_retried):
            return ExecutionOutcome(
                status="ok" if result.rows else "empty",
                sql=result.sql,
                result=result,
                attempts=attempts,
            )

        if result is not None:
            empty_retried = True
            error, stage = (
                "The query ran but returned zero rows, so it cannot support a "
                "finding. The filters are probably too narrow or reference values "
                "that do not exist.",
                "empty",
            )

        record = RepairAttempt(
            attempt=attempt, sql=current, error=error, stage=stage, suggestions=suggestions
        )

        if attempt == max_attempts:
            attempts.append(record)
            if on_attempt:
                on_attempt(record)
            return ExecutionOutcome(status="failed", sql=current, error=error, attempts=attempts)

        try:
            fix = await _ask_for_fix(
                llm,
                sql=current,
                error=error,
                suggestions=suggestions,
                goal=goal,
                question=question,
                schema_card=schema_card,
            )
        except Exception as exc:
            record.note = f"Repair request failed: {_first_line(str(exc))}"
            attempts.append(record)
            if on_attempt:
                on_attempt(record)
            return ExecutionOutcome(status="failed", sql=current, error=error, attempts=attempts)

        record.fixed_sql = fix.sql
        record.note = fix.explanation
        attempts.append(record)
        if on_attempt:
            on_attempt(record)

        if not fix.sql.strip() or fix.sql.strip() == current.strip():
            return ExecutionOutcome(status="failed", sql=current, error=error, attempts=attempts)
        current = fix.sql.strip()

    return ExecutionOutcome(status="failed", sql=current, error="exhausted attempts", attempts=attempts)


async def _ask_for_fix(
    llm,
    *,
    sql: str,
    error: str,
    suggestions: list[str],
    goal: str,
    question: str,
    schema_card: str,
) -> SqlFix:
    hint = (
        f"\nColumns that exist and look similar: {', '.join(suggestions)}"
        if suggestions
        else ""
    )
    prompt = f"""This query failed. Rewrite it so it works.

User question: {question}
Step goal: {goal}

Failing SQL:
{sql}

Error:
{error}{hint}

{schema_card}

Return the corrected SQL and a one-sentence explanation of the fix."""

    fix = await llm.complete(
        [Message("system", _SYSTEM), Message("user", prompt)], response_format=SqlFix
    )
    if not isinstance(fix, SqlFix):
        raise TypeError(f"Expected SqlFix, got {type(fix).__name__}")
    return fix


def _first_line(text: str) -> str:
    return text.strip().splitlines()[0] if text.strip() else text
