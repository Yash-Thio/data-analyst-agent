"""Semantic profiling against the real sample datasets.

Every assertion here corresponds to a concrete misclassification the previous
profiler made on `sample-data/`.
"""

from __future__ import annotations

from typing import Any

from app.data.duckdb_engine import DuckDBEngine


def column(profile: dict[str, Any], name: str) -> dict[str, Any]:
    for col in profile["columns"]:
        if col["name"] == name:
            return col
    raise AssertionError(f"{name!r} missing from {[c['name'] for c in profile['columns']]}")


# --- 04-01-Financial Sample Data.csv ------------------------------------------


def test_padded_headers_are_trimmed(financial_profile: dict[str, Any]) -> None:
    """Pandas saw ` Units Sold `, DuckDB saw `Units Sold`; they must agree."""
    names = [c["name"] for c in financial_profile["columns"]]
    assert "Units Sold" in names
    assert "Sales" in names
    assert "Gross Sales" in names
    assert all(name == name.strip() for name in names)


def test_financial_date_format_is_month_first(financial_profile: dict[str, Any]) -> None:
    date_col = column(financial_profile, "Date")
    assert date_col["semantic_type"] == "date"
    assert date_col["date_format"] == "%m/%d/%Y"


def test_financial_dates_span_the_real_range(financial_csv) -> None:
    """Regression: D/M/YYYY misparsing collapsed all 714 rows into January."""
    with DuckDBEngine(financial_csv) as engine:
        rows, _ = engine.run_sql(
            'SELECT COUNT(DISTINCT date_trunc(\'month\', "Date")) AS months, '
            'MIN("Date") AS lo, MAX("Date") AS hi FROM data'
        )
    assert rows[0]["months"] >= 12
    assert str(rows[0]["lo"]).startswith("2013-09")
    assert str(rows[0]["hi"]).startswith("2014-12")


def test_currency_columns_are_measures(financial_profile: dict[str, Any]) -> None:
    for name in ("Sales", "Gross Sales", "Profit", "COGS", "Sale Price"):
        col = column(financial_profile, name)
        assert col["role"] == "measure", f"{name} -> {col['role']}"
        assert col["semantic_type"] in ("currency", "decimal", "integer")


def test_discounts_is_a_measure_despite_placeholder_rows(
    financial_profile: dict[str, Any]
) -> None:
    """`Discounts` is mostly ` $-   ` and used to be classified categorical."""
    col = column(financial_profile, "Discounts")
    assert col["semantic_type"] == "currency"
    assert col["role"] == "measure"
    assert "Discounts" in financial_profile["measures"]


def test_year_is_an_integer_period_not_a_date(financial_profile: dict[str, Any]) -> None:
    col = column(financial_profile, "Year")
    assert col["semantic_type"] == "integer"
    assert col["temporal_grain"] == "year"
    assert "Year" not in financial_profile["date_columns"]


def test_month_name_is_categorical(financial_profile: dict[str, Any]) -> None:
    col = column(financial_profile, "Month Name")
    assert col["semantic_type"] == "categorical"
    assert "Month Name" not in financial_profile["date_columns"]
    assert "Month Name" not in financial_profile["measures"]


def test_month_number_is_not_temporal(financial_profile: dict[str, Any]) -> None:
    assert "Month Number" not in financial_profile["date_columns"]


def test_country_casing_inconsistency_is_reported(financial_profile: dict[str, Any]) -> None:
    """`CANADA` vs `   germany   ` would otherwise split into separate groups."""
    warnings = financial_profile["quality"]["warnings"]
    assert any(w["column"] == "Country" and w["code"] == "inconsistent_casing" for w in warnings)
    assert "Country" in financial_profile["quality"]["normalized_expressions"]


def test_financial_layout_is_long(financial_profile: dict[str, Any]) -> None:
    assert financial_profile["layout"] == "long"
    assert financial_profile["long_table_name"] is None


# --- unemployment (wide) ------------------------------------------------------


def test_series_id_is_an_identifier_not_a_measure(
    unemployment_profile: dict[str, Any]
) -> None:
    """`ABIL148UR` was stripped to `148` and offered as the default metric."""
    col = column(unemployment_profile, "Series ID")
    assert col["semantic_type"] == "identifier"
    assert col["role"] == "identifier"
    assert "Series ID" not in unemployment_profile["measures"]


def test_region_code_is_an_identifier(unemployment_profile: dict[str, Any]) -> None:
    col = column(unemployment_profile, "Region Code")
    assert col["role"] == "identifier"
    assert "Region Code" not in unemployment_profile["measures"]


def test_region_name_is_a_dimension(unemployment_profile: dict[str, Any]) -> None:
    col = column(unemployment_profile, "Region Name")
    assert col["role"] == "dimension"


def test_unemployment_layout_is_wide(unemployment_profile: dict[str, Any]) -> None:
    assert unemployment_profile["layout"] == "wide"
    assert unemployment_profile["long_table_name"] == "data_long"
    wide = unemployment_profile["wide"]
    assert len(wide["value_columns"]) == 18
    assert "Region Name" in wide["id_columns"]
    assert "Series ID" in wide["id_columns"]


def test_all_null_month_is_reported(unemployment_profile: dict[str, Any]) -> None:
    col = column(unemployment_profile, "2025-10-01")
    assert col["null_pct"] == 100.0


# --- sales.csv ----------------------------------------------------------------


def test_sales_profile_still_works(sales_profile: dict[str, Any]) -> None:
    assert sales_profile["layout"] == "long"
    assert column(sales_profile, "revenue")["role"] == "measure"
    assert column(sales_profile, "date")["semantic_type"] == "date"
    assert column(sales_profile, "region")["role"] == "dimension"
    assert sales_profile["row_count"] == 16
