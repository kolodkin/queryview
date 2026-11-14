# YAML export & import

Dashboards can be exported to plain YAML files and imported back — one at a
time, or a whole workspace as a single bundle.
Unlike [git sync](./gitsync.md) this needs no git remote — just a file you can
share or use to copy content between workspaces and instances. Connections are
never exported (their config is encrypted credentials).

## Documents

Every exported document is self-describing via a top-level `kind`; import
dispatches on the file's content, never on its name.

```yaml
# kind: dashboard — one dashboard
kind: dashboard
name: sales
html: |
  <html>...</html>
queries:
  panel1: SELECT ...
params: # optional selectors, see dashboard.md#dashboard-parameters
  - { name: region, options: [eu, us] }
```

```yaml
# kind: workspace — everything a workspace owns
kind: workspace
dashboards: # list of dashboard entries (as above, minus kind)
  - { name: ..., connection: ..., html: ..., queries: {} }
```

Import upserts by name into the target workspace (same overwrite semantics as
a git-sync restore) and validates the whole document before writing
anything, so a malformed file changes nothing. A `kind: query` document, or a
bundle carrying a non-empty `queries` list, is refused with
`saved queries are no longer supported`. The bundle carries no workspace
name, so it imports into whichever workspace you choose.

## UI

Next to the dashboard page's **Commit**/**Restore** buttons: **Export** downloads the saved DB state as a YAML file;
**Import** picks a YAML file and upserts whatever its `kind` declares. The
workspace manage panel (header dropdown → *Manage workspaces…*) has the same
pair for the whole active workspace.

## API

- `GET /api/export?kind=&name=&workspace=` → the YAML document,
  with a `Content-Disposition` download filename
  (`{name}.dashboard.yaml` / `{workspace}.workspace.yaml`).
- `POST /api/import?workspace=` with the raw YAML document as the request
  body → `{ok, kind, dashboards}` (the count of upserted dashboards).

`kind` is `"dashboard"` or `"workspace"`; `name` is required for a
dashboard; `workspace` defaults to the fallback workspace.
Errors: `400` malformed document or missing arguments, `404` unknown
entity/workspace.

## Related docs

- [gitsync.md](./gitsync.md) — versioned backup/restore of the same entities via git.
- [dashboard.md](./dashboard.md) — dashboards.
- [workspace.md](./workspace.md) — workspaces: entity ownership.
- [api.md](./api.md) — backend JSON API.
