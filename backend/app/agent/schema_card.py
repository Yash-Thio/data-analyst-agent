"""The compact dataset description the planner writes SQL against.

Grounding beats prompting. Most bad SQL comes from the model not knowing the
exact column name, what a column means, or which values it holds - so the card
spells out every name verbatim, marks identifiers as un-aggregatable, gives
real date ranges, and lists category values the model would otherwise invent.
"""

from __future__ import annotations

from typing import Any

MAX_LISTED_VALUES = 12
MAX_VALUE_LENGTH = 40

_QUOTE = '"'

_TYPE_LABELS = {
    "currency": "number (currency)",
    "percentage": "number (percent)",
    "decimal": "number",
    "integer": "whole number",
    "date": "date",
    "datetime": "timestamp",
    "boolean": "boolean",
    "categorical": "text",
    "identifier": "identifier",
}


def build_schema_card(profile: dict[str, Any]) -> str:
    sections = [_header(profile), _columns_section(profile)]

    if long_section := _long_view_section(profile):
        sections.append(long_section)
    if quality_section := _quality_section(profile):
        sections.append(quality_section)

    sections.append(_rules_section(profile))
    return "\n\n".join(s for s in sections if s)


def _header(profile: dict[str, Any]) -> str:
    return (
        f"## Table `{profile.get('table_name', 'data')}` "
        f"({profile.get('row_count', 0):,} rows, {profile.get('column_count', 0)} columns)\n"
        "Every column below is ALREADY the right type. Currency symbols, thousands "
        "separators and date formats were parsed at load time, so use "
        '`SUM("Sales")` and `"Date" >= DATE \'2014-01-01\'` directly. '
        "Do not add CAST, TRY_CAST, REPLACE or STRPTIME."
    )


def _columns_section(profile: dict[str, Any]) -> str:
    lines = ["| column | type | role | detail |", "| --- | --- | --- | --- |"]
    for col in profile.get("columns", []):
        lines.append(
            "| {name} | {type} | {role} | {detail} |".format(
                name=f'`"{col["name"]}"`',
                type=_TYPE_LABELS.get(col.get("semantic_type", ""), col.get("semantic_type", "")),
                role=_role_label(col),
                detail=_detail(col),
            )
        )
    return "\n".join(lines)


def _role_label(col: dict[str, Any]) -> str:
    role = col.get("role", "")
    if role == "identifier":
        return "identifier - never aggregate"
    if role == "measure":
        return "measure"
    if role == "temporal":
        grain = col.get("temporal_grain")
        return f"temporal ({grain})" if grain else "temporal"
    return "dimension"


def _detail(col: dict[str, Any]) -> str:
    parts: list[str] = []
    temporal = col.get("role") == "temporal"

    if (span := col.get("date_range")) and span.get("min") and span.get("max"):
        parts.append(f"{span['min']} to {span['max']}")
    elif stats := col.get("stats"):
        lo, hi = stats.get("min"), stats.get("max")
        if lo is not None and hi is not None:
            parts.append(f"range {_number(lo, temporal)} to {_number(hi, temporal)}")
    elif top := col.get("top_values"):
        values = list(top)[:MAX_LISTED_VALUES]
        rendered = ", ".join(_truncate(v) for v in values)
        suffix = ", ..." if col.get("unique_count", 0) > len(values) else ""
        parts.append(f"values: {rendered}{suffix}")
    elif samples := col.get("sample_values"):
        parts.append("e.g. " + ", ".join(_truncate(str(v)) for v in samples[:3]))

    if (unique := col.get("unique_count")) and col.get("role") in ("dimension", "identifier"):
        parts.append(f"{unique} distinct")
    if (null_pct := col.get("null_pct", 0)) >= 1:
        parts.append(f"{null_pct:.0f}% null")

    return "; ".join(parts) or "-"


def _long_view_section(profile: dict[str, Any]) -> str:
    wide = profile.get("wide")
    if not wide:
        return ""
    period = wide["value_columns"]
    long_name = profile["long_table_name"]
    keys = ", ".join(_code_ident(c) for c in wide["id_columns"])
    period_col = _code_ident(wide["period_name"])
    value_col = _code_ident(wide["value_name"])
    return (
        f"## Also available: `{long_name}` (unpivoted)\n"
        f"`data` stores each period as its own column "
        f"({period[0]} ... {period[-1]}, {len(period)} in total), which makes "
        "trends and period comparisons awkward.\n"
        f"`{long_name}` is the same data one row per period, with the key columns "
        f"{keys} plus:\n"
        f"- {period_col} - a real DATE ({wide['period_grain']} grain)\n"
        f"- {value_col} - the numeric value\n"
        "Prefer it for anything involving time, ranking across periods, or averages."
    )


def _quality_section(profile: dict[str, Any]) -> str:
    quality = profile.get("quality") or {}
    warnings = [w for w in quality.get("warnings", []) if w.get("severity") != "info"]
    normalized = quality.get("normalized_expressions") or {}
    if not warnings and not normalized:
        return ""

    lines = ["## Data quality"]
    for expr in normalized:
        lines.append(
            f'- `"{expr}"` has values differing only by case; GROUP BY '
            f"`{normalized[expr]}` instead of the raw column."
        )
    for warning in warnings:
        # The casing warnings are already covered by the normalisation lines.
        if warning.get("column") in normalized and warning.get("code") == "inconsistent_casing":
            continue
        lines.append(f"- {warning['message']}")
    return "\n".join(lines)


def _rules_section(profile: dict[str, Any]) -> str:
    tables = f"`{profile.get('table_name', 'data')}`"
    if profile.get("long_table_name"):
        tables += f" or `{profile['long_table_name']}`"

    identifiers = profile.get("identifiers") or []
    rules = [
        "## SQL rules",
        f"- Query {tables} only. One statement, SELECT or WITH ... SELECT.",
        '- Quote every column name exactly as written above: `"Gross Sales"`.',
        "- Quote aliases that are not plain words: `AS \"Q3 2024\"`, `AS \"2014\"`.",
        "- The columns are already typed; casting them again is an error.",
        "- Aggregate only columns marked `measure`.",
    ]
    if identifiers:
        rules.append(
            "- Never SUM or AVG " + ", ".join(f'`"{c}"`' for c in identifiers) + "."
        )
    rules.append("- Return few enough rows to read: aggregate, and ORDER BY + LIMIT rankings.")
    rules.append("- Give every computed column a meaningful alias.")
    return "\n".join(rules)


def _code_ident(name: str) -> str:
    """Render a column name as a quoted identifier inside backticks."""
    return f"`{_QUOTE}{name}{_QUOTE}`"


def _truncate(value: str) -> str:
    # Values can contain newlines and pipes, both of which break the table.
    text = " ".join(str(value).split()).replace("|", "/")
    return text if len(text) <= MAX_VALUE_LENGTH else text[: MAX_VALUE_LENGTH - 1] + "…"


def _number(value: float, plain: bool = False) -> str:
    """Years and month numbers must not be rendered as `2,014`."""
    if plain:
        return f"{value:g}"
    if abs(value) >= 1000:
        return f"{value:,.0f}"
    return f"{value:g}"
