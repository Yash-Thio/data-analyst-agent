"""Gates every generated query passes before it is allowed to run.

Three layers, cheapest first:

1. static validation - read-only, single statement, no file or system access
2. identifier check  - hallucinated columns caught with a "did you mean" hint
3. EXPLAIN dry run   - DuckDB binds and plans the query without executing it

The suggestions matter as much as the rejections: they are what the repair
loop feeds back to the model, and a named alternative fixes a query far more
reliably than a bare error string.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field

import duckdb

from app.data.duckdb_engine import (
    RAW_TABLE_NAME,
    TABLE_NAME,
    DuckDBEngine,
    SqlValidationError,
)
from app.data.reshape import LONG_TABLE_NAME

MAX_SUGGESTIONS = 3
SIMILARITY_CUTOFF = 0.6

_QUOTED_IDENT = re.compile(r'"((?:[^"]|"")*)"')
_FROM_JOIN = re.compile(
    r'\b(?:FROM|JOIN)\s+("(?:[^"]|"")*"|[A-Za-z_][\w$]*)', re.IGNORECASE
)
_CTE_NAME = re.compile(
    r'(?:\bWITH\b|,)\s*(?:RECURSIVE\s+)?("(?:[^"]|"")*"|[A-Za-z_][\w$]*)\s+AS\s*\(',
    re.IGNORECASE,
)


@dataclass(eq=False)
class GuardError(Exception):
    """A rejection carrying enough context for the model to fix itself."""

    message: str
    stage: str
    suggestions: list[str] = field(default_factory=list)

    def __str__(self) -> str:
        if not self.suggestions:
            return self.message
        return f"{self.message} Did you mean: {', '.join(self.suggestions)}?"


def allowed_tables(engine: DuckDBEngine) -> set[str]:
    tables = {TABLE_NAME, RAW_TABLE_NAME}
    if engine.schema.wide_layout is not None:
        tables.add(LONG_TABLE_NAME)
    return tables


def known_columns(engine: DuckDBEngine) -> set[str]:
    return engine.schema.all_column_names()


def extract_quoted_identifiers(sql: str) -> list[str]:
    """Quoted names outside string literals.

    Only quoted names are checked: an unquoted token could be an alias, a
    function or a keyword, and guessing there produces false rejections.
    """
    return [m.group(1).replace('""', '"') for m in _QUOTED_IDENT.finditer(_mask_literals(sql))]


def referenced_tables(sql: str) -> set[str]:
    masked = _mask_literals(sql)
    return {_unquote(m.group(1)) for m in _FROM_JOIN.finditer(masked)}


def cte_names(sql: str) -> set[str]:
    masked = _mask_literals(sql)
    return {_unquote(m.group(1)) for m in _CTE_NAME.finditer(masked)}


def check_tables(sql: str, engine: DuckDBEngine) -> None:
    permitted = allowed_tables(engine) | cte_names(sql)
    unknown = {t for t in referenced_tables(sql) if t.lower() not in {p.lower() for p in permitted}}
    if unknown:
        raise GuardError(
            message=f"Unknown table(s): {', '.join(sorted(unknown))}.",
            stage="tables",
            suggestions=sorted(allowed_tables(engine)),
        )


def check_identifiers(sql: str, engine: DuckDBEngine) -> None:
    """Catch hallucinated column names and propose the closest real one."""
    columns = known_columns(engine)
    lowered = {c.lower(): c for c in columns}
    # Aliases the query defines itself are legitimate references later on.
    aliases = _self_defined_aliases(sql)

    for ident in extract_quoted_identifiers(sql):
        key = ident.strip().lower()
        if not key or key in lowered or key in aliases or key in {t.lower() for t in allowed_tables(engine)}:
            continue
        # A quoted literal-looking alias such as "Q3 2024" is fine.
        matches = difflib.get_close_matches(
            ident, sorted(columns), n=MAX_SUGGESTIONS, cutoff=SIMILARITY_CUTOFF
        )
        if matches:
            raise GuardError(
                message=f'Column "{ident}" does not exist.',
                stage="identifiers",
                suggestions=matches,
            )


def dry_run(sql: str, engine: DuckDBEngine) -> None:
    try:
        engine.explain(sql)
    except SqlValidationError:
        raise
    except duckdb.Error as exc:
        raise GuardError(
            message=str(exc).strip(),
            stage="explain",
            suggestions=_suggest_from_error(str(exc), engine),
        ) from exc


def guard(sql: str, engine: DuckDBEngine) -> str:
    """Run every gate. Returns the query, or raises `GuardError`."""
    cleaned = sql.strip().rstrip(";").strip()
    try:
        DuckDBEngine.validate_sql(cleaned)
    except SqlValidationError as exc:
        raise GuardError(message=str(exc), stage="static") from exc

    check_tables(cleaned, engine)
    check_identifiers(cleaned, engine)
    dry_run(cleaned, engine)
    return cleaned


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------


def _mask_literals(sql: str) -> str:
    """Blank string literals so their contents are never read as identifiers."""
    return re.sub(r"'(?:[^']|'')*'", "''", sql)


def _unquote(token: str) -> str:
    token = token.strip()
    if token.startswith('"') and token.endswith('"'):
        return token[1:-1].replace('""', '"')
    return token


def _self_defined_aliases(sql: str) -> set[str]:
    """Names introduced by `AS "x"`, which are valid references downstream."""
    masked = _mask_literals(sql)
    return {
        m.group(1).replace('""', '"').lower()
        for m in re.finditer(r'\bAS\s+"((?:[^"]|"")*)"', masked, re.IGNORECASE)
    }


def _suggest_from_error(message: str, engine: DuckDBEngine) -> list[str]:
    """Pull the offending name out of a DuckDB binder error and match it."""
    match = re.search(r'column "?([\w \-.]+)"? not found', message, re.IGNORECASE)
    if not match:
        match = re.search(r'Referenced column "([^"]+)"', message)
    if not match:
        return []
    return difflib.get_close_matches(
        match.group(1), sorted(known_columns(engine)), n=MAX_SUGGESTIONS, cutoff=0.4
    )
