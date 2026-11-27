# YAML export & import

Export a dashboard, or a whole workspace, as a plain YAML file and import it
back, from the dashboard page (`/dashboard`) or the workspace manage panel.
Unlike [git sync](./gitsync.md) this needs no git remote: it is a file you
share or use to copy dashboards between workspaces and instances. Connections
are never exported, since their config holds credentials.

## Move a dashboard as YAML

<!-- req: yaml-export-import -->
You can move a dashboard between instances as YAML.

- Export downloads the dashboard as a YAML file.
- Importing that file saves the dashboard as it was exported, over any copy of
  the same name.

## Export and import

<!-- req: ui -->
Next to the dashboard page's **Restore** button: **Export** downloads the saved DB state as a YAML file;
**Import** picks a YAML file and upserts whatever its `kind` declares. The
workspace manage panel (header dropdown → *Manage workspaces…*) has the same
pair for the whole active workspace.

## The file format

Every exported file says what it holds in a top-level `kind`; import goes by
the file's content, never its name.

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
  - { name: ..., html: ..., queries: {} }
```

Import overwrites dashboards of the same name in the workspace you import into
(as a git-sync restore does) and checks the whole file before writing
anything, so a malformed file changes nothing. A `kind: query` file, or a
bundle carrying a non-empty `queries` list, is refused with
`saved queries are no longer supported`. A bundle names no workspace, so it
imports into whichever one you choose.

A query entry is written as stored: a SQL string, or a
[federated](./dashboard.md#federated-dashboards) map
`{connection, sql, database?}`. A dashboard mixing the two is refused with
`every query and options_sql names a connection, or none does`.

## Related docs

- [gitsync.md](./gitsync.md) — versioned backup/restore of the same entities via git.
- [dashboard.md](./dashboard.md) — dashboards.
- [workspace.md](./workspace.md) — workspaces: entity ownership.
- [api.md](../architecture/api.md) — the export and import endpoints.
