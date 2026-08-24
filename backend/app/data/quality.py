"""Data-quality checks that become report caveats and planner hints.

The point is not to clean the data behind the user's back. It is to make the
agent aware of traps - `CANADA` and `germany` in the same column, a period
column that is entirely blank, dates whose day/month order had to be guessed -
so the SQL it writes accounts for them and the final report says so.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING

from app.data.typing import ColumnPlan, quote_ident

if TYPE_CHECKING:  # pragma: no cover
    from app.data.duckdb_engine import DuckDBEngine

HIGH_NULL_PCT = 40.0
MAX_CASING_EXAMPLES = 4


@dataclass
class QualityWarning:
    code: str
    column: str
    message: str
    severity: str = "warning"

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class QualityReport:
    warnings: list[QualityWarning] = field(default_factory=list)
    normalized_expressions: dict[str, str] = field(default_factory=dict)
    duplicate_rows: int = 0

    def as_dict(self) -> dict:
        return {
            "warnings": [w.as_dict() for w in self.warnings],
            "normalized_expressions": dict(self.normalized_expressions),
            "duplicate_rows": self.duplicate_rows,
        }

    def caveats(self) -> list[str]:
        """Human-readable lines for the report's limitations section."""
        lines = [w.message for w in self.warnings if w.severity in ("warning", "error")]
        if self.duplicate_rows:
            lines.append(
                f"{self.duplicate_rows} fully duplicated rows are present and are "
                "counted more than once by aggregates."
            )
        return lines


def assess_quality(
    engine: "DuckDBEngine",
    plans: list[ColumnPlan],
    stats: dict[str, dict],
) -> QualityReport:
    report = QualityReport()
    row_count = int(stats.get("__row_count__", {}).get("value", 0))

    for plan in plans:
        col_stats = stats.get(plan.name, {})
        _check_column(report, plan, col_stats, row_count)

    report.duplicate_rows = _count_duplicate_rows(engine, row_count)
    return report


def _check_column(
    report: QualityReport, plan: ColumnPlan, stats: dict, row_count: int
) -> None:
    name = plan.name
    null_pct = float(stats.get("null_pct") or 0.0)
    unique_count = int(stats.get("unique_count") or 0)

    if plan.ambiguous_date:
        report.warnings.append(
            QualityWarning(
                code="ambiguous_date_order",
                column=name,
                message=(
                    f'Day/month order in "{name}" could not be proven from the data; '
                    "period boundaries may be off."
                ),
                severity="error",
            )
        )

    for text in plan.warnings:
        # `plan_column` already phrased these; keep them attached to the column.
        report.warnings.append(
            QualityWarning(code="parse_loss", column=name, message=f'"{name}": {text}')
        )

    for text in plan.notes:
        report.warnings.append(
            QualityWarning(
                code="type_inference",
                column=name,
                message=f'"{name}": {text}',
                severity="info",
            )
        )

    if null_pct >= 100.0:
        report.warnings.append(
            QualityWarning(
                code="empty_column",
                column=name,
                message=f'"{name}" is empty for every row and cannot be analysed.',
            )
        )
    elif null_pct >= HIGH_NULL_PCT:
        report.warnings.append(
            QualityWarning(
                code="high_null_rate",
                column=name,
                message=f'"{name}" is missing for {null_pct:.0f}% of rows.',
            )
        )

    if row_count > 1 and unique_count == 1 and null_pct < 100.0:
        report.warnings.append(
            QualityWarning(
                code="constant_column",
                column=name,
                message=f'"{name}" holds a single value for every row.',
                severity="info",
            )
        )

    normalized_unique = stats.get("normalized_unique_count")
    if normalized_unique is not None and 0 < int(normalized_unique) < unique_count:
        collapsed = unique_count - int(normalized_unique)
        examples = stats.get("casing_examples") or []
        sample = ", ".join(repr(e) for e in examples[:MAX_CASING_EXAMPLES])
        report.warnings.append(
            QualityWarning(
                code="inconsistent_casing",
                column=name,
                message=(
                    f'"{name}" has {collapsed} value(s) that differ only by casing or '
                    f"padding ({sample}). Group on UPPER(TRIM(...)) to avoid splitting them."
                ),
            )
        )
        report.normalized_expressions[name] = f"UPPER(TRIM({quote_ident(name)}))"


def _count_duplicate_rows(engine: "DuckDBEngine", row_count: int) -> int:
    if row_count <= 1:
        return 0
    try:
        rows, _ = engine.run_sql(
            "SELECT COUNT(*) AS n FROM (SELECT DISTINCT * FROM data)", limit=1
        )
    except Exception:
        return 0
    distinct = int(rows[0]["n"]) if rows else row_count
    return max(0, row_count - distinct)
