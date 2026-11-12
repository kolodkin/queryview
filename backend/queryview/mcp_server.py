"""The MCP layer: an MCPServer (mounted by main.py at /mcp) whose tools push
queries/scripts/dashboards to a live QueryView browser session, delegating to the
in-process remote.py hub."""

from __future__ import annotations

import asyncio
from typing import Any

from mcp.server.mcpserver import Context, MCPServer

from . import gitsync, remote, sessions
from .connect import (
    _gated_session,
    _session_conn,
    add_session_connection,
    agent_connections_for,
    execute_script,
    get_session,
    list_databases_of,
    list_tables,
    open_saved,
    parse_driver_config,
    push,
    remove_session_connection,
)
from .connect import run_sql as connect_run_sql
from .connect import select_database as connect_select_database
from .dashboards import _push_dashboard, get_dashboard
from .mcp_skills import SkillsExtension
from .queries import get_predefined_query, list_predefined_queries_view
from .validation import dashboard_params_error

mcp = MCPServer(
    "queryview",
    description="Local, agent-controlled SQL workbench for ClickHouse, Postgres, DuckDB and SQLite.",
    instructions=(
        "Open your own tab with new_tab unless given a session id. Run SQL, reads and writes, with run_script "
        "(apply writes once), then push_script the final SQL with run=False. Use push_studio or "
        "push_dashboard only when asked. Full workflow: the queryview skill (skill://queryview/SKILL.md)."
    ),
    extensions=[SkillsExtension()],
)


