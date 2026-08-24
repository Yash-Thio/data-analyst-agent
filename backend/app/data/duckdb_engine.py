"""DuckDB access with an explicitly typed view over the raw CSV.

The CSV is loaded twice over:

1. `data_raw` - every column as VARCHAR, so DuckDB never guesses. This matters:
   auto-detection used to read `1/1/2014` as D/M/YYYY and silently collapse a
   whole year of data into January.
2. `data` - a view that casts each column using a format verified against the
   actual values (see `app.data.typing`).

Because `data` is already typed, generated SQL can use `SUM("Sales")` directly
instead of re-deriving currency parsing on every query.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from app.data.reshape import LONG_TABLE_NAME, WideLayout, build_long_view_sql, detect_wide_layout
from app.data.typing import ColumnPlan, plan_column, quote_ident

TABLE_NAME = "data"
RAW_TABLE_NAME = "data_raw"
MAX_ROWS = 500
SQL_TIMEOUT_SECONDS = 30
TYPE_SAMPLE_ROWS = 2000

_READ_OPTIONS = "all_varchar=true, header=true, null_padding=true, parallel=false"

_SELECT_ONLY = re.compile(r"^\s*(WITH\b[\s\S]+?\bSELECT\b|SELECT\b)", re.IGNORECASE)
_FORBIDDEN = re.compile(
    r"(?<![\w\"])(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|REPLACE\s+INTO|"
    r"COPY|ATTACH|DETACH|PRAGMA|LOAD|INSTALL|EXPORT|IMPORT|SET|CALL)(?![\w\"])",
    re.IGNORECASE,
)
_FORBIDDEN_FUNCTIONS = re.compile(
    r"(?<![\w\"])(read_csv|read_csv_auto|read_parquet|read_json|read_json_auto|"
    r"glob|parquet_scan|json_scan|sniff_csv|getenv|shell)\s*\(",
    re.IGNORECASE,
)


class SqlValidationError(ValueError):
    """Static validation rejected the query before it ever reached DuckDB."""


@dataclass
class QueryResult:
    sql: str
    rows: list[dict[str, Any]]
    columns: list[str]
    truncated: bool = False

    @property
    def row_count(self) -> int:
        return len(self.rows)


@dataclass
class DatasetSchema:
    """Everything the planner and the SQL guard need to know about the tables."""

    columns: list[ColumnPlan] = field(default_factory=list)
    wide_layout: WideLayout | None = None
    long_columns: list[str] = field(default_factory=list)

    @property
    def column_names(self) -> list[str]:
        return [c.name for c in self.columns]

    @property
    def table_names(self) -> set[str]:
        names = {TABLE_NAME, RAW_TABLE_NAME}
        if self.wide_layout is not None:
            names.add(LONG_TABLE_NAME)
        return names

    def all_column_names(self) -> set[str]:
        return set(self.column_names) | set(self.long_columns)


class DuckDBEngine:
    def __init__(self, csv_path: Path, *, timeout_seconds: int = SQL_TIMEOUT_SECONDS) -> None:
        self.csv_path = Path(csv_path)
        self.timeout_seconds = timeout_seconds
        self._conn: duckdb.DuckDBPyConnection | None = None
        self._schema: DatasetSchema | None = None

    # -- lifecycle ---------------------------------------------------------

    def connect(self) -> duckdb.DuckDBPyConnection:
        if self._conn is None:
            conn = duckdb.connect(database=":memory:", read_only=False)
            conn.execute(
                f"CREATE TABLE {RAW_TABLE_NAME} AS "
                f"SELECT * FROM read_csv(?, {_READ_OPTIONS})",
                [str(self.csv_path)],
            )
            self._conn = conn
            self._schema = self._build_schema(conn)
        return self._conn

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
            self._schema = None

    def __enter__(self) -> "DuckDBEngine":
        self.connect()
        return self

    def __exit__(self, *args: object) -> None:
        self.close()

    @property
    def schema(self) -> DatasetSchema:
        self.connect()
        assert self._schema is not None
        return self._schema

    # -- schema construction ----------------------------------------------

    def _build_schema(self, conn: duckdb.DuckDBPyConnection) -> DatasetSchema:
        raw_names = [row[0] for row in conn.execute(f"DESCRIBE {RAW_TABLE_NAME}").fetchall()]
        sample = conn.execute(
            f"SELECT * FROM {RAW_TABLE_NAME} LIMIT {TYPE_SAMPLE_ROWS}"
        ).fetchdf()

        plans = [
            plan_column(name, sample[name].tolist() if name in sample else [])
            for name in raw_names
        ]

        projection = ",\n    ".join(
            f"{plan.cast_sql} AS {quote_ident(plan.name)}" for plan in plans
        )
        conn.execute(f"CREATE VIEW {TABLE_NAME} AS SELECT\n    {projection}\nFROM {RAW_TABLE_NAME}")

        schema = DatasetSchema(columns=plans)

        layout = detect_wide_layout(raw_names)
        if layout is not None:
            by_name = {p.name: p for p in plans}
            # An entirely empty period column carries no type information and
            # must not force the whole long view to VARCHAR.
            numeric = all(
                by_name[name].is_numeric or by_name[name].is_empty
                for name in layout.value_columns
                if name in by_name
            )
            try:
                conn.execute(
                    build_long_view_sql(
                        layout, value_type="DOUBLE" if numeric else "VARCHAR"
                    )
                )
            except duckdb.Error:
                # A malformed wide table should not sink the whole dataset;
                # `data` is still perfectly usable.
                layout = None
            else:
                schema.wide_layout = layout
                schema.long_columns = [
                    row[0] for row in conn.execute(f"DESCRIBE {LONG_TABLE_NAME}").fetchall()
                ]

        return schema

    # -- validation --------------------------------------------------------

    @staticmethod
    def validate_sql(sql: str) -> None:
        normalized = sql.strip().rstrip(";")
        if not normalized:
            raise SqlValidationError("Query is empty")
        if ";" in normalized:
            raise SqlValidationError("Multi-statement SQL is not allowed")
        if not _SELECT_ONLY.match(normalized):
            raise SqlValidationError("Only SELECT queries are allowed")
        stripped = _strip_string_literals(normalized)
        if match := _FORBIDDEN.search(stripped):
            raise SqlValidationError(f"Query contains forbidden keyword: {match.group(1)}")
        if match := _FORBIDDEN_FUNCTIONS.search(stripped):
            raise SqlValidationError(f"Query contains forbidden function: {match.group(1)}")

    # -- execution ---------------------------------------------------------

    def explain(self, sql: str) -> None:
        """Bind and plan without executing, to surface errors cheaply."""
        self.validate_sql(sql)
        conn = self.connect()
        conn.execute(f"EXPLAIN {sql.rstrip(';')}").fetchall()

    def execute(self, sql: str, limit: int = MAX_ROWS) -> QueryResult:
        self.validate_sql(sql)
        conn = self.connect()
        # Fetch one extra row so truncation is detectable rather than silent.
        wrapped = f"SELECT * FROM ({sql.rstrip(';')}) AS _q LIMIT {int(limit) + 1}"

        timer = threading.Timer(self.timeout_seconds, conn.interrupt)
        timer.start()
        try:
            df = conn.execute(wrapped).fetchdf()
        except duckdb.InterruptException as exc:
            raise TimeoutError(
                f"Query exceeded the {self.timeout_seconds}s limit"
            ) from exc
        except Exception as exc:
            raise RuntimeError(f"{exc}\nExecuted SQL:\n{wrapped}") from exc
        finally:
            timer.cancel()

        truncated = len(df) > limit
        if truncated:
            df = df.head(limit)

        return QueryResult(
            sql=wrapped,
            rows=_records(df),
            columns=[str(c) for c in df.columns],
            truncated=truncated,
        )

    def run_sql(self, sql: str, limit: int = MAX_ROWS) -> tuple[list[dict[str, Any]], str]:
        result = self.execute(sql, limit)
        return result.rows, result.sql

    # -- introspection -----------------------------------------------------

    def get_row_count(self) -> int:
        conn = self.connect()
        return int(conn.execute(f"SELECT COUNT(*) FROM {TABLE_NAME}").fetchone()[0])

    def get_columns(self, table: str = TABLE_NAME) -> list[tuple[str, str]]:
        conn = self.connect()
        return [(r[0], r[1]) for r in conn.execute(f"DESCRIBE {table}").fetchall()]

    def raw_values(self, column: str, limit: int = TYPE_SAMPLE_ROWS) -> list[Any]:
        conn = self.connect()
        rows = conn.execute(
            f"SELECT {quote_ident(column)} FROM {RAW_TABLE_NAME} LIMIT {int(limit)}"
        ).fetchall()
        return [r[0] for r in rows]


def _records(df: pd.DataFrame) -> list[dict[str, Any]]:
    rows = df.to_dict(orient="records")
    for row in rows:
        for key, value in row.items():
            row[key] = _scalar(value)
    return rows


def _scalar(value: Any) -> Any:
    """Convert to something JSON-serialisable and stable for the UI.

    Dates become ISO strings rather than timestamps so chart axes and evidence
    tables read as `2025-01-01`, not `2025-01-01 00:00:00`.
    """
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return value
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat() if value.time() == time.min else value.isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat() if value.time() == time.min else value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if hasattr(value, "item"):
        return value.item()
    return value


def _strip_string_literals(sql: str) -> str:
    """Blank out quoted text so keyword checks cannot fire on data values."""
    return re.sub(r"'(?:[^']|'')*'", "''", sql)
