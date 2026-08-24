"""Value-level type detection for CSV columns.

The CSV is loaded with ``all_varchar=true`` so DuckDB never guesses a date
format for us. Everything below therefore works on raw text and produces the
SQL cast expression that the typed view is built from.

The date logic is deliberately conservative: a column is only temporal if its
values actually parse, and an ambiguous day/month order is resolved from the
data (or flagged) rather than assumed.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

PLACEHOLDER_TOKENS = frozenset(
    {
        "",
        "-",
        "--",
        "---",
        "–",
        "—",
        ".",
        "?",
        "n/a",
        "n.a.",
        "na",
        "nil",
        "none",
        "null",
        "nan",
        "unknown",
        "undefined",
        "#n/a",
    }
)

CURRENCY_SYMBOLS = "$€£¥₹₩₽"

_NUMERIC_BODY = re.compile(r"\d*\.?\d+(?:[eE][+-]?\d+)?")
_DAY_MONTH_HEAD = re.compile(r"^(\d{1,2})\D(\d{1,2})\D")

SAMPLE_LIMIT = 500
MIN_PARSE_RATE = 0.9


# --------------------------------------------------------------------------
# placeholders and numbers
# --------------------------------------------------------------------------


def is_placeholder(value: object) -> bool:
    """True for blanks and the various ways a CSV spells "no value"."""
    if value is None:
        return True
    text = str(value).strip()
    if not text:
        return True
    stripped = text.strip(CURRENCY_SYMBOLS + " \t").strip()
    return text.lower() in PLACEHOLDER_TOKENS or stripped.lower() in PLACEHOLDER_TOKENS


def parse_numeric_token(text: object) -> float | None:
    """Parse a display-formatted number: currency, thousands separators,
    accounting negatives and trailing percent signs.

    Returns ``None`` for anything that is not wholly a number. This strictness
    is the point: an identifier like ``ABIL148UR`` must not become ``148``.
    """
    if text is None:
        return None
    body = str(text).strip()
    if not body:
        return None

    negative = False
    if body.startswith("(") and body.endswith(")"):
        negative = True
        body = body[1:-1].strip()

    for symbol in CURRENCY_SYMBOLS:
        body = body.replace(symbol, "")
    body = body.replace(",", "").replace("_", "").replace(" ", "")

    if body.endswith("%"):
        body = body[:-1]
    if body.startswith("-"):
        negative = True
        body = body[1:]
    elif body.startswith("+"):
        body = body[1:]

    if not body or not _NUMERIC_BODY.fullmatch(body):
        return None
    try:
        value = float(body)
    except ValueError:
        return None
    return -value if negative else value


def numeric_parse_rate(values: list[object]) -> float:
    """Fraction of *meaningful* values that parse as numbers.

    Placeholders are excluded rather than counted as failures, which is why a
    mostly-``$-`` currency column is still recognised as numeric.
    """
    samples = [v for v in values if not is_placeholder(v)][:SAMPLE_LIMIT]
    if not samples:
        return 0.0
    parsed = sum(1 for v in samples if parse_numeric_token(v) is not None)
    return parsed / len(samples)


def has_currency_marker(values: list[object]) -> bool:
    return any(
        any(symbol in str(v) for symbol in CURRENCY_SYMBOLS)
        for v in values
        if v is not None
    )


def has_percent_marker(values: list[object]) -> bool:
    return any(str(v).strip().endswith("%") for v in values if v is not None)


def looks_like_boolean(values: list[object]) -> bool:
    truthy = {"true", "false", "yes", "no", "t", "f", "y", "n"}
    samples = [str(v).strip().lower() for v in values if not is_placeholder(v)]
    return bool(samples) and all(v in truthy for v in samples)


# --------------------------------------------------------------------------
# dates
# --------------------------------------------------------------------------

# Ordered by preference: unambiguous ISO shapes first, so they win ties.
_DATE_CANDIDATES: tuple[tuple[str, str], ...] = (
    ("%Y-%m-%d %H:%M:%S", "second"),
    ("%Y-%m-%dT%H:%M:%S", "second"),
    ("%Y/%m/%d %H:%M:%S", "second"),
    ("%m/%d/%Y %H:%M:%S", "second"),
    ("%d/%m/%Y %H:%M:%S", "second"),
    ("%Y-%m-%d", "day"),
    ("%Y/%m/%d", "day"),
    ("%Y%m%d", "day"),
    ("%m/%d/%Y", "day"),
    ("%d/%m/%Y", "day"),
    ("%m-%d-%Y", "day"),
    ("%d-%m-%Y", "day"),
    ("%d.%m.%Y", "day"),
    ("%m/%d/%y", "day"),
    ("%d/%m/%y", "day"),
    ("%b %d, %Y", "day"),
    ("%B %d, %Y", "day"),
    ("%d %b %Y", "day"),
    ("%d %B %Y", "day"),
    ("%Y-%m", "month"),
    ("%m/%Y", "month"),
    ("%b %Y", "month"),
    ("%B %Y", "month"),
)

# Formats that differ only in day/month order.
_ORDER_PAIRS = {
    "%m/%d/%Y": "%d/%m/%Y",
    "%d/%m/%Y": "%m/%d/%Y",
    "%m-%d-%Y": "%d-%m-%Y",
    "%d-%m-%Y": "%m-%d-%Y",
    "%m/%d/%y": "%d/%m/%y",
    "%d/%m/%y": "%m/%d/%y",
    "%m/%d/%Y %H:%M:%S": "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M:%S": "%m/%d/%Y %H:%M:%S",
}


@dataclass(frozen=True)
class DetectedDate:
    fmt: str
    grain: str
    parse_rate: float
    ambiguous: bool = False
    note: str = ""


@dataclass(frozen=True)
class _Candidate:
    fmt: str
    grain: str
    rate: float
    parsed: tuple[datetime, ...]


def _try_parse(text: str, fmt: str) -> datetime | None:
    try:
        return datetime.strptime(text, fmt)
    except (ValueError, TypeError):
        return None


def _is_month_first(fmt: str) -> bool:
    return fmt.index("%m") < fmt.index("%d")


def _order_evidence(samples: list[str]) -> str | None:
    """Decisive proof of day/month order: a component that cannot be a month."""
    for text in samples:
        match = _DAY_MONTH_HEAD.match(text)
        if not match:
            continue
        first, second = int(match.group(1)), int(match.group(2))
        if first > 12 and second <= 12:
            return "day_first"
        if second > 12 and first <= 12:
            return "month_first"
    return None


def _distinct_months(parsed: tuple[datetime, ...]) -> int:
    return len({(d.year, d.month) for d in parsed})


def _resolve_order(
    a: _Candidate, b: _Candidate, samples: list[str]
) -> tuple[_Candidate, bool, str]:
    month_first, day_first = (a, b) if _is_month_first(a.fmt) else (b, a)

    evidence = _order_evidence(samples)
    if evidence == "day_first":
        return day_first, False, "A day component above 12 proves day-first ordering."
    if evidence == "month_first":
        return month_first, False, "A month component above 12 proves month-first ordering."

    # No decisive value. Prefer the reading that spreads the data across the
    # calendar: `1/1/2014 … 12/1/2014` is twelve months month-first but a single
    # month day-first, and a real dataset is very unlikely to be the latter.
    month_spread = _distinct_months(month_first.parsed)
    day_spread = _distinct_months(day_first.parsed)
    if month_spread > day_spread:
        return (
            month_first,
            False,
            f"Read as month-first: it spans {month_spread} months versus "
            f"{day_spread} when read day-first.",
        )
    if day_spread > month_spread:
        return (
            day_first,
            False,
            f"Read as day-first: it spans {day_spread} months versus "
            f"{month_spread} when read month-first.",
        )
    return (
        month_first,
        True,
        "Day/month order is ambiguous in this column; assumed month-first "
        "(US convention). Verify before trusting period boundaries.",
    )


def detect_date_format(
    values: list[object], *, min_rate: float = MIN_PARSE_RATE
) -> DetectedDate | None:
    """Detect the strptime format of a text column, or ``None`` if not temporal.

    Bare years, month numbers and month names deliberately do not qualify -
    they are periods, not dates, and casting them to DATE throws.
    """
    samples = [str(v).strip() for v in values if not is_placeholder(v)][:SAMPLE_LIMIT]
    if not samples:
        return None

    scored: list[_Candidate] = []
    for fmt, grain in _DATE_CANDIDATES:
        parsed = tuple(p for p in (_try_parse(s, fmt) for s in samples) if p is not None)
        rate = len(parsed) / len(samples)
        if rate >= min_rate:
            scored.append(_Candidate(fmt, grain, rate, parsed))

    if not scored:
        return None

    best_rate = max(c.rate for c in scored)
    top = [c for c in scored if c.rate >= best_rate - 1e-9]
    chosen = top[0]

    rival_fmt = _ORDER_PAIRS.get(chosen.fmt)
    rival = next((c for c in top if c.fmt == rival_fmt), None)
    ambiguous, note = False, ""
    if rival is not None:
        chosen, ambiguous, note = _resolve_order(chosen, rival, samples)

    return DetectedDate(chosen.fmt, chosen.grain, chosen.rate, ambiguous, note)


@dataclass(frozen=True)
class DateLabel:
    value: date
    grain: str


_LABEL_FORMATS: tuple[tuple[str, str], ...] = (
    ("%Y-%m-%d", "day"),
    ("%Y/%m/%d", "day"),
    ("%m/%d/%Y", "day"),
    ("%Y-%m", "month"),
    ("%Y/%m", "month"),
    ("%b %Y", "month"),
    ("%B %Y", "month"),
    ("%b-%y", "month"),
    ("%Y", "year"),
)

_QUARTER_LABEL = re.compile(r"^Q([1-4])[ \-_]?(\d{4})$", re.IGNORECASE)


def looks_like_date_label(name: str) -> DateLabel | None:
    """Interpret a *column header* as a period, for wide-layout detection."""
    text = str(name).strip()
    if not text:
        return None

    if quarter := _QUARTER_LABEL.match(text):
        month = (int(quarter.group(1)) - 1) * 3 + 1
        return DateLabel(date(int(quarter.group(2)), month, 1), "quarter")

    for fmt, grain in _LABEL_FORMATS:
        parsed = _try_parse(text, fmt)
        if parsed is None:
            continue
        if grain == "year" and not 1900 <= parsed.year <= 2100:
            return None
        return DateLabel(parsed.date(), grain)
    return None


# --------------------------------------------------------------------------
# SQL cast expressions
# --------------------------------------------------------------------------


def quote_ident(name: str) -> str:
    cleaned = str(name).strip().strip('"')
    return '"' + cleaned.replace('"', '""') + '"'


def quote_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def numeric_cast_sql(quoted: str) -> str:
    """Parse display-formatted numbers in SQL, mirroring `parse_numeric_token`.

    Strips currency symbols and thousands separators, and understands
    accounting negatives such as ``($1,200)``.
    """
    trimmed = f"TRIM({quoted})"
    digits = f"regexp_replace({trimmed}, '[^0-9.eE+-]', '', 'g')"
    signed = (
        f"CASE WHEN {trimmed} LIKE '(%)' THEN '-' || {digits} ELSE {digits} END"
    )
    return f"TRY_CAST({signed} AS DOUBLE)"


def cast_expression(semantic_type: str, name: str, *, date_format: str | None = None) -> str:
    """The expression used to build the typed view from the raw text table."""
    quoted = quote_ident(name)

    if semantic_type in ("date", "datetime"):
        target = "TIMESTAMP" if semantic_type == "datetime" else "DATE"
        if date_format:
            return f"TRY_CAST(TRY_STRPTIME({quoted}, {quote_literal(date_format)}) AS {target})"
        return f"TRY_CAST({quoted} AS {target})"

    if semantic_type == "integer":
        return f"TRY_CAST({numeric_cast_sql(quoted)} AS BIGINT)"

    if semantic_type in ("decimal", "currency", "percentage"):
        return numeric_cast_sql(quoted)

    if semantic_type == "boolean":
        return f"TRY_CAST(LOWER(TRIM({quoted})) AS BOOLEAN)"

    # Text: trim padding and normalise empty strings to NULL. Casing is left
    # alone - it is data, and `quality.py` reports inconsistencies instead.
    return f"NULLIF(TRIM({quoted}), '')"


# --------------------------------------------------------------------------
# per-column verdict
# --------------------------------------------------------------------------

_YEAR_NAMES = {"year", "yr", "fiscal year", "fy", "calendar year"}
_MEASURE_TYPES = frozenset({"integer", "decimal", "currency", "percentage"})

# Integer columns that are period keys rather than things to sum:
# `(name pattern, allowed range, grain)`.
_PERIOD_HINTS: tuple[tuple[re.Pattern[str], tuple[int, int], str], ...] = (
    (re.compile(r"month", re.IGNORECASE), (1, 12), "month_of_year"),
    (re.compile(r"quarter|qtr", re.IGNORECASE), (1, 4), "quarter_of_year"),
    (re.compile(r"week", re.IGNORECASE), (1, 53), "week_of_year"),
    (re.compile(r"day", re.IGNORECASE), (1, 31), "day_of_month"),
)


@dataclass(frozen=True)
class ColumnPlan:
    """How one raw text column becomes a typed column in the `data` view."""

    name: str
    semantic_type: str
    cast_sql: str
    date_format: str | None = None
    temporal_grain: str | None = None
    parse_rate: float = 0.0
    ambiguous_date: bool = False
    is_empty: bool = False
    warnings: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def is_numeric(self) -> bool:
        return self.semantic_type in _MEASURE_TYPES

    @property
    def is_temporal(self) -> bool:
        return self.semantic_type in ("date", "datetime")


def period_grain_hint(name: str, values: list[object]) -> str | None:
    """Recognise integer period keys - `Year`, `Month Number`, `Quarter`.

    They look like ordinary numbers, so without this the agent happily sums
    `Year` into 1.4 million.
    """
    numbers = [parse_numeric_token(v) for v in values if not is_placeholder(v)]
    real = [n for n in numbers if n is not None]
    if not real or any(n != int(n) for n in real):
        return None

    label = str(name).strip().lower()
    if (label in _YEAR_NAMES or label.endswith(" year")) and all(
        1900 <= n <= 2100 for n in real
    ):
        return "year"

    for pattern, (low, high), grain in _PERIOD_HINTS:
        if pattern.search(label) and all(low <= n <= high for n in real):
            return grain
    return None


def plan_column(name: str, values: list[object]) -> ColumnPlan:
    """Classify a raw text column and produce its cast expression.

    Order matters: dates are checked before numbers so `2025-01-01` is not
    mistaken for arithmetic, and numbers are only accepted when practically
    every non-placeholder value parses.
    """
    meaningful = [v for v in values if not is_placeholder(v)]
    warnings: list[str] = []

    if not meaningful:
        return ColumnPlan(
            name=name,
            semantic_type="categorical",
            cast_sql=cast_expression("categorical", name),
            is_empty=True,
        )

    if looks_like_boolean(meaningful):
        return ColumnPlan(
            name=name,
            semantic_type="boolean",
            cast_sql=cast_expression("boolean", name),
            parse_rate=1.0,
        )

    if detected := detect_date_format(meaningful):
        semantic = "datetime" if detected.grain == "second" else "date"
        notes: list[str] = []
        # An unresolved day/month order is a real risk; a resolved one is just
        # worth recording so the choice is auditable.
        (warnings if detected.ambiguous else notes).append(detected.note)
        return ColumnPlan(
            name=name,
            semantic_type=semantic,
            cast_sql=cast_expression(semantic, name, date_format=detected.fmt),
            date_format=detected.fmt,
            temporal_grain=detected.grain,
            parse_rate=detected.parse_rate,
            ambiguous_date=detected.ambiguous,
            warnings=tuple(w for w in warnings if w),
            notes=tuple(n for n in notes if n),
        )

    rate = numeric_parse_rate(meaningful)
    if rate >= MIN_PARSE_RATE:
        if has_percent_marker(meaningful):
            semantic = "percentage"
        elif has_currency_marker(meaningful):
            semantic = "currency"
        else:
            parsed = [parse_numeric_token(v) for v in meaningful]
            whole = all(n is not None and n == int(n) for n in parsed)
            semantic = "integer" if whole and not any("." in str(v) for v in meaningful) else "decimal"

        grain = period_grain_hint(name, meaningful)
        if rate < 1.0:
            warnings.append(
                f"{(1 - rate) * 100:.0f}% of values could not be parsed as numbers "
                "and become NULL."
            )
        return ColumnPlan(
            name=name,
            semantic_type=semantic,
            cast_sql=cast_expression(semantic, name),
            temporal_grain=grain,
            parse_rate=rate,
            warnings=tuple(warnings),
        )

    return ColumnPlan(
        name=name,
        semantic_type="categorical",
        cast_sql=cast_expression("categorical", name),
        parse_rate=rate,
        warnings=tuple(warnings),
    )
