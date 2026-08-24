"""Semantic profile of an uploaded CSV.

Produces the schema the agent reasons about: not just dtypes, but what each
column *is for*. The distinction that matters most is measure vs dimension vs
identifier - `Series ID` looks numeric-ish and is unique per row, but summing
it is meaningless, and the previous profiler offered it as the default metric.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.data.duckdb_engine import TABLE_NAME, DuckDBEngine
from app.data.quality import assess_quality
from app.data.reshape import LONG_TABLE_NAME
from app.data.typing import ColumnPlan, quote_ident

SAMPLE_VALUES = 5
TOP_VALUES = 8
MAX_TOP_VALUE_CARDINALITY = 500
NEARLY_UNIQUE = 0.95

_ID_NAME = re.compile(
    r"(?:^|[\s_\-])(id|ids|code|codes|key|keys|uuid|guid|sku|isbn|ssn|ein)(?:[\s_\-]|$)",
    re.IGNORECASE,
)

ROLE_MEASURE = "measure"
ROLE_DIMENSION = "dimension"
ROLE_TEMPORAL = "temporal"
ROLE_IDENTIFIER = "identifier"


def profile_dataset(csv_path: Path) -> dict[str, Any]:
    with DuckDBEngine(Path(csv_path)) as engine:
        return build_profile(engine)


def build_profile(engine: DuckDBEngine) -> dict[str, Any]:
    schema = engine.schema
    plans = schema.columns
    row_count = engine.get_row_count()
    duckdb_types = dict(engine.get_columns())

    stats = _collect_stats(engine, plans, row_count)
    stats["__row_count__"] = {"value": row_count}

    columns: list[dict[str, Any]] = []
    for plan in plans:
        col_stats = stats.get(plan.name, {})
        role = _classify_role(plan, col_stats, row_count)
        columns.append(
            {
                "name": plan.name,
                # Identifiers are surfaced as their own type so the schema card
                # makes it obvious they are labels, not quantities.
                "semantic_type": (
                    "identifier" if role == ROLE_IDENTIFIER else plan.semantic_type
                ),
                "storage_type": plan.semantic_type,
                "duckdb_type": duckdb_types.get(plan.name, "VARCHAR"),
                "role": role,
                "null_count": int(col_stats.get("null_count") or 0),
                "null_pct": round(float(col_stats.get("null_pct") or 0.0), 2),
                "unique_count": int(col_stats.get("unique_count") or 0),
                "unique_ratio": round(float(col_stats.get("unique_ratio") or 0.0), 4),
                "sample_values": col_stats.get("sample_values") or [],
                "stats": col_stats.get("numeric_stats"),
                "date_range": col_stats.get("date_range"),
                "top_values": col_stats.get("top_values"),
                "date_format": plan.date_format,
                "temporal_grain": plan.temporal_grain,
                "warnings": list(plan.warnings),
                "notes": list(plan.notes),
            }
        )

    quality = assess_quality(engine, plans, stats)
    by_role = lambda role: [c["name"] for c in columns if c["role"] == role]  # noqa: E731

    layout = schema.wide_layout
    return {
        "table_name": TABLE_NAME,
        "long_table_name": LONG_TABLE_NAME if layout else None,
        "layout": "wide" if layout else "long",
        "row_count": row_count,
        "column_count": len(columns),
        "columns": columns,
        "measures": by_role(ROLE_MEASURE),
        "dimensions": by_role(ROLE_DIMENSION),
        "temporal": by_role(ROLE_TEMPORAL),
        "identifiers": by_role(ROLE_IDENTIFIER),
        # Kept for consumers that only care about castable date columns.
        "date_columns": [c["name"] for c in columns if c["semantic_type"] in ("date", "datetime")],
        "numeric_columns": by_role(ROLE_MEASURE),
        "categorical_columns": by_role(ROLE_DIMENSION),
        "quality": quality.as_dict(),
        "wide": layout.as_dict() if layout else None,
        "long_columns": list(schema.long_columns),
    }


def _classify_role(plan: ColumnPlan, stats: dict, row_count: int) -> str:
    if plan.temporal_grain or plan.is_temporal:
        return ROLE_TEMPORAL

    unique_ratio = float(stats.get("unique_ratio") or 0.0)
    nearly_unique = row_count > 1 and unique_ratio >= NEARLY_UNIQUE
    id_named = bool(_ID_NAME.search(plan.name))

    # An id-ish name only wins when the values back it up: unique per row, or
    # not a number at all. `Order Count` stays a measure.
    if id_named and (nearly_unique or not plan.is_numeric):
        return ROLE_IDENTIFIER
    if plan.is_numeric:
        return ROLE_MEASURE
    if plan.semantic_type == "boolean":
        return ROLE_DIMENSION
    return ROLE_DIMENSION


def _collect_stats(
    engine: DuckDBEngine, plans: list[ColumnPlan], row_count: int
) -> dict[str, dict]:
    """One pass for counts, then targeted follow-ups for previews."""
    if not plans:
        return {}

    selects: list[str] = []
    for i, plan in enumerate(plans):
        col = quote_ident(plan.name)
        selects.append(f"COUNT({col}) AS c{i}")
        selects.append(f"COUNT(DISTINCT {col}) AS u{i}")
        if _casing_candidate(plan):
            selects.append(f"COUNT(DISTINCT UPPER(TRIM({col}))) AS n{i}")

    aggregate = _safe_query(engine, f"SELECT {', '.join(selects)} FROM {TABLE_NAME}")
    row = aggregate[0] if aggregate else {}

    stats: dict[str, dict] = {}
    for i, plan in enumerate(plans):
        non_null = int(row.get(f"c{i}") or 0)
        unique_count = int(row.get(f"u{i}") or 0)
        null_count = max(0, row_count - non_null)
        entry: dict[str, Any] = {
            "null_count": null_count,
            "null_pct": (null_count / row_count * 100) if row_count else 0.0,
            "unique_count": unique_count,
            "unique_ratio": (unique_count / row_count) if row_count else 0.0,
            "sample_values": _sample_values(engine, plan),
        }
        if f"n{i}" in row:
            entry["normalized_unique_count"] = int(row.get(f"n{i}") or 0)
            if entry["normalized_unique_count"] < unique_count:
                entry["casing_examples"] = _casing_examples(engine, plan)

        if plan.is_numeric:
            entry["numeric_stats"] = _numeric_stats(engine, plan)
        elif plan.is_temporal:
            entry["date_range"] = _date_range(engine, plan)
        elif unique_count and unique_count <= MAX_TOP_VALUE_CARDINALITY:
            entry["top_values"] = _top_values(engine, plan)

        stats[plan.name] = entry
    return stats


def _casing_candidate(plan: ColumnPlan) -> bool:
    return plan.semantic_type in ("categorical", "boolean")


def _sample_values(engine: DuckDBEngine, plan: ColumnPlan) -> list[str]:
    col = quote_ident(plan.name)
    rows = _safe_query(
        engine,
        f"SELECT DISTINCT {col} AS v FROM {TABLE_NAME} "
        f"WHERE {col} IS NOT NULL LIMIT {SAMPLE_VALUES}",
    )
    return [str(r["v"]) for r in rows]


def _numeric_stats(engine: DuckDBEngine, plan: ColumnPlan) -> dict[str, float | None]:
    col = quote_ident(plan.name)
    rows = _safe_query(
        engine,
        f"SELECT MIN({col}) AS lo, MAX({col}) AS hi, AVG({col}) AS mean, "
        f"MEDIAN({col}) AS mid, SUM({col}) AS total FROM {TABLE_NAME}",
    )
    if not rows:
        return {}
    row = rows[0]
    return {
        "min": _round(row.get("lo")),
        "max": _round(row.get("hi")),
        "mean": _round(row.get("mean")),
        "median": _round(row.get("mid")),
        "sum": _round(row.get("total")),
    }


def _date_range(engine: DuckDBEngine, plan: ColumnPlan) -> dict[str, str | None]:
    col = quote_ident(plan.name)
    rows = _safe_query(
        engine, f"SELECT MIN({col}) AS lo, MAX({col}) AS hi FROM {TABLE_NAME}"
    )
    if not rows:
        return {}
    lo, hi = rows[0].get("lo"), rows[0].get("hi")
    return {"min": str(lo) if lo is not None else None, "max": str(hi) if hi is not None else None}


def _top_values(engine: DuckDBEngine, plan: ColumnPlan) -> dict[str, int]:
    col = quote_ident(plan.name)
    rows = _safe_query(
        engine,
        f"SELECT {col} AS v, COUNT(*) AS n FROM {TABLE_NAME} "
        f"WHERE {col} IS NOT NULL GROUP BY 1 ORDER BY n DESC LIMIT {TOP_VALUES}",
    )
    return {str(r["v"]): int(r["n"]) for r in rows}


def _casing_examples(engine: DuckDBEngine, plan: ColumnPlan) -> list[str]:
    """Actual values that collide once case is normalised."""
    col = quote_ident(plan.name)
    rows = _safe_query(
        engine,
        f"SELECT string_agg(DISTINCT {col}, ' / ') AS variants FROM {TABLE_NAME} "
        f"WHERE {col} IS NOT NULL GROUP BY UPPER(TRIM({col})) "
        f"HAVING COUNT(DISTINCT {col}) > 1 LIMIT {TOP_VALUES}",
    )
    return [str(r["variants"]) for r in rows if r.get("variants")]


def _safe_query(engine: DuckDBEngine, sql: str) -> list[dict[str, Any]]:
    """Profiling must never be the reason an upload fails."""
    try:
        rows, _ = engine.run_sql(sql, limit=MAX_TOP_VALUE_CARDINALITY)
        return rows
    except Exception:
        return []


def _round(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return round(float(value), 4)
    except (TypeError, ValueError):
        return None
