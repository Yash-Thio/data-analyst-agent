# Any-CSV SQL Agent — Checklist

Progress against [the plan](.cursor/plans/any_csv_sql_agent_a9cf3b25.plan.md).
Two goals: **handle any CSV with any natural-language question**, and **be
robust enough that errors degrade instead of lying or crashing**.

## Phase 1 — Ingestion and semantic profiling

- [x] Two-stage load: `data_raw` as `all_varchar`, then a typed `data` view
      built from verified cast expressions (`app/data/duckdb_engine.py`)
- [x] Date-format detection with day/month disambiguation (`app/data/typing.py`)
- [x] Query timeout applied via connection interrupt, plus a `truncated` flag
      instead of a silent row cap
- [x] Semantic profiler: semantic types, roles, identifier detection,
      placeholder-tolerant currency, parse-verified temporal (`app/data/profiler.py`)
- [x] Data-quality report with normalised grouping expressions (`app/data/quality.py`)

## Phase 2 — Any CSV shape

- [x] Wide-layout detection from date-like headers (`app/data/reshape.py`)
- [x] `data_long` UNPIVOT view, with the reporting grain inferred from header spacing
- [x] Both views advertised in the schema card

## Phase 3 — SQL-only execution

- [x] `plan_repair.py` and the template tools deleted
- [x] `AnalysisStep` carries SQL; `StepParams` removed
- [x] `QuestionInterpretation` generalised, with `answerable` / `clarification`
- [x] Schema card grounds the planner in real names, types, ranges and values
      (`app/agent/schema_card.py`)
- [x] SQL guard: static validation, table check, identifier check with
      suggestions, EXPLAIN dry run (`app/agent/sql_guard.py`)
- [x] Bounded repair loop on guard failure, runtime error or empty result
      (`app/agent/sql_repair.py`)

## Phase 4 — Verification and explainability integrity

- [x] Numbers in claims matched against the evidence they cite (`app/agent/verify.py`)
- [x] Claims backed only by zero-row evidence are dropped
- [x] Unverifiable figures downgrade confidence and add a caveat
- [x] `build_explanation` retries once on a bad evidence citation instead of dying

## Phase 5 — Robustness across the graph

- [x] `node_guard` converts any node failure into a recorded error
- [x] `execute_step` records failed steps and continues
- [x] Real `replan_analysis` node; `route_after_evaluate` honours the evaluation
- [x] Step and replan budgets prevent unbounded loops
- [x] Chart axes derived from result shape and semantic types
- [x] SSE: incremental emission, guaranteed terminal event, cancellation,
      bounded session store, `warning` / `step_retry` / `step_error` events

## Phase 6 — Frontend surfacing

- [x] `DatasetSummary` shows roles, detected date format, wide-layout note and
      quality warnings
- [x] Activity feed renders errors, warnings and retries distinctly
- [x] Report shows a degraded banner, per-claim verification badges and caveats
- [x] Charts skip specs that cannot be rendered

## Phase 7 — Tests and evaluation

- [x] Offline suite covering every confirmed bug (135 tests, no API key needed)
- [x] `tests/eval/questions.yaml` — 19 questions across all three sample datasets
- [x] Live runner: `pytest -m live`

## Confirmed bugs and their regression tests

| Bug | Test |
| --- | --- |
| `1/1/2014` parsed D/M/YYYY, collapsing 711 rows into January | `test_profiler_semantics.py::test_financial_dates_span_the_real_range` |
| `Series ID` (`ABIL148UR`) treated as a numeric metric | `test_profiler_semantics.py::test_series_id_is_an_identifier_not_a_measure` |
| `Discounts` classified categorical because of `$-` placeholders | `test_profiler_semantics.py::test_discounts_is_a_measure_despite_placeholder_rows` |
| `Year` / `Month Name` called temporal by name substring | `test_profiler_semantics.py::test_year_is_an_integer_period_not_a_date` |
| Wide CSV aborted the run before any query executed | `test_graph.py::test_wide_dataset_runs_end_to_end` |
| `CANADA` vs `germany` split into separate groups | `test_profiler_semantics.py::test_country_casing_inconsistency_is_reported` |
| Any tool failure killed the whole graph | `test_execute_step.py::test_unfixable_step_degrades_instead_of_raising` |
| `route_after_evaluate` ignored the evaluation | `test_graph.py::test_insufficient_evidence_triggers_one_replan` |
| Claims checked only for evidence-ID existence | `test_graph.py::test_invented_numbers_are_demoted` |
