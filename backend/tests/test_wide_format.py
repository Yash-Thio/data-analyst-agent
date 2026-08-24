"""Wide (pivoted) CSVs.

The unemployment sample stores 18 months as column headers. The previous
implementation found no date column at all and aborted the whole run.
"""

from __future__ import annotations

from pathlib import Path

from app.data.duckdb_engine import DuckDBEngine
from app.data.reshape import detect_wide_layout


def test_detects_the_monthly_columns(unemployment_csv: Path) -> None:
    with DuckDBEngine(unemployment_csv) as engine:
        names = [name for name, _ in engine.get_columns()]
    layout = detect_wide_layout(names)
    assert layout is not None
    assert len(layout.value_columns) == 18
    assert layout.value_columns[0] == "2025-01-01"
    assert layout.id_columns == [
        "Series ID",
        "Series Name",
        "Units",
        "Region Name",
        "Region Code",
    ]
    assert layout.period_grain == "month"


def test_tidy_csv_is_not_treated_as_wide(sales_csv: Path) -> None:
    with DuckDBEngine(sales_csv) as engine:
        names = [name for name, _ in engine.get_columns()]
    assert detect_wide_layout(names) is None


def test_long_view_is_queryable(unemployment_csv: Path) -> None:
    with DuckDBEngine(unemployment_csv) as engine:
        rows, _ = engine.run_sql(
            'SELECT "Region Name", "period", "value" FROM data_long '
            "WHERE \"Region Name\" = 'Akron, OH' ORDER BY \"period\" LIMIT 3"
        )
    assert len(rows) == 3
    assert str(rows[0]["period"]) == "2025-01-01"
    assert rows[0]["value"] == 5.0


def test_long_view_drops_the_empty_month(unemployment_csv: Path) -> None:
    """2025-10-01 is blank for every region and must not appear as a null row."""
    with DuckDBEngine(unemployment_csv) as engine:
        rows, _ = engine.run_sql(
            "SELECT COUNT(*) AS n FROM data_long WHERE \"period\" = DATE '2025-10-01'"
        )
    assert rows[0]["n"] == 0


def test_average_by_region_works(unemployment_csv: Path) -> None:
    """The exact question the old template tools could not express."""
    with DuckDBEngine(unemployment_csv) as engine:
        rows, _ = engine.run_sql(
            'SELECT "Region Name", ROUND(AVG("value"), 2) AS avg_rate '
            'FROM data_long GROUP BY 1 ORDER BY avg_rate DESC LIMIT 5'
        )
    assert len(rows) == 5
    assert rows[0]["avg_rate"] >= rows[-1]["avg_rate"]
    assert all(isinstance(r["avg_rate"], float) for r in rows)


def test_wide_table_is_still_directly_queryable(unemployment_csv: Path) -> None:
    with DuckDBEngine(unemployment_csv) as engine:
        rows, _ = engine.run_sql('SELECT "Region Name", "2025-01-01" FROM data LIMIT 1')
    assert rows[0]["2025-01-01"] == 3.3
