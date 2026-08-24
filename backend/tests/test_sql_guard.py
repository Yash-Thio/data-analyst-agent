"""Pre-execution gates for generated SQL."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.agent.sql_guard import GuardError, guard
from app.data.duckdb_engine import DuckDBEngine


@pytest.fixture
def engine(sales_csv: Path):
    with DuckDBEngine(sales_csv) as e:
        yield e


@pytest.fixture
def wide_engine(unemployment_csv: Path):
    with DuckDBEngine(unemployment_csv) as e:
        yield e


def test_accepts_a_valid_query(engine) -> None:
    sql = 'SELECT "region", SUM("revenue") AS total FROM data GROUP BY 1'
    assert guard(sql, engine) == sql


def test_accepts_ctes_and_their_self_references(engine) -> None:
    sql = (
        'WITH monthly AS (SELECT date_trunc(\'month\', "date") AS m, '
        'SUM("revenue") AS total FROM data GROUP BY 1) '
        'SELECT "m", "total" FROM monthly ORDER BY "m"'
    )
    assert guard(sql, engine)


def test_accepts_quoted_period_aliases(engine) -> None:
    """`AS "Q3 2024"` is a label, not a missing column."""
    sql = 'SELECT SUM("revenue") AS "Q3 2024" FROM data'
    assert guard(sql, engine)


@pytest.mark.parametrize(
    "sql",
    [
        'DROP TABLE data',
        'SELECT * FROM data; DROP TABLE data',
        'INSERT INTO data VALUES (1)',
        'CREATE TABLE evil AS SELECT 1',
        'PRAGMA database_list',
        'ATTACH \'other.db\' AS other',
        '',
    ],
)
def test_rejects_non_read_only_sql(engine, sql: str) -> None:
    with pytest.raises(GuardError) as excinfo:
        guard(sql, engine)
    assert excinfo.value.stage == "static"


@pytest.mark.parametrize(
    "sql",
    [
        "SELECT * FROM read_csv('/etc/passwd')",
        "SELECT * FROM read_parquet('/tmp/x.parquet')",
        "SELECT * FROM glob('/**')",
    ],
)
def test_rejects_filesystem_access(engine, sql: str) -> None:
    with pytest.raises(GuardError):
        guard(sql, engine)


def test_string_literals_do_not_trip_keyword_checks(engine) -> None:
    """A value that happens to contain a keyword is data, not a statement."""
    sql = "SELECT * FROM data WHERE \"product\" = 'drop table update'"
    assert guard(sql, engine)


def test_rejects_unknown_tables(engine) -> None:
    with pytest.raises(GuardError) as excinfo:
        guard('SELECT * FROM customers', engine)
    assert excinfo.value.stage == "tables"
    assert "data" in excinfo.value.suggestions


def test_suggests_the_closest_column(engine) -> None:
    with pytest.raises(GuardError) as excinfo:
        guard('SELECT "revenues" FROM data', engine)
    assert excinfo.value.stage == "identifiers"
    assert "revenue" in excinfo.value.suggestions
    assert "Did you mean" in str(excinfo.value)


def test_explain_catches_errors_static_checks_miss(engine) -> None:
    """Unquoted hallucinated columns only surface at bind time."""
    with pytest.raises(GuardError) as excinfo:
        guard("SELECT nonexistent_column FROM data", engine)
    assert excinfo.value.stage == "explain"


def test_explain_catches_type_errors(engine) -> None:
    with pytest.raises(GuardError) as excinfo:
        guard('SELECT SUM("region") FROM data', engine)
    assert excinfo.value.stage == "explain"


def test_dry_run_does_not_execute(engine) -> None:
    """EXPLAIN must not raise on a query that would be expensive to run."""
    guard('SELECT "region" FROM data ORDER BY "revenue" DESC', engine)


def test_long_view_is_allowed_for_wide_datasets(wide_engine) -> None:
    sql = 'SELECT "Region Name", AVG("value") FROM data_long GROUP BY 1'
    assert guard(sql, wide_engine)


def test_long_view_is_rejected_for_tidy_datasets(engine) -> None:
    with pytest.raises(GuardError) as excinfo:
        guard('SELECT * FROM data_long', engine)
    assert excinfo.value.stage == "tables"
