# A query run once per value: the `each` param

## Intent

Let a dashboard query run once per value of a list and arrive as one table, so
a heavy query over many partitions (one database per tenant, one table per
region) becomes several small ones run side by side.

Measured on a real dashboard whose query joins every partition at once: 10.3 s
as one query; the same SQL per partition takes 5.2 s for the largest and under
0.7 s for each of the rest (8.2 s summed). Run five at a time, the largest
partition sets the time.

## Approaches

1. **A param kind, `each`**: a list nobody picks from. A query that references
   it runs per value. `queries.yaml` keeps its `{name: SQL}` shape, and the
   list comes from `options` / `options_sql` like any selector's. **Picked.**
2. A marker on the query (`sales: {sql: …, for_each: region}`): says the same
   thing twice (the SQL already names the param) and changes the file's shape.
3. Nothing in the framework; precompute in the database. Fastest to read, but
   it is not the dashboard author's to build.

## Design

```yaml
# meta.yaml
params:
  - name: region
    kind: each
    options_sql: SELECT DISTINCT region FROM orders ORDER BY region
```

```yaml
# queries.yaml
sales: |
  SELECT {region} AS region, count() AS orders, sum(amount) AS revenue
  FROM orders WHERE region = {region}
totals: SELECT count() AS orders FROM orders
```

`sales` runs once per region; `window.queries.sales` is the rows of every run,
stacked in the list's order. `totals` names no `each` param and runs once.

The param:

- Needs `options` or `options_sql`; takes no `default` and no value. A value
  sent for it is ignored.
- Its `options_sql` may reference other params (a typed text narrowing the
  list), never another `each`. No other param's `options_sql` may reference it.
- Substitutes as a `value` does, casts included (`{region:identifier}`).
- Resolves to `{name, kind: 'each', options, value: ''}`. `<qv-param>` draws
  nothing for it.

The run (`dashboard_params.apply_to_queries`, `dashboard_queries.run_queries_on`):

- A query naming one `each` param becomes one SQL per option; all of a run's
  SQL share the five-at-a-time limit.
- Naming two `each` params is a params error.
- No options: the query's result is empty, with no columns.
- More than 100 options is a params error.
- The runs must return the same columns, in name and order; otherwise the
  query fails with `sales: columns differ between values`.
- A failing run fails the query, as today, named with its value:
  `sales[eu]: Unknown table …`.
- The 1000-row cap applies to each run and again to the stacked rows, which
  keep the first 1000 in list order.
- A widget (`<qv-select-view query="sales">`) cannot page a fan-out query: its
  describe and query answer `a widget cannot page a query run per value`.

Reach: `KINDS` in `dashboard_params.py` and `validation.py`, `ParamKind` in
`params.ts`, `ParamSelect.tsx`. The viewer server runs the same functions.

Docs: the kinds table and a section in `dashboard.md`; the `/api/runqueries`
row in `api.md`.

Tests (backend unit unless said): stacking and order; the shared limit; the two
`each` error; no options; over 100; differing columns; a failing value's
message; the row cap; a widget's refusal; validation accepts the kind. One e2e:
a dashboard whose table holds the rows of every value.

## Non-goals

- Skipping a value that fails. The list is the author's: `options_sql` returns
  only the values the query can run on.
- Results that appear value by value as each run finishes.
- Paging or sorting a fan-out query in a widget.

## Decided

1. One failing value fails the whole query.
2. 100 values is the ceiling.
