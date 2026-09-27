# YAML export & import

Predefined queries and dashboards can be exported to plain YAML files and
imported back — one entity at a time, or a whole workspace as a single bundle.
Unlike [git sync](./gitsync.md) this needs no git remote — just a file you can
share or use to copy content between workspaces and instances. Connections are
never exported (their config is encrypted credentials).

## Documents

Every exported document is self-describing via a top-level `kind`; import
dispatches on the file's content, never on its name.

```yaml
# kind: query — one predefined query
kind: query
type: clickhouse
query_name: top users
query: |-
  SELECT user, count() FROM events GROUP BY user
cell_view: ... # optional, raw YAML text (see query.md#cell-views)
order_by: # optional
  - { name: count, dir: DESC }
fields: [user, count] # optional
```

```yaml
# kind: dashboard — one dashboard
kind: dashboard
name: sales
html: |
  <html>...</html>
queries:
  panel1: SELECT ...
```

```yaml
# kind: workspace — everything a workspace owns
kind: workspace
queries: # list of query entries (as above, minus kind)
  - { type: clickhouse, query_name: ..., query: ... }
dashboards: # list of dashboard entries (as above, minus kind)
  - { name: ..., connection: ..., html: ..., queries: {} }
```

Import upserts by name into the target workspace (same overwrite semantics as
a git-sync restore) and validates the whole document — including `cell_view`
([query.md](./query.md#cell-views)) and `order_by`/`fields` — before writing
anything, so a malformed file changes nothing. The bundle carries no workspace
name, so it imports into whichever workspace you choose.

## UI

Next to each entity's **Commit**/**Restore** buttons (query panel and
dashboard page): **Export** downloads the saved DB state as a YAML file;
**Import** picks a YAML file and upserts whatever its `kind` declares. The
workspace manage panel (header dropdown → *Manage workspaces…*) has the same
pair for the whole active workspace.

## API

- `GET /api/export?kind=&name=&conn_type=&workspace=` → the YAML document,
  with a `Content-Disposition` download filename
  (`{name}.query.yaml` / `{name}.dashboard.yaml` / `{workspace}.workspace.yaml`).
- `POST /api/import?workspace=` with the raw YAML document as the request
  body → `{ok, kind, queries, dashboards}` (counts of upserted entities).

`kind` is `"query"`, `"dashboard"` or `"workspace"`; `name` is required for
entity kinds and `conn_type` for queries; `workspace` defaults to `default`.
Errors: `400` malformed document or missing arguments, `404` unknown
entity/workspace.

## Related docs

- [gitsync.md](./gitsync.md) — versioned backup/restore of the same entities via git.
- [query.md](./query.md) — predefined queries.
- [dashboard.md](./dashboard.md) — dashboards.
- [workspace.md](./workspace.md) — workspaces: entity ownership.
- [api.md](./api.md) — backend JSON API.
