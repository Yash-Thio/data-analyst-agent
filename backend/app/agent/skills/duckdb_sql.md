# Writing DuckDB SQL for this app

You write the queries yourself. There are no helper tools and no templates, so
every step is one complete `SELECT` (or `WITH ... SELECT`) statement.

## The columns are already typed

The table was loaded with explicit casts derived from the actual values:
currency symbols, thousands separators, accounting negatives and the date
format were all handled at load time.

```sql
-- correct
SELECT SUM("Sales") FROM data WHERE "Date" >= DATE '2014-01-01'

-- wrong: re-casting an already-typed column
SELECT SUM(TRY_CAST(REPLACE("Sales", '$', '') AS DOUBLE)) FROM data
SELECT SUM("Sales") FROM data WHERE CAST("Date" AS DATE) >= DATE '2014-01-01'
```

## Identifiers

- Quote every column exactly as the schema spells it: `"Gross Sales"`, `"2025-01-01"`.
- Quote any alias that is not a plain word: `AS "Q3 2024"`, `AS "2014"`.
  `AS 2014` is a syntax error.
- Only the tables named in the schema card exist. There is no `sales`,
  `orders` or `customers` table unless it is listed.

## Aggregation

- Aggregate only columns marked **measure**.
- Columns marked **identifier** are labels. `SUM("Region Code")` is meaningless
  even though it type-checks.
- Columns marked **temporal** with a grain such as `year` or `month_of_year`
  are period keys - group by them, never sum them.

## Dates and periods

```sql
-- a quarter
WHERE "Date" >= DATE '2014-07-01' AND "Date" < DATE '2014-10-01'

-- monthly trend
SELECT date_trunc('month', "Date") AS "month", SUM("Sales") AS "total"
FROM data GROUP BY 1 ORDER BY 1

-- comparing two periods in one query
SELECT
    CASE WHEN "Date" >= DATE '2014-07-01' THEN 'Q3' ELSE 'Q2' END AS "period",
    SUM("Sales") AS "total"
FROM data
WHERE "Date" >= DATE '2014-04-01' AND "Date" < DATE '2014-10-01'
GROUP BY 1
```

Check the date range in the schema card before writing a filter. A period
outside the data returns zero rows, which cannot support any finding.

## Wide datasets

When the schema card lists a `data_long` view, the source file stores each
period as its own column. Prefer `data_long` for anything involving time:

```sql
SELECT "Region Name", AVG("value") AS "avg_rate"
FROM data_long
GROUP BY 1 ORDER BY "avg_rate" DESC LIMIT 10
```

## Messy categories

If the schema card says a column has values differing only by case, group on
the normalised form so they do not split:

```sql
SELECT UPPER(TRIM("Country")) AS "country", SUM("Profit") AS "profit"
FROM data GROUP BY 1 ORDER BY "profit" DESC
```

## Shape of the result

- Aggregate. A step that returns thousands of raw rows explains nothing.
- Rankings need `ORDER BY ... DESC LIMIT n`.
- Alias every computed column: `SUM("Profit") AS "total_profit"`.
- Exclude NULLs from a metric when they would distort an average.

## Not allowed

One statement only. No `INSERT`, `UPDATE`, `DELETE`, DDL, `PRAGMA`, `ATTACH`,
or file functions such as `read_csv` and `read_parquet`.
