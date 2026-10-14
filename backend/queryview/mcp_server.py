"""The MCP layer: a FastMCP server (mounted by main.py at /mcp) whose tools push
queries/scripts/dashboards to a live QueryView browser session, delegating to the
in-process remote.py hub."""

from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from . import gitsync, remote, sessions
from .dashboards import _push_dashboard
from .queries import list_predefined_queries_view
from .validation import dashboard_params_error

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
            "findings sources"). Selection only — nothing is persisted, unless
            the workspace has autosave on: then a successful auto-run saves it
            under this name. When the
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
    return {"ok": True, "database": r["database"], **_columns(r["meta"]), "rows": r["data"]}


def _columns(meta: list[dict[str, Any]] | None) -> dict[str, Any]:
    """The agent-facing column shape of a driver's meta (None: no result set)."""
    if meta is None:
        return {"columns": None, "types": None}
    return {"columns": [c["name"] for c in meta], "types": [c["type"] for c in meta]}


@mcp.tool()
async def run_script(session_id: str, sql: str) -> dict[str, Any]:
    """Run a `;`-separated script on the session's connection and selected
    database, like the Scripts page's Run all, returning each statement's result.
    WRITES ARE ALLOWED (use run_query to explore read-only). Stops at the first
    error; rows per statement are capped and the script has a timeout.

    Returns {"ok": True, "database", "results": [{sql, ok, status, message,
    columns, types, rows, truncated, elapsed_ms}]}, one entry per statement run
    (columns/types/rows null when it returned no rows), or {"ok": False,
    "message"} (e.g. "sql required", "not connected", "select a database first").

    Args:
        session_id: The session id shown in the QueryView popover.
        sql: The script; separate statements with `;`.
    """
    from .connect import execute_script

    if not sql.strip():
        return {"ok": False, "message": "sql required"}
    r = await execute_script(session_id, sql)
    if not r["ok"]:
        return {"ok": False, "message": r["message"]}
    results = [
        {**{k: v for k, v in s.items() if k not in ("meta", "data")}, **_columns(s["meta"]), "rows": s["data"]}
        for s in r["results"]
    ]
    return {"ok": True, "database": r["database"], "results": results}


@mcp.tool()
async def push_script(session_id: str, sql: str, run: bool = False) -> dict[str, Any]:
    """Replace the text of a live session's Scripts editor; with run=True the
    browser also runs it all. Results stay in the browser (use run_script to get
    them). Fails with "blocked, user editing" while the user types, or "not
    connected" / "select a database first" when the Scripts page can't open.

    Args:
        session_id: The session id shown in the QueryView popover.
        sql: The script; separate statements with `;`.
        run: Also run it (default False: load only).
    """
    from .connect import _gated_session

    # Otherwise the push would wait in the browser and replay (run included)
    # whenever the user next opens Scripts.
    s, err = await _gated_session(session_id)
    if s is None:
        return {"ok": False, "message": err["message"], "database": None}  # type: ignore[index]
    ok, message = remote.push(session_id, {"type": "script", "sql": sql, "run": run})
    return {"ok": ok, "message": message, "database": s.database}


@mcp.tool()
async def session_info(session_id: str) -> dict[str, Any]:
    """What a QueryView session is on: its connection, selected database, the
    databases it can switch to, its workspace, and the selected database's
    tables. Start here to discover schema; then run_query on the same session.

    The user picks the server and database in the UI (connection pill); the
    agent may only switch to session connections it added itself (see
    list_connections). Fully-qualify tables as db.table to reach another one.

    Args:
        session_id: The session id shown in the QueryView popover.

    Returns {"ok": True, "connected", "connection", "type", "scope",
    "created_by", "database", "databases", "workspace", "tables": [{name, ...}]};
    a disconnected session
    has "connected": False and no connection fields; "tables" is empty until a
    database is selected. Unknown session → {"ok": False, "message"}.
    """
    from .connect import get_session, list_tables

    rec = await sessions.get_session_rec(session_id) if session_id else None
    if rec is None:
        return {"ok": False, "message": "unknown session"}
    info: dict[str, Any] = {"ok": True, "workspace": rec.workspace, **await get_session(session_id)}
    if info["connected"]:
        info["connection"] = info.pop("name")
        listed = await list_tables(session_id)  # not ok until a database is picked
        tables: list[dict[str, Any]] = listed.get("tables") or []
        # The browse SELECT is for the Explorer UI; the agent writes its own SQL.
        info["tables"] = [{k: v for k, v in t.items() if k != "query"} for t in tables]
    return info


