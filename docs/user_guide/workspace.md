# Workspaces

A **workspace** groups your dashboards, and each one can back up to its own git
remote ([gitsync.md](./gitsync.md)). Names are unique per workspace, so two
workspaces can each have a "daily revenue" dashboard. Connections are shared:
any workspace can use any connection. To copy a workspace as a file instead,
see [export-import.md](./export-import.md).

A `default` workspace exists from the start, with no remote and on branch
`main`; you can rename it like any other. The **fallback** workspace, used for
new sessions and when a request names none, is the oldest one, whatever its
name. Renaming a workspace keeps its sessions on it; deleting one moves them to
the fallback, and the last workspace can't be deleted.

## Switch and manage workspaces

<!-- req: switcher -->
The header shows a workspace switcher (dropdown + manage panel for
create/rename/remote/branch/delete). The active workspace is session state
(see [session.md](./session.md)); switching reloads the query and dashboard
lists.

## Set a git remote

You set a workspace's remote and branch in the manage panel; they are kept in
the app's database, not in environment variables. A token in the remote URL is
stored encrypted and never shown again: the panel shows the URL with the
credential stripped (`https://host/org/repo.git`, or an SSH URL as is). A
workspace without a remote is a plain namespace, and its git controls are
disabled.

You can delete a workspace only once it is empty; the git remote keeps its
history either way.

## Workspaces and your agent

Your agent never picks a workspace: it has no workspace parameter and no
workspace tools. It works in the workspace of the session you invited it into
([mcp.md](./mcp.md#arming-a-session)), and `list_dashboards` and the `git_*`
tools use the fallback when given no session. Creating and configuring
workspaces stays in the app, since a remote can carry a secret.

## Why

Connections are shared across workspaces rather than owned by one: a workspace
is then a cheap namespace for one team's dashboards, with no connection to
re-enter per workspace.

## Related docs

- [gitsync.md](./gitsync.md) — backup & restore mechanics.
- [dashboard.md](./dashboard.md) — dashboards.
- [export-import.md](./export-import.md) — copying a workspace as YAML.
- [mcp.md](./mcp.md) — connecting an agent and arming a session.
