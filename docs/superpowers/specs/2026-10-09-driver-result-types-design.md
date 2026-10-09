# Driver result types

One result shape for every driver method, so callers narrow with `isinstance`
and the type checker follows.

## Problem

The driver layer returns results in five shapes:

| Shape | Where |
|---|---|
| `ChResult(ok, value: str)` | ClickHouse HTTP client |
| `QueryRows \| str` | ClickHouse `ch_json` |
| `QueryResult(ok, rows, message)` | `run_query`, all drivers |
| `TextResult(ok, value)` | `export_csv`, all drivers |
| `tuple[bool, X \| str]` | `list_databases`, `list_tables`, `describe_query`, all drivers |

Pyright cannot narrow `value` after `if not ok` on an unpacked tuple, so
`connect.py` carries three `# type: ignore` lines and the ClickHouse driver
grew a sixth shape to work around it.

## Scope

The driver layer only: `drivers/base.py`, the three drivers, and their
consumers in `connect.py`. `parse_config`, `test()`, `_build_session`,
`_gated_session`, and the API's `{"ok": ...}` dicts keep their shapes; their
callers handle those as they do now.

## Design

### Shared types, `drivers/base.py`

Payload classes only. No driver knowledge.

```python
class Result: ...                                   # marker base

@dataclass(frozen=True)
class Err(Result):
    message: str

@dataclass(frozen=True)
class RowsResult(Result):
    rows: QueryRows

@dataclass(frozen=True)
class TextResult(Result):
    text: str

@dataclass(frozen=True)
class DatabasesResult(Result):
    databases: list[str]

@dataclass(frozen=True)
class TablesResult(Result):
    tables: list[dict[str, Any]]                    # {"name", "rows", "bytes"} as today

@dataclass(frozen=True)
class FieldsResult(Result):
    fields: list[dict[str, str]]                    # {"name", "type"} as today
```

`QueryRows` and `Column` are unchanged. `QueryResult` and `TextResult`'s old
`(ok, value)` form are deleted.

### Driver protocol

| Method | Returns |
|---|---|
| `list_databases` | `DatabasesResult \| Err` |
| `list_tables` | `TablesResult \| Err` |
| `run_query` | `RowsResult \| Err` |
| `export_csv` | `TextResult \| Err` |
| `describe_query` | `FieldsResult \| Err` |

Annotations name the concrete union, never the `Result` base: pyright narrows
`X | Err` past an `isinstance(r, Err)` check, but not `Result`.

### Consumer idiom

```python
r = await driver.list_tables(config, database)
if isinstance(r, Err):
    return {"ok": False, "message": r.message}
tables = r.tables
```

### ClickHouse client, `drivers/clickhouse.py`

The driver subclasses the shared results; only the subclasses know the wire
format. `ch_query` takes the result type and returns it decoded.

```python
class ChResult(Result):
    clause: ClassVar[str | None]                    # the FORMAT clause; None for the server default
    @classmethod
    def from_text(cls, text: str) -> Self | Err: ...

class ChText(TextResult, ChResult):                 # clause = None; from_text -> cls(text)
class ChCsv(ChText):                                # clause = "CSVWithNames"
class ChRows(RowsResult, ChResult):                 # clause = "JSONCompact"; from_text parses

R = TypeVar("R", bound=ChResult)

async def ch_query(c, query, kind: type[R], database=None, settings=None) -> R | Err:
    # transport as today; Err on timeout, HTTP error, non-2xx
    return kind.from_text(text)
```

`ChRows.from_text` is today's `ch_json` validation: `json.loads`, `meta` and
`data` present, every row a list with one cell per `meta` column; anything else
is `Err("unexpected JSON from ClickHouse: ...")`. Settings (`JSON_COMPACT_SETTINGS`)
stay a parameter, passed by `run_query` only.

The old `ChResult` NamedTuple and `ch_json` are deleted; `ChResult` is now the base above.

### ClickHouse driver methods

```python
r = await ch_query(config, "SHOW DATABASES", ChRows)
if isinstance(r, Err):
    return r
if len(r.rows.meta) < 1:
    return Err("unexpected JSON from ClickHouse: too few columns")
return DatabasesResult([row[0] for row in r.rows.data])
```

`list_tables` indexes three columns, `describe_query` two. `run_query` returns
the `ChRows` as is (it is a `RowsResult`). `export_csv` uses `ChCsv`.

### Postgres and DuckDB

Mechanical: `return True, x` becomes `return XResult(x)`, `return False, msg`
becomes `return Err(msg)`, `QueryResult(True, rows)` becomes `RowsResult(rows)`.
`_fetch_page` helpers are unchanged.

### `connect.py`

`_build_session`, `describe_query`, `list_tables`, `run_query`, and
`export_csv` switch to the consumer idiom. The three `# type: ignore` lines
go away. The dicts they return are unchanged, so `main.py`, `mcp_server.py`,
and the frontend do not change.

## Testing

- `test_clickhouse.py`: existing cases assert on the new classes; the four
  malformed-body cases stay and now exercise `ChRows.from_text`. One new case:
  `export_csv` requests `CSVWithNames` and returns `TextResult`.
- `test_postgres.py`, `test_duckdb.py`: assertions move from `ok, x` to the
  named field or `Err`.
- `test_connect_flow.py`, `test_dashboard_queries.py`: fake drivers return the
  new classes.
- `test_contract.py`: one new check, every driver method's return annotation is
  `<Result subclass> | Err`.
- Lint and pyright must pass with no new `type: ignore`.
- e2e is unchanged and must still pass for ClickHouse.

## Not in scope

- `parse_config`, `test()`, session helpers, API dict format.
- A `Result` base with `ok`; the union is what gives narrowing.
- Generic `Ok[T]`; rejected in favor of named fields.