@mcp.tool()
async def list_connections(session_id: str) -> dict[str, Any]:
    """List the connections a session can use: its session connections (memory
    only, this session only) and the saved ones, each tagged with "scope"
    ("session" | "saved"), "created_by" ("agent" | "user") and "active".

    You may use_connection / remove_connection only scope="session",
    created_by="agent" entries; for anything else ask the user with
    pick_connection.

    Returns {"ok": True, "connections": [{name, type, scope, created_by,
    active}]} or {"ok": False, "message"} for an unknown session.
    """
    from .connect import list_connections_for

    rec = await sessions.get_session_rec(session_id)
    if rec is None:
        return {"ok": False, "message": "unknown session"}
    return {
        "ok": True,
        "connections": [
            {
                "name": c["name"],
                "type": c["type"],
                "scope": c["scope"],
                "created_by": c["created_by"],
                "active": c["name"] == rec.connection_name,  # names are unique
            }
            for c in await list_connections_for(session_id)
        ],
    }


@mcp.tool()
async def add_connection(session_id: str, name: str, type: str, config: dict[str, Any]) -> dict[str, Any]:
    """Ask the user, in a dialog in the armed browser, to add a session
    connection: kept in this session's memory only, never saved, gone when the
    session is deleted or QueryView restarts. Returns once the dialog is shown;
    once confirmed it appears in list_connections as yours, and use_connection
    switches to it.

    Args:
        session_id: The session id shown in the QueryView popover.
        name: A name no saved or session connection uses yet.
        type: The driver: "clickhouse" | "postgres" | "duckdb".
        config: The driver's fields — clickhouse/postgres: {host, port,
            username, password}; duckdb: {path} (or ":memory:").

    Returns {"ok", "message"}; not ok for a bad config, a taken name, or a
    session that is not armed.
    """
    from .connect import add_ask, drop_add, parse_driver_config, request_add

    if await sessions.get_session_rec(session_id) is None:
        return {"ok": False, "message": "unknown session"}
    if not name.strip():
        return {"ok": False, "message": "name required"}
    _, parsed, error = parse_driver_config({**(config if isinstance(config, dict) else {}), "type": type})
    if error or parsed is None:
        return {"ok": False, "message": error or "invalid config"}
    rid, error = await request_add(session_id, name.strip(), parsed, type)
    if rid is None:
        return {"ok": False, "message": error}
    ok, message = remote.push(session_id, add_ask(session_id) or {})
    if not ok:
        drop_add(session_id, rid)
    return {"ok": ok, "message": "waiting for the user to confirm" if ok else message}


@mcp.tool()
async def remove_connection(session_id: str, name: str) -> dict[str, Any]:
    """Remove a session connection you added (disconnecting the session if it
    was active). Saved and user-added connections are refused.

    Returns {"ok": True} or {"ok": False, "message"}.
    """
    from .connect import agent_owned_error, remove_session_connection

    err = agent_owned_error(session_id, name)
    if err is not None:
        return {"ok": False, "message": err}
    return await remove_session_connection(session_id, name)


@mcp.tool()
async def use_connection(session_id: str, name: str, database: str | None = None) -> dict[str, Any]:
    """Switch the session to a session connection you added, optionally
    selecting `database` (ClickHouse/Postgres need one before querying). The
    browser follows within a few seconds. Anything else is refused — ask the
    user with pick_connection.

    Returns {"ok": True, "name", "type", "databases", "database"} or
    {"ok": False, "message"}.
    """
    from .connect import agent_owned_error, open_saved

    err = agent_owned_error(session_id, name)
    if err is not None:
        return {"ok": False, "message": err}
    r = await open_saved(session_id, name, database)
    if not r["ok"]:
        return {"ok": False, "message": r["message"]}
    return r


@mcp.tool()
async def pick_connection(session_id: str, name: str, database: str | None = None) -> dict[str, Any]:
    """Ask the user, in a dialog in the armed browser, to switch the session to
    connection `name` (and optionally `database`). Use this for any connection
    you may not use_connection yourself. It returns once the dialog is shown,
    not when answered: check session_info afterwards.

    Returns {"ok", "message"}; not ok when the name is unknown or the session
    is not armed.
    """
    return await _ask(session_id, name, {"action": "pick", "database": database})


@mcp.tool()
async def promote_connection(session_id: str, name: str) -> dict[str, Any]:
    """Ask the user, in a dialog in the armed browser, to save session
    connection `name` to the saved connections (shared by every session). Only
    the user's confirmation saves it. Returns once the dialog is shown.

    Returns {"ok", "message"}.
    """
    from .connect import _session_conn

    if _session_conn(session_id, name) is None:
        return {"ok": False, "message": f'no session connection named "{name}"'}
    return await _ask(session_id, name, {"action": "promote"})


