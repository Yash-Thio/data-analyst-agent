"""Wide (pivoted) CSV support.

Plenty of real exports put periods in the header rather than in a column -
the unemployment sample has eighteen monthly columns. Those files have no date
column at all, so period analysis is impossible until they are unpivoted.

When a wide layout is detected we expose an extra `data_long` view alongside
`data`, so the agent can choose whichever shape suits the question.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from datetime import date

from app.data.typing import looks_like_date_label, quote_ident, quote_literal

MIN_VALUE_COLUMNS = 3
LONG_TABLE_NAME = "data_long"
PERIOD_COLUMN = "period"
VALUE_COLUMN = "value"


@dataclass(frozen=True)
class WideLayout:
    id_columns: list[str]
    value_columns: list[str]
    period_labels: dict[str, date]
    period_grain: str
    period_name: str = PERIOD_COLUMN
    value_name: str = VALUE_COLUMN

    def as_dict(self) -> dict:
        return {
            "id_columns": list(self.id_columns),
            "value_columns": list(self.value_columns),
            "period_labels": {k: v.isoformat() for k, v in self.period_labels.items()},
            "period_grain": self.period_grain,
            "period_name": self.period_name,
            "value_name": self.value_name,
        }


def detect_wide_layout(
    column_names: list[str], *, min_value_columns: int = MIN_VALUE_COLUMNS
) -> WideLayout | None:
    """Detect period-per-column layout from the header alone.

    Requires several date-like headers *and* at least one ordinary column to
    key them by, so a tidy table like `date, revenue, region` is untouched.
    """
    labels = {name: looks_like_date_label(name) for name in column_names}
    dated = [name for name, label in labels.items() if label is not None]

    if len(dated) < min_value_columns:
        return None
    id_columns = [name for name in column_names if labels[name] is None]
    if not id_columns:
        return None

    grains = {labels[name].grain for name in dated}  # type: ignore[union-attr]
    label_grain = grains.pop() if len(grains) == 1 else "mixed"
    period_labels = {name: labels[name].value for name in dated}  # type: ignore[union-attr]

    return WideLayout(
        id_columns=id_columns,
        value_columns=dated,
        period_labels=period_labels,
        period_grain=_infer_period_grain(list(period_labels.values()), label_grain),
    )


def _infer_period_grain(labels: list[date], fallback: str) -> str:
    """Derive the real reporting grain from the spacing of the headers.

    `2025-01-01, 2025-02-01, ...` are day-precision labels but monthly data,
    and the agent needs to know which it is to phrase periods correctly.
    """
    unique = sorted(set(labels))
    if len(unique) < 2:
        return fallback
    gap = statistics.median((b - a).days for a, b in zip(unique, unique[1:]))
    if all(d.day == 1 for d in unique):
        if 28 <= gap <= 31:
            return "month"
        if 89 <= gap <= 92:
            return "quarter"
        if 360 <= gap <= 366:
            return "year"
    if gap == 1:
        return "day"
    if gap == 7:
        return "week"
    return fallback


def build_long_view_sql(
    layout: WideLayout,
    *,
    source: str = "data",
    view: str = LONG_TABLE_NAME,
    value_type: str = "DOUBLE",
) -> str:
    """`CREATE VIEW` statement that unpivots the period columns into rows.

    UNPIVOT drops NULLs by default, so an entirely empty period column simply
    contributes no rows rather than a wall of nulls.
    """
    ids = ", ".join(quote_ident(name) for name in layout.id_columns)
    values = ", ".join(
        f"TRY_CAST({quote_ident(name)} AS {value_type}) AS {quote_ident(name)}"
        for name in layout.value_columns
    )
    in_list = ", ".join(quote_ident(name) for name in layout.value_columns)
    period = quote_ident(layout.period_name)
    value = quote_ident(layout.value_name)

    when_clauses = "\n        ".join(
        f"WHEN {quote_literal(name)} THEN DATE {quote_literal(label.isoformat())}"
        for name, label in layout.period_labels.items()
    )

    return f"""
CREATE VIEW {view} AS
SELECT
    {ids},
    CASE period_label
        {when_clauses}
    END AS {period},
    {value}
FROM (
    SELECT {ids}, {values}
    FROM {source}
) UNPIVOT ({value} FOR period_label IN ({in_list}))
""".strip()
