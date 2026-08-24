---
name: duckdb-sql-analyst
description: >-
  Rules for the data-analyst agent's generated DuckDB SQL: the typed view, the
  raw text table, identifier quoting, column roles and the wide-format long
  view. Use when editing the profiler, schema card, planner prompts, SQL guard
  or repair loop, or when diagnosing DuckDB binder or parser errors.
---

# DuckDB SQL for the data-analyst agent

There are no SQL templates. The planner writes each query itself, guided by the
schema card and constrained by the guard.

The runtime copy of the model-facing rules lives in
`backend/app/agent/skills/duckdb_sql.md`. Keep it and this skill in sync.

## The two tables

| Table | What it is |
| --- | --- |
| `data_raw` | Every column as `VARCHAR`, exactly as the file spells it. Never queried by generated SQL. |
| `data` | A view over `data_raw` that casts each column using an expression the profiler verified. This is what queries hit. |
| `data_long` | Only for wide files: `data` unpivoted to `(…keys, period DATE, value)`. |

`data` is already typed. Generated SQL must not re-cast:

```sql
-- correct
SELECT SUM("Sales") FROM data WHERE "Date" >= DATE '2014-01-01'

-- wrong: the view already did this
SELECT SUM(TRY_CAST(REPLACE("Sales", '$', '') AS DOUBLE)) FROM data
```

If a cast looks necessary, the profiler misclassified the column — fix
`app/data/typing.py`, not the query.

## Column roles

`app/data/profiler.py` assigns every column a role, and the schema card passes
it to the model:

- **measure** — safe to `SUM` / `AVG`
- **dimension** — safe to `GROUP BY`
- **temporal** — a date, or an integer period key like `Year`; group, never sum
- **identifier** — a label such as `Series ID` or `Region Code`; never aggregate

## Hard rules

- Quote every column exactly as the schema card spells it: `"Gross Sales"`, `"2025-01-01"`.
- Quote aliases that are not plain words: `AS "Q3 2024"`. `AS 2014` is a syntax error.
- One statement, `SELECT` or `WITH … SELECT`. No DDL, DML, `PRAGMA`, `ATTACH`
  or file functions (`read_csv`, `read_parquet`, `glob`).
- Only `data`, `data_long` and CTEs defined in the query may appear after
  `FROM` / `JOIN`.
- When the schema card flags inconsistent casing, group on the normalised
  expression (`UPPER(TRIM("Country"))`), not the raw column.

## Diagnosing errors

Work outwards from the stage the guard reported (`GuardError.stage`):

1. `static` — read-only or single-statement rule broken.
2. `tables` — a table that does not exist; check `allowed_tables`.
3. `identifiers` — a quoted column that is not in the schema. The error carries
   `difflib` suggestions; those go into the repair prompt.
4. `explain` — a binder or type error DuckDB found while planning. Usually an
   aggregate over a text column, or an unquoted hallucinated name.
5. `empty` — the query ran but matched nothing. Almost always a period filter
   outside the data's real range; check the date range in the schema card.

## Date handling

Dates are parsed at load time with a format detected from the values, not
guessed by `read_csv_auto`. When day/month order cannot be proven from the
data, `app/data/typing.py` records an ambiguity warning that becomes a caveat
in the report. Never resolve such an ambiguity by assumption in query code.
