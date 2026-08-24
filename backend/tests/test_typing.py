"""Value-level type detection.

These lock in the parsing bugs that used to produce confidently wrong answers.
"""

from __future__ import annotations

import pytest

from app.data.typing import (
    detect_date_format,
    is_placeholder,
    looks_like_date_label,
    numeric_parse_rate,
    parse_numeric_token,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" $1,618.50 ", 1618.50),
        ("$32,370.00", 32370.0),
        ("($1,200)", -1200.0),
        ("-5000", -5000.0),
        ("3.3", 3.3),
        ("3", 3.0),
        ("12.5%", 12.5),
        ("1e3", 1000.0),
        ("  ", None),
        (" $-   ", None),
        ("N/A", None),
    ],
)
def test_parse_numeric_token(raw: str, expected: float | None) -> None:
    assert parse_numeric_token(raw) == expected


def test_alphanumeric_ids_are_not_numeric() -> None:
    """`ABIL148UR` used to be stripped down to `148` and called a number."""
    for series_id in ("ABIL148UR", "AKRO439UR", "ALBA513UR"):
        assert parse_numeric_token(series_id) is None
    assert numeric_parse_rate(["ABIL148UR", "AKRO439UR", "ALBA513UR"]) == 0.0


def test_placeholders_are_recognised() -> None:
    for token in ("", "   ", "-", "N/A", "null", "None", "$-", " $-   "):
        assert is_placeholder(token), token
    for token in ("0", "3.3", "Germany"):
        assert not is_placeholder(token)


def test_currency_column_with_placeholders_still_reads_as_numeric() -> None:
    """`Discounts` is mostly ` $-   ` placeholders but is a real currency column."""
    values = [" $-   ", " $-   ", " $-   ", "$1,200.00", "", " $-   ", "$350.00"]
    assert numeric_parse_rate(values) == 1.0


def test_detect_iso_dates() -> None:
    detected = detect_date_format(["2024-04-01", "2024-05-01", "2024-07-15"])
    assert detected is not None
    assert detected.fmt == "%Y-%m-%d"
    assert detected.ambiguous is False


def test_month_first_wins_when_day_first_collapses_the_range() -> None:
    """The financial sample: every row is `M/1/YYYY`.

    Both %m/%d/%Y and %d/%m/%Y parse cleanly, but reading it day-first puts
    every row in January. The spread tie-breaker must pick month-first.
    """
    values = [f"{month}/1/2014" for month in range(1, 13)]
    detected = detect_date_format(values)
    assert detected is not None
    assert detected.fmt == "%m/%d/%Y"


def test_day_first_wins_with_decisive_evidence() -> None:
    values = ["13/01/2024", "25/02/2024", "01/03/2024", "30/04/2024"]
    detected = detect_date_format(values)
    assert detected is not None
    assert detected.fmt == "%d/%m/%Y"
    assert detected.ambiguous is False


def test_genuinely_ambiguous_dates_are_flagged() -> None:
    values = ["01/02/2024", "03/04/2024", "05/06/2024"]
    detected = detect_date_format(values)
    assert detected is not None
    assert detected.ambiguous is True
    assert detected.note


@pytest.mark.parametrize(
    "values",
    [
        ["January", "February", "March"],
        ["2014", "2013", "2014"],
        ["1", "2", "3", "12"],
        ["Government", "Midmarket", "Enterprise"],
    ],
)
def test_non_dates_are_not_detected_as_dates(values: list[str]) -> None:
    """`Month Name`, `Year` and `Month Number` used to be temporal by name alone."""
    assert detect_date_format(values) is None


def test_looks_like_date_label_identifies_wide_headers() -> None:
    assert looks_like_date_label("2025-01-01") is not None
    assert looks_like_date_label("2025-06") is not None
    assert looks_like_date_label("Region Code") is None
    assert looks_like_date_label("Series ID") is None
