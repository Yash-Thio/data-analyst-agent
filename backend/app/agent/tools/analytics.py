"""Result-shaping helpers.

The period-comparison templates that used to live here are gone: they could
only express "one metric, one date column, two windows", which is a small
fraction of what people ask. The planner writes SQL instead, and what remains
is turning a result set into something summarised and chartable.
"""

from __future__ import annotations

from typing import Any

from app.data.typing import quote_ident, quote_literal  # re-exported for callers

__all__ = [
    "quote_ident",
    "quote_literal",
    "get_schema",
    "summarise_result",
    "derive_metrics",
    "choose_chart",
    "create_chart_spec",
]

MAX_CHART_POINTS = 30
MAX_METRIC_ROWS = 5
_NUMBER_TYPES = (int, float)


def get_schema(profile: dict[str, Any]) -> dict[str, Any]:
    """Machine-readable schema summary (the LLM gets `schema_card` instead)."""
    return {
        "table_name": profile.get("table_name", "data"),
        "long_table_name": profile.get("long_table_name"),
        "layout": profile.get("layout", "long"),
        "row_count": profile.get("row_count"),
        "columns": profile.get("columns", []),
        "measures": profile.get("measures", []),
        "dimensions": profile.get("dimensions", []),
        "temporal": profile.get("temporal", []),
        "identifiers": profile.get("identifiers", []),
    }


def summarise_result(goal: str, rows: list[dict], truncated: bool = False) -> str:
    if not rows:
        return f"{goal}: no rows matched."

    if len(rows) == 1 and len(rows[0]) == 1:
        (key, value), = rows[0].items()
        return f"{goal}: {key} = {_format(value)}"

    suffix = " (truncated)" if truncated else ""
    label_key = _first_label_key(rows[0])
    numeric_key = _first_numeric_key(rows[0])
    if label_key and numeric_key:
        top = rows[0]
        return (
            f"{goal}: {len(rows)} rows{suffix}; top is "
            f"{_format(top.get(label_key))} at {_format(top.get(numeric_key))}."
        )
    return f"{goal}: {len(rows)} rows{suffix}."


def derive_metrics(rows: list[dict]) -> dict[str, float | str | int | None]:
    """Pull exact numbers out of a result so claims can be checked against them.

    Only values that actually appear in the data end up here - nothing is
    inferred, which is what makes them usable as ground truth.
    """
    if not rows:
        return {}

    metrics: dict[str, float | str | int | None] = {}
    numeric_keys = [k for k, v in rows[0].items() if isinstance(v, _NUMBER_TYPES)]
    label_key = _first_label_key(rows[0])

    if len(rows) == 1:
        for key, value in rows[0].items():
            if isinstance(value, _NUMBER_TYPES):
                metrics[str(key)] = value
        return metrics

    for key in numeric_keys:
        values = [r[key] for r in rows if isinstance(r.get(key), _NUMBER_TYPES)]
        if not values:
            continue
        metrics[f"{key}__total"] = round(float(sum(values)), 4)
        metrics[f"{key}__max"] = max(values)
        metrics[f"{key}__min"] = min(values)

    if label_key and numeric_keys:
        primary = numeric_keys[0]
        for row in rows[:MAX_METRIC_ROWS]:
            label = row.get(label_key)
            value = row.get(primary)
            if label is not None and isinstance(value, _NUMBER_TYPES):
                metrics[f"{label}"] = value

    return metrics


def choose_chart(rows: list[dict], column_roles: dict[str, str]) -> dict[str, str] | None:
    """Pick axes from the shape of the result, not from hardcoded column names.

    Returns ``None`` when the result cannot sensibly be plotted, which is
    better than emitting a chart with a string on the value axis.
    """
    if len(rows) < 2:
        return None

    first = rows[0]
    numeric_keys = [
        key
        for key in first
        if all(isinstance(r.get(key), _NUMBER_TYPES) or r.get(key) is None for r in rows)
        and any(isinstance(r.get(key), _NUMBER_TYPES) for r in rows)
    ]
    if not numeric_keys:
        return None

    label_keys = [key for key in first if key not in numeric_keys]
    temporal = [k for k in first if column_roles.get(str(k)) == "temporal" or _looks_temporal(rows, k)]

    x_key = next((k for k in temporal if k not in numeric_keys), None) or (
        label_keys[0] if label_keys else None
    )
    if x_key is None:
        return None

    y_key = next((k for k in numeric_keys if k != x_key), None)
    if y_key is None:
        return None

    return {
        "x_key": str(x_key),
        "y_key": str(y_key),
        "type": "line" if x_key in temporal else "bar",
    }


def create_chart_spec(
    finding_id: str,
    chart_type: str,
    title: str,
    data: list[dict],
    x_key: str,
    y_key: str,
) -> dict[str, Any]:
    return {
        "id": f"chart-{finding_id}",
        "finding_id": finding_id,
        "type": chart_type,
        "title": title,
        "data": [
            {x_key: row.get(x_key), y_key: row.get(y_key)} for row in data[:MAX_CHART_POINTS]
        ],
        "x_key": x_key,
        "y_key": y_key,
    }


# --------------------------------------------------------------------------


def _first_numeric_key(row: dict) -> str | None:
    return next((str(k) for k, v in row.items() if isinstance(v, _NUMBER_TYPES)), None)


def _first_label_key(row: dict) -> str | None:
    return next((str(k) for k, v in row.items() if not isinstance(v, _NUMBER_TYPES)), None)


def _looks_temporal(rows: list[dict], key: Any) -> bool:
    values = [r.get(key) for r in rows if r.get(key) is not None]
    if not values:
        return False
    return all(
        isinstance(v, str) and len(v) >= 7 and v[:4].isdigit() and v[4] in "-/"
        for v in values
    )


def _format(value: Any) -> str:
    if isinstance(value, float):
        return f"{value:,.2f}".rstrip("0").rstrip(".")
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)