@mcp.tool()
async def select_database(session_id: str, database: str) -> dict[str, Any]:
    """Switch the session's database on its active connection. Direct on a
    session connection you added; otherwise it asks the user in a dialog in the
    armed browser and returns once the dialog is shown (check session_info).

    Returns {"ok", "message", "database"}; not ok when disconnected or the
    database is not in session_info's "databases".
    """
    from .connect import agent_owned_error, get_session
    from .connect import select_database as _select_database

    cur = await get_session(session_id)
    if not cur["connected"]:
        return {"ok": False, "message": "not connected", "database": None}
    if database not in cur["databases"]:
        return {"ok": False, "message": "unknown database", "database": cur["database"]}
    if agent_owned_error(session_id, cur["name"]) is None:
        r = await _select_database(session_id, database)
        return {"ok": r["ok"], "message": r.get("message", "selected"), "database": database}
    r = await _ask(session_id, cur["name"], {"action": "pick", "database": database})
    return {**r, "database": cur["database"]}


async def _ask(session_id: str, name: str, extra: dict[str, Any]) -> dict[str, Any]:
    """Push a connection dialog for the user to confirm in the browser."""
    from .connect import _session_conn, list_connection_names, unknown_connection_message

    if _session_conn(session_id, name) is None and name not in await list_connection_names():
        return {"ok": False, "message": await unknown_connection_message(name)}
    ok, message = remote.push(session_id, {"type": "connection", "name": name, **extra})
    return {"ok": ok, "message": "waiting for the user to confirm" if ok else message}


async def _session_workspace_rec(session_id: str | None):
    """The workspace the given session is on, read from its row, else the
    fallback workspace. MCP is deliberately workspace-unaware: the human picks
    the workspace in the UI; the agent works in session scope."""
    from . import workspaces

    name = await sessions.workspace_of(session_id) if session_id else None
    return await (workspaces.resolve(name) if name else workspaces.fallback())


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

    Returns {"dashboards": [{name, updated_at}]}; updated_at is
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
    params: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Push a dashboard to a live QueryView session.

    The dashboard renders immediately in the browser. By default it is a DRAFT:
    nothing is written to the store until the user's **Save** in the dashboard
    view, mirroring how push_query drafts a query. When the session's workspace
    has autosave on, a delivered push is also persisted (`persisted: true`).
    Re-push to update it. Its queries run on the viewing session's connection
    and selected database — a dashboard never names a connection.

    The browser consumes the results, not the agent: the HTML reads them from a
    `window.queries` global, a column-oriented map
    `{query_name: {column_name: [values, …]}}` — e.g.
    `window.queries.sales.revenue`. Load chart libraries from a CDN if needed.

    `params` declares selectors substituted into the queries' `{name}`
    placeholders (kinds value / identifier / dimension, `options` or
    `options_sql`, `default: none`); the page gets them as `window.params` and
    re-runs with `window.setParams({...})`. See docs/dashboard.md.

    Args:
        session_id: The session id shown in the QueryView popover.
        name: Dashboard name (the name the user's Save will persist under).
        html: The dashboard HTML document (renders in a sandboxed iframe).
        queries: Map of query name to SQL.
        params: Optional selector specs (see above).

    Returns {ok, pushed, persisted, message, database}; "not connected" if
    the session has no connection.
    """
    rec = await sessions.get_session_rec(session_id) if session_id else None
    if rec is None or rec.connection_name is None:
        return _push_failed("not connected")
    perr = dashboard_params_error(params)
    if perr is not None:
        return _push_failed(perr)
    pushed, persisted, message = await _push_dashboard(name, html, queries, session_id, params, rec.workspace)
    return {
        "ok": pushed,
        "pushed": pushed,
        "persisted": persisted,
        "message": message,
        "database": await sessions.database_of(session_id),
    }


def _push_failed(message: str) -> dict[str, Any]:
    return {"ok": False, "pushed": False, "persisted": False, "message": message, "database": None}


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
        ref: A sha from git_history or a branch name, read as origin/<name>
            (default: latest backup).
        session_id: Optional armed-session id; the operation runs in that
            session's workspace (default workspace otherwise).

    Returns {ok, restored, sha} or {ok: False, message}.
    """
    ws = await _session_workspace_rec(session_id)
    return await _git_tool(gitsync.restore(ws, kind, name, conn_type, ref))
