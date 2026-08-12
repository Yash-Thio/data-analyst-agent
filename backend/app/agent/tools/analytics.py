from pathlib import Path
from typing import Any

from app.data.duckdb_engine import DuckDBEngine, TABLE_NAME


def get_schema(profile: dict[str, Any]) -> dict[str, Any]:
    return {
        "table_name": profile.get("table_name", TABLE_NAME),
        "row_count": profile.get("row_count"),
        "columns": profile.get("columns", []),
        "date_columns": profile.get("date_columns", []),
        "numeric_columns": profile.get("numeric_columns", []),
        "categorical_columns": profile.get("categorical_columns", []),
    }


def run_sql(csv_path: Path, sql: str) -> dict[str, Any]:
    with DuckDBEngine(csv_path) as engine:
        rows, executed_sql = engine.run_sql(sql)
    return {"sql": executed_sql, "rows": rows, "row_count": len(rows)}


def compare_periods(
    csv_path: Path,
    metric_col: str,
    date_col: str,
    period_a_label: str,
    period_a_filter: str,
    period_b_label: str,
    period_b_filter: str,
    group_by: str | None = None,
) -> dict[str, Any]:
    group_clause = f", {group_by}" if group_by else ""
    group_select = f", {group_by} AS dimension" if group_by else ""
    group_by_clause = f"GROUP BY {group_by}" if group_by else ""

    sql = f"""
SELECT
    '{period_a_label}' AS period{group_select},
    SUM(CAST("{metric_col}" AS DOUBLE)) AS total
FROM {TABLE_NAME}
WHERE {period_a_filter}
{group_by_clause}

UNION ALL

SELECT
    '{period_b_label}' AS period{group_select},
    SUM(CAST("{metric_col}" AS DOUBLE)) AS total
FROM {TABLE_NAME}
WHERE {period_b_filter}
{group_by_clause}
"""
    with DuckDBEngine(csv_path) as engine:
        rows, executed_sql = engine.run_sql(sql)

    metrics: dict[str, float | str | int | None] = {}
    if not group_by and len(rows) >= 2:
        a_total = next((r["total"] for r in rows if r.get("period") == period_a_label), 0) or 0
        b_total = next((r["total"] for r in rows if r.get("period") == period_b_label), 0) or 0
        delta_abs = float(b_total) - float(a_total)
        delta_pct = (delta_abs / float(a_total) * 100) if a_total else 0
        metrics = {
            f"{period_a_label}_total": float(a_total),
            f"{period_b_label}_total": float(b_total),
            "delta_abs": round(delta_abs, 4),
            "delta_pct": round(delta_pct, 2),
        }

    return {
        "sql": executed_sql.strip(),
        "rows": rows,
        "metrics": metrics,
        "summary": _compare_summary(period_a_label, period_b_label, metrics, group_by),
    }


def top_contributors(
    csv_path: Path,
    metric_col: str,
    date_col: str,
    dimension_col: str,
    period_a_filter: str,
    period_b_filter: str,
    period_a_label: str = "period_a",
    period_b_label: str = "period_b",
    limit: int = 10,
) -> dict[str, Any]:
    sql = f"""
WITH period_a AS (
    SELECT "{dimension_col}" AS dimension, SUM(CAST("{metric_col}" AS DOUBLE)) AS total
    FROM {TABLE_NAME}
    WHERE {period_a_filter}
    GROUP BY 1
),
period_b AS (
    SELECT "{dimension_col}" AS dimension, SUM(CAST("{metric_col}" AS DOUBLE)) AS total
    FROM {TABLE_NAME}
    WHERE {period_b_filter}
    GROUP BY 1
)
SELECT
    COALESCE(a.dimension, b.dimension) AS dimension,
    COALESCE(a.total, 0) AS {period_a_label},
    COALESCE(b.total, 0) AS {period_b_label},
    COALESCE(b.total, 0) - COALESCE(a.total, 0) AS delta,
    CASE
        WHEN COALESCE(a.total, 0) = 0 THEN NULL
        ELSE ROUND((COALESCE(b.total, 0) - COALESCE(a.total, 0)) / a.total * 100, 2)
    END AS delta_pct
FROM period_a a
FULL OUTER JOIN period_b b ON a.dimension = b.dimension
ORDER BY delta ASC
LIMIT {limit}
"""
    with DuckDBEngine(csv_path) as engine:
        rows, executed_sql = engine.run_sql(sql)

    total_delta = sum(r.get("delta") or 0 for r in rows)
    if rows and total_delta:
        top = rows[0]
        share = abs(top.get("delta", 0) / total_delta * 100) if total_delta else 0
        metrics = {
            "top_contributor": str(top.get("dimension")),
            "top_delta": top.get("delta"),
            "share_of_total_change_pct": round(share, 2),
        }
    else:
        metrics = {}

    return {
        "sql": executed_sql.strip(),
        "rows": rows,
        "metrics": metrics,
        "summary": f"Top contributor: {metrics.get('top_contributor', 'N/A')}",
    }


def create_chart_spec(
    finding_id: str,
    chart_type: str,
    title: str,
    data: list[dict],
    x_key: str,
    y_key: str,
) -> dict[str, Any]:
    chart_id = f"chart-{finding_id}"
    return {
        "id": chart_id,
        "finding_id": finding_id,
        "type": chart_type,
        "title": title,
        "data": data,
        "x_key": x_key,
        "y_key": y_key,
    }


def _compare_summary(
    period_a: str,
    period_b: str,
    metrics: dict[str, Any],
    group_by: str | None,
) -> str:
    if group_by:
        return f"Compared {period_a} vs {period_b} grouped by {group_by}"
    if "delta_pct" in metrics:
        return (
            f"{period_b} vs {period_a}: "
            f"{metrics['delta_pct']}% change ({metrics.get('delta_abs')} absolute)"
        )
    return f"Compared {period_a} vs {period_b}"
