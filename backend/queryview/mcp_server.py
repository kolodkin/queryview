"""The MCP layer: a FastMCP server (mounted by main.py at /mcp) whose tools push
queries/dashboards to a live QueryView browser session, delegating to the
in-process remote.py hub."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from . import gitsync, remote, sessions
from .dashboards import _push_dashboard
from .queries import list_predefined_queries_view

mcp = FastMCP("queryview", stateless_http=True)
mcp.settings.streamable_http_path = "/"


@mcp.tool()
async def push_query(
    session_id: str,
    query: str,
    limit: int = 100,
    offset: int = 0,
    order_by: list[dict[str, Any]] | None = None,
    fields: list[str] | None = None,
    cell_view: str | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """Push a SQL query to a live QueryView browser session.

    The targeted browser fills its query panel and auto-runs the query against
    the session's own connection. Get the `session_id` from the QueryView UI:
    the agent icon next to the connection status pill, after enabling "Allow
    remote control". To explore data first, use run_query with the same id.

    Args:
        session_id: The session id shown in the QueryView popover.
        query: The SQL to run.
        limit: Page size (default 100).
        offset: Row offset (default 0).
        order_by: Optional sort, e.g. [{"name": "id", "dir": "DESC"}].
        fields: Optional column names to display; omit to show all columns.
        cell_view: Optional raw cell-view YAML (column -> {type, value}) applied
            to this pushed result only, e.g. to render a column as a custom
            HTML token. Same format as the "Cell view" modal; see docs/query.md.
            Unlike the modal it isn't persisted — it rides with this one push and
            overrides any selected predefined query's saved cell_view.
        name: Optional predefined-query name to select in the dropdown (e.g.
            "findings sources"). Selection only — nothing is persisted. When the
            name matches a saved query and no `cell_view` is given, the pushed
            result renders with that query's saved cell_view.
    """
    payload = {
        "type": "query",
        "query": query,
        "limit": limit,
        "offset": offset,
        "order_by": order_by,
        "fields": fields,
        "cell_view": cell_view,
        "name": name,
    }
    ok, message = remote.push(session_id, payload)
    return {"ok": ok, "message": message, "database": await sessions.database_of(session_id)}


@mcp.tool()
async def run_query(
    session_id: str,
    query: str,
    limit: int = 1000,
    offset: int = 0,
) -> dict[str, Any]:
    """Run a read-only SQL query on the session's connection and selected
    database, returning the rows to the agent (push_query only fills a browser
    panel). Use it to explore schema and data before a push.

    Returns {"ok": True, "database", "columns", "types", "rows": [[...]]} —
    values typed as the driver returns them (64-bit integers and decimals as
    strings) — or {"ok": False, "message"} (e.g. "not connected", "select a
    database first"). The user can switch `database` from the connection pill;
    check it before deciding whether to fully-qualify tables as db.table.

    Args:
        session_id: The session id shown in the QueryView popover.
        query: The SQL to run.
        limit: Page size (default 1000, max 10000).
        offset: Row offset (default 0).
    """
    from .connect import run_query as _run_query
    from .validation import MAX_LIMIT

    limit = max(0, min(limit, MAX_LIMIT))
    offset = max(0, offset)
    r = await _run_query(session_id, query, limit, offset)
    if not r["ok"]:
        return {"ok": False, "message": r["message"]}
    return {
        "ok": True,
        "database": r["database"],
        "columns": [c["name"] for c in r["meta"]],
        "types": [c["type"] for c in r["meta"]],
        "rows": r["data"],
    }


async def _session_workspace_rec(session_id: str | None):
    """The workspace the given session is on, read from its row, else the
    default workspace. MCP is deliberately workspace-unaware: the human picks
    the workspace in the UI; the agent works in session scope."""
    from . import workspaces

    name = await sessions.workspace_of(session_id) if session_id else None
    return await workspaces.resolve(name or workspaces.DEFAULT_WORKSPACE)


@mcp.tool()
async def list_queries(conn_type: str = "clickhouse", session_id: str | None = None) -> dict[str, Any]:
    """List the saved (predefined) queries for a connection type.

    These are reusable queries a human has saved, shared per connection type
    (default "clickhouse") within a workspace. Returns
    {"queries": [{query_name, query, cell_view, order_by, fields}]}, where
    order_by is [{"name","dir"}] or null, fields is ["col", ...] or null, and
    cell_view is raw YAML or null. Pass a query_name back as push_query's `name`
    to select that query in the browser (its saved presentation then applies).

    Args:
        conn_type: Connection type to list queries for.
        session_id: Optional armed-session id; scopes the list to that
            session's workspace (default workspace otherwise).
    """
    ws = await _session_workspace_rec(session_id)
    return {"queries": await list_predefined_queries_view(conn_type, ws.id)}


@mcp.tool()
async def list_dashboards(session_id: str | None = None) -> dict[str, Any]:
    """List the saved dashboards (names + metadata, no HTML/queries payload).

    Use this to discover dashboard names — e.g. to pick a `name` for
    git_store/git_history/git_restore with kind="dashboard", or to avoid
    overwriting an existing dashboard when pushing a new one.

    Args:
        session_id: Optional armed-session id; scopes the list to that
            session's workspace (default workspace otherwise).

    Returns {"dashboards": [{name, connection, updated_at}]}; updated_at is
    unix ms.
    """
    from .dashboards import list_dashboards as _list_dashboards

    ws = await _session_workspace_rec(session_id)
    return {"dashboards": await _list_dashboards(ws.id)}


@mcp.tool()
async def push_dashboard(
    session_id: str,
    name: str,
    html: str,
    queries: dict[str, str],
) -> dict[str, Any]:
    """Push a dashboard DRAFT to a live QueryView session (does not persist).

    The dashboard renders immediately in the browser, but nothing is written to
    the store — only the user's **Save** button in the dashboard view persists
    it, mirroring how push_query drafts a query for the user to Save. Re-push to
    update the live draft. Its queries run on the session's connection, which
    the Save keeps.

    The browser consumes the results, not the agent: the HTML reads them from a
    `window.queries` global, a column-oriented map
    `{query_name: {column_name: [values, …]}}` — e.g.
    `window.queries.sales.revenue`. Load chart libraries from a CDN if needed.

    Args:
        session_id: The session id shown in the QueryView popover.
        name: Dashboard name (the name the user's Save will persist under).
        html: The dashboard HTML document (renders in a sandboxed iframe).
        queries: Map of query name to SQL.

    Returns {ok, pushed, message, database}; "not connected" if the session
    has no connection.
    """
    rec = await sessions.get_session_rec(session_id) if session_id else None
    if rec is None or rec.connection_name is None:
        return {"ok": False, "pushed": False, "message": "not connected", "database": None}
    pushed, message = await _push_dashboard(name, rec.connection_name, html, queries, session_id)
    return {
        "ok": pushed,
        "pushed": pushed,
        "message": message,
        "database": await sessions.database_of(session_id),
    }


async def _git_tool(coro) -> dict[str, Any]:
    """Await a gitsync operation, mapping its result (or GitSyncError) to the
    tool result — the one place the git-tool error contract lives."""
    try:
        return {"ok": True, **(await coro)}
    except gitsync.GitSyncError as e:
        return {"ok": False, "message": str(e)}


@mcp.tool()
async def git_store(
    kind: str,
    name: str,
    conn_type: str | None = None,
    message: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Back up one predefined query or dashboard to its workspace's git remote.

    Exports the entity's saved DB state as files, makes one commit, and pushes.
    Requires the target workspace to have a git remote configured. Versions are
    git commits — use git_history to list them and git_restore to roll back.

    Args:
        kind: "query" or "dashboard".
        name: The entity's name.
        conn_type: The query's connection type (e.g. "clickhouse"); required
            for kind="query", ignored for dashboards.
        message: Optional commit message (default: "store query {conn_type}/{name}"
            for queries, "store dashboard {name}" for dashboards).
        session_id: Optional armed-session id; the operation runs in that
            session's workspace (default workspace otherwise).

    Returns {ok, committed, sha, message}; committed=False with "no changes"
    when the repo already matches the DB.
    """
    ws = await _session_workspace_rec(session_id)
    return await _git_tool(gitsync.store(ws, kind, name, conn_type, message))


@mcp.tool()
async def git_history(
    kind: str,
    name: str,
    conn_type: str | None = None,
    before: str | None = None,
    limit: int = 10,
    session_id: str | None = None,
) -> dict[str, Any]:
    """List an entity's backup revisions (commits touching it), newest first.

    Args:
        kind: "query" or "dashboard".
        name: The entity's name.
        conn_type: The query's connection type; required for kind="query".
        before: A sha from a previous page; returns strictly older revisions.
        limit: Page size (default 10).
        session_id: Optional armed-session id; the operation runs in that
            session's workspace (default workspace otherwise).

    Returns {ok, revisions: [{sha, date, message}], has_more}; date is unix ms.
    Pass a sha to git_restore's `ref` to restore that revision.
    """
    ws = await _session_workspace_rec(session_id)
    return await _git_tool(gitsync.history(ws, kind, name, conn_type, before, limit))


@mcp.tool()
async def git_restore(
    kind: str,
    name: str,
    conn_type: str | None = None,
    ref: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Overwrite the local DB copy of one query/dashboard with a git revision.

    Reads the entity's files at `ref` (default: the remote branch head) and
    upserts them into the store. Git history is untouched — HEAD never moves;
    a later git_store simply commits on top.

    Args:
        kind: "query" or "dashboard".
        name: The entity's name.
        conn_type: The query's connection type; required for kind="query".
        ref: A sha from git_history (default: latest backup).
        session_id: Optional armed-session id; the operation runs in that
            session's workspace (default workspace otherwise).

    Returns {ok, restored, sha} or {ok: False, message}.
    """
    ws = await _session_workspace_rec(session_id)
    return await _git_tool(gitsync.restore(ws, kind, name, conn_type, ref))