@mcp.tool()
async def push_studio(
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
    remote control"; without one, open a tab of your own with new_tab.
    To explore data first, use run_script with the same id.
    A session on a locked connection (see session_info) refuses every push and
    query with "connection is locked"; use_connection another one.

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
        name: Optional name of an existing saved query (see list_queries) to
            edit: it is selected in the dropdown, and with no `cell_view` its
            saved cell_view applies. Nothing is persisted, unless the workspace
            has autosave on: then a successful auto-run saves over it. A name
            that isn't saved is refused — omit it to push an unnamed draft; the
            user names and saves it.
    """
    if name:
        info = await get_session(session_id)
        ws = await _session_workspace_rec(session_id)
        # A session that isn't connected lets the push itself say what's wrong.
        if info.get("connected") and await get_predefined_query(info["type"], name, ws.id) is None:
            return _failed(_NEW_NAME.format(kind="query", name=name))
    payload = {
        "type": "studio",
        "query": query,
        "limit": limit,
        "offset": offset,
        "order_by": order_by,
        "fields": fields,
        "cell_view": cell_view,
        "name": name,
    }
    ok, message = await push(session_id, payload)
    return _with_url(session_id, {"ok": ok, "message": message, "database": await sessions.database_of(session_id)})


@mcp.tool()
async def run_sql(session_id: str, sql: str, limit: int = 1000) -> dict[str, Any]:
    """Run one read-only SQL statement on the session's connection and selected
    database, returning the rows to the agent (push_studio only fills a browser
    panel). Use it to explore schema and data before a push. Runs as written
    (SELECT, DESCRIBE, SHOW, EXPLAIN...): page with your own LIMIT/OFFSET.
    Stops after a minute.

    Returns {"ok": True, "database", "columns", "types", "rows": [[...]],
    "truncated"} — values typed as the driver returns them (64-bit integers and
    decimals as strings), `truncated` when rows past `limit` were dropped — or
    {"ok": False, "message"} (e.g. "not connected", "select a database first").
    The user can switch `database` from the connection pill; check it before
    deciding whether to fully-qualify tables as db.table.

    Args:
        session_id: The session id shown in the QueryView popover.
        sql: The SQL statement to run.
        limit: Most rows to return (default 1000, max 10000).
    """
    from .drivers.base import RUN_SQL_TIMEOUT_SECONDS
    from .validation import MAX_LIMIT

    limit = max(0, min(limit, MAX_LIMIT))
    deadline = RUN_SQL_TIMEOUT_SECONDS + 10  # past the drivers' own limits: a backstop
    try:
        async with asyncio.timeout(deadline):
            r = await connect_run_sql(session_id, sql, limit + 1)
    except TimeoutError:
        return {"ok": False, "message": f"query timed out after {deadline}s"}
    if not r["ok"]:
        return {"ok": False, "message": r["message"]}
    rows = r["data"]
    return {
        "ok": True,
        "database": r["database"],
        **_columns(r["meta"]),
        "rows": rows[:limit],
        "truncated": len(rows) > limit,
    }


def _columns(meta: list[dict[str, Any]] | None) -> dict[str, Any]:
    """The agent-facing column shape of a driver's meta (None: no result set)."""
    if meta is None:
        return {"columns": None, "types": None}
    return {"columns": [c["name"] for c in meta], "types": [c["type"] for c in meta]}


@mcp.tool()
async def run_script(session_id: str, sql: str) -> dict[str, Any]:
    """Run a `;`-separated script on the session's connection and selected
    database, like the Scripts page's Run all, returning each statement's result.
    The default way to run SQL, reads and writes alike: WRITES ARE ALLOWED, so
    apply them once (run_sql is the read-only alternative). Stops at the first
    error; rows per statement are capped and the script has a timeout.

    Returns {"ok": True, "database", "results": [{sql, ok, status, message,
    columns, types, rows, truncated, elapsed_ms}]}, one entry per statement run
    (columns/types/rows null when it returned no rows), or {"ok": False,
    "message"} (e.g. "sql required", "not connected", "select a database first").

    Args:
        session_id: The session id shown in the QueryView popover.
        sql: The script; separate statements with `;`.
    """
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
        session_id: The session id shown in the QueryView popover, or new_tab's.
        sql: The script; separate statements with `;`.
        run: Also run it (default False: load only).
    """
    # Otherwise the push would wait in the browser and replay (run included)
    # whenever the user next opens Scripts.
    s, err = await _gated_session(session_id)
    if s is None:
        return _failed(err["message"])  # type: ignore[index]
    ok, message = remote.push(session_id, {"type": "script", "sql": sql, "run": run})
    return _with_url(session_id, {"ok": ok, "message": message, "database": s.database})


@mcp.tool()
async def session_info(session_id: str) -> dict[str, Any]:
    """What a QueryView session is on: its connection, selected database, the
    databases it can switch to, its workspace, and the selected database's
    tables. Start here to discover schema; then run_sql on the same session.

    Switch with use_connection / select_database (any connection
    list_connections shows). Fully-qualify tables as db.table to reach another one.

    Args:
        session_id: The session id shown in the QueryView popover.

    Returns {"ok": True, "connected", "connection", "type", "scope",
    "created_by", "locked", "database", "databases", "workspace",
    "tables": [{name, ...}]}; a disconnected session
    has "connected": False and no connection fields; "tables" is empty until a
    database is selected, and on a locked connection ("locked": True), which
    the agent may not query at all. Unknown session → {"ok": False, "message"}.
    """
    rec = await sessions.get_session_rec(session_id) if session_id else None
    if rec is None:
        return {"ok": False, "message": "unknown session"}
    info: dict[str, Any] = {"ok": True, "workspace": rec.workspace, **await get_session(session_id)}
    info.pop("unlocked", None)  # the tab's business, not the agent's
    if info["connected"]:
        info["connection"] = info.pop("name")
        listed = await list_tables(session_id)  # not ok until a database is picked
        tables: list[dict[str, Any]] = listed.get("tables") or []
        # The browse SELECT is for the Explorer UI; the agent writes its own SQL.
        info["tables"] = [{k: v for k, v in t.items() if k != "query"} for t in tables]
    return _with_url(session_id, info)


@mcp.tool()
async def list_connections(session_id: str) -> dict[str, Any]:
    """List the connections a session can use: its session connections (memory
    only, this session only) and the saved ones, each tagged with "scope"
    ("session" | "saved"), "created_by" ("agent" | "user") and "active".
    Locked saved connections are left out, even while a tab has one unlocked.

    You may use_connection any ClickHouse or Postgres one; remove_connection only
    scope="session", created_by="agent" entries.

    Returns {"ok": True, "connections": [{name, type, scope, created_by,
    active}]} or {"ok": False, "message"} for an unknown session.
    """
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
            for c in await agent_connections_for(session_id)
        ],
    }


@mcp.tool()
async def list_databases(session_id: str, connection: str | None = None) -> dict[str, Any]:
    """List the databases of every connection list_connections shows (locked
    ones are left out), fetched live from each server; only `connection`'s
    when given.

    Returns {"ok": True, "connections": [{name, type, databases}]}, where a
    connection that cannot be reached has "error" in place of "databases";
    {"ok": False, "message"} for an unknown session, or a `connection` that is
    unknown or locked.
    """
    if await sessions.get_session_rec(session_id) is None:
        return {"ok": False, "message": "unknown session"}
    conns = [c for c in await agent_connections_for(session_id) if connection in (None, c["name"])]
    if connection is not None and not conns:
        return {"ok": False, "message": f'no connection named "{connection}"'}  # locked reads as unknown
    return {"ok": True, "connections": list(await asyncio.gather(*(_databases_of(session_id, c) for c in conns)))}


async def _databases_of(session_id: str, c: dict[str, Any]) -> dict[str, Any]:
    """One list_connections entry's {name, type} plus its "databases" or "error"."""
    databases, error = await list_databases_of(session_id, c["name"])
    return {"name": c["name"], "type": c["type"]} | (
        {"error": error} if databases is None else {"databases": databases}
    )


# Network drivers only: DuckDB's and SQLite's SQL read any file the backend can.
_AGENT_DRIVERS = ("clickhouse", "postgres")


@mcp.tool()
async def add_connection(session_id: str, name: str, type: str, config: dict[str, Any]) -> dict[str, Any]:
    """Add a session connection of your own: kept in this session's memory
    only, never saved, gone when the session is deleted or QueryView restarts.
    Checks it connects; use_connection then switches to it.

    Args:
        session_id: The session id shown in the QueryView popover.
        name: A name no saved or session connection uses yet.
        type: "clickhouse" or "postgres" (DuckDB and SQLite are refused: they read local files).
        config: {host, port, username, password}.

    Returns {"ok": True, "name", "type", "databases"} or {"ok": False, "message"}.
    """
    if await sessions.get_session_rec(session_id) is None:
        return {"ok": False, "message": "unknown session"}
    if type not in _AGENT_DRIVERS:
        return {"ok": False, "message": f"the agent may add only {' or '.join(_AGENT_DRIVERS)} connections"}
    if not name.strip():
        return {"ok": False, "message": "name required"}
    _, parsed, error = parse_driver_config({**(config if isinstance(config, dict) else {}), "type": type})
    if error or parsed is None:
        return {"ok": False, "message": error or "invalid config"}
    state, message = await add_session_connection(session_id, name.strip(), parsed, type, "agent")
    if state is None:
        return {"ok": False, "message": message}
    return {"ok": True, "name": state.name, "type": type, "databases": state.databases}


@mcp.tool()
async def remove_connection(session_id: str, name: str) -> dict[str, Any]:
    """Remove a session connection you added (disconnecting the session if it
    was active). Saved and user-added connections are refused.

    Returns {"ok": True} or {"ok": False, "message"}.
    """
    sc = _session_conn(session_id, name)
    if sc is None or sc.created_by != "agent":
        whose = "a session connection the user added" if sc is not None else "not one of your session connections"
        return {"ok": False, "message": f'"{name}" is {whose}; ask the user to remove it in QueryView'}
    return await remove_session_connection(session_id, name, by="agent")


@mcp.tool()
async def use_connection(session_id: str, name: str, database: str | None = None) -> dict[str, Any]:
    """Switch the session to any ClickHouse or Postgres connection
    list_connections shows, optionally selecting `database` (both need one
    before querying). The browser follows within a few seconds. Locked
    connections are refused, and so are DuckDB and SQLite ones: they read local
    files.

    Returns {"ok": True, "name", "type", "databases", "database"} or
    {"ok": False, "message"}.
    """
    # shortcut: no switching to file drivers until DuckDB reads blob storage instead of local files
    listed = next((c for c in await agent_connections_for(session_id) if c["name"] == name), None)
    if listed is not None and listed["created_by"] != "agent" and listed["type"] not in _AGENT_DRIVERS:
        return {"ok": False, "message": f"the agent may switch only to {' or '.join(_AGENT_DRIVERS)} connections"}
    return await open_saved(session_id, name, database, by="agent")


@mcp.tool()
async def select_database(session_id: str, database: str) -> dict[str, Any]:
    """Switch the database of the session's active connection.

    Returns {"ok", "message", "database"}; not ok when disconnected, the
    connection is locked, or the database does not exist (a name missing from
    session_info's "databases" is re-checked against the server first).
    """
    cur = await get_session(session_id)
    if not cur["connected"]:
        return _failed("not connected")
    r = await connect_select_database(session_id, database)
    if not r["ok"]:
        return {"ok": False, "message": r["message"], "database": cur["database"]}
    return {"ok": True, "message": "selected", "database": database}


@mcp.tool()
async def open_explorer(session_id: str, database: str, table: str | None = None) -> dict[str, Any]:
    """Switch the session to `database` and open the browser's Explorer page
    (the table navigator) on it; with `table`, browse that table's rows (SELECT *
    with field and order-by pickers). Use push_studio instead for custom SQL.

    Returns {"ok", "message", "database"}; not ok when select_database fails,
    the table isn't in the database, or the push fails (unknown session,
    "blocked, user editing"). Past select_database, a failure still leaves the
    session on `database`.

    Args:
        session_id: The session id shown in the QueryView popover.
        database: A database of the session's connection.
        table: Optional table name as session_info's "tables" lists it.
    """
    r = await select_database(session_id, database)
    if not r["ok"]:
        return r
    if table is not None:
        listed = await list_tables(session_id)
        if not listed["ok"]:
            return {"ok": False, "message": listed["message"], "database": database}
        # A truncated list can't prove absence; the Explorer drops an unknown table itself.
        if not listed.get("truncated") and not any(t["name"] == table for t in listed["tables"]):
            return {"ok": False, "message": f'no table "{table}" in {database}', "database": database}
    ok, message = await push(session_id, {"type": "explorer", "table": table})
    return _with_url(session_id, {"ok": ok, "message": message, "database": database})


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
    cell_view is raw YAML or null. Pass a query_name back as push_studio's `name`
    to edit that query in the browser (its saved presentation then applies).

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
    git_store/git_history/git_restore with kind="dashboard", or to edit one
    with push_dashboard.

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
    html: str,
    queries: dict[str, str],
    params: list[dict[str, Any]] | None = None,
    name: str | None = None,
) -> dict[str, Any]:
    """Push a dashboard to a live QueryView session.

    The dashboard renders immediately in the browser. By default it is a DRAFT:
    nothing is written to the store until the user's **Save** in the dashboard
    view, mirroring how push_studio drafts a query. Omit `name` for a new
    dashboard: the user names it on Save. With the `name` of a saved dashboard
    (see list_dashboards) the push edits that one, and when the session's
    workspace has autosave on it is also persisted (`persisted: true`).
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
        html: The dashboard HTML document (renders in a sandboxed iframe).
        queries: Map of query name to SQL.
        params: Optional selector specs (see above).
        name: Optional name of an existing saved dashboard to edit; any other
            name is refused.

    Returns {ok, pushed, persisted, message, database}; "not connected" if
    the session has no connection.
    """
    rec = await sessions.get_session_rec(session_id) if session_id else None
    if rec is None or rec.connection_name is None:
        return _push_failed("not connected")
    perr = dashboard_params_error(params)
    if perr is not None:
        return _push_failed(perr)
    if name and await get_dashboard(name, (await _session_workspace_rec(session_id)).id) is None:
        return _push_failed(_NEW_NAME.format(kind="dashboard", name=name))
    pushed, persisted, message = await _push_dashboard(name or "", html, queries, session_id, params, rec.workspace)
    return _with_url(
        session_id,
        {
            "ok": pushed,
            "pushed": pushed,
            "persisted": persisted,
            "message": message,
            "database": await sessions.database_of(session_id),
        },
    )


# Agents edit saved entities or push unnamed drafts; only the user names one.
_NEW_NAME = 'no saved {kind} named "{name}"; omit `name` to push a draft the user names and saves'


def _failed(message: str) -> dict[str, Any]:
    return {"ok": False, "message": message, "database": None}


def _push_failed(message: str) -> dict[str, Any]:
    return {**_failed(message), "pushed": False, "persisted": False}


@mcp.tool()
async def new_tab(name: str, ctx: Context) -> dict[str, Any]:
    """A fresh QueryView session for your work and the link that shows it (see
    docs/mcp.md, "Tabs"). Open `url` in the user's browser yourself: `open
    <url>` on macOS, `xdg-open <url>` on Linux; otherwise give the user the
    link. The tab lists as "Agent › <name>", arms itself on load and is gone
    once closed. Connect it with use_connection or add_connection, then push
    into its `session_id`; a push made before the tab loads waits for it (a
    minute at most).

    Args:
        name: What the tab is for, e.g. "orders cleanup".

    Returns {"ok": True, "session_id", "url"} or {"ok": False, "message"}.
    """
    name = name.strip()
    if not name:
        return {"ok": False, "message": "name required"}
    rec = await sessions.create_tab(name)
    remote.open_pending(rec.id)
    _tab_urls[rec.id] = f"{_origin(ctx)}/?session={rec.id}"
    return {"ok": True, "session_id": rec.id, "url": _tab_urls[rec.id]}


# The link of each tab this process opened, so every reply about it can carry
# it: the agent can re-open or hand over a tab without keeping the link itself.
_tab_urls: dict[str, str] = {}


def _with_url(session_id: str, reply: dict[str, Any]) -> dict[str, Any]:
    url = _tab_urls.get(session_id)
    return {**reply, "url": url} if url else reply


def _origin(ctx: Context) -> str:
    """The scheme and host the MCP client reached us on, so the link it gets
    works from where it is."""
    request = ctx.request_context.request
    return f"{request.url.scheme}://{request.url.netloc}" if request is not None else ""


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
