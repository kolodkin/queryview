"""The app: the JSON API under /api/*, the X-QV-Session header that names the
caller's session, and optionally the built frontend with an index.html
fallback. Nothing is built at import: create_app() assembles an app from the
routes here, and the entry point (__main__.py) names the factory it wants."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import (
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)

from . import gitsync, remote, sessions, workspaces, yamlio
from .connect import (
    _ensure_schema,
    connect_new,
    delete_connection,
    describe_query,
    disconnect,
    execute_script,
    export_csv,
    get_session,
    list_connections_for,
    list_tables,
    lock_connection,
    open_saved,
    parse_driver_config,
    refresh_databases,
    remove_lock,
    request_token,
    run_query,
    saved_config,
    select_database,
    session_settings,
    unlock_connection,
)
from .dashboard_entries import MIXED, clean_queries, is_federated
from .dashboard_queries import (
    LookupError_,
    Target,
    clean_values,
    dialect_of,
    ready_sql,
    resolved_part,
    run_dashboard,
    run_dashboard_queries,
    session_lookup,
    session_sql,
)
from .dashboards import get_dashboard, list_dashboards
from .drivers import DRIVERS
from .drivers.base import Err
from .drivers.clickhouse import close_client
from .mcp_server import mcp
from .serving import serve_static
from .validation import dashboard_params_dropped, dashboard_params_error, page_bounds


async def _read_json(request: Request) -> Any:
    try:
        return await request.json()
    except Exception:
        return None


def _clean_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _status_error(
    e: workspaces.WorkspaceError | gitsync.GitSyncError | yamlio.YamlIOError | sessions.ReservedLabelError,
) -> JSONResponse:
    """The `{ok: false, message}` response for a domain error carrying its HTTP status."""
    return JSONResponse({"ok": False, "message": str(e)}, status_code=e.status)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema to head before serving any request (single-process, no lock needed).
    await _ensure_schema()
    # A mounted sub-app's lifespan isn't run by the parent, so run the MCP session
    # manager here. streamable_http_app() (at mount, in create_app) initializes
    # mcp.session_manager before this runs.
    async with mcp.session_manager.run():
        try:
            yield
        finally:
            await close_client()


# Every route, registered once at import; create_app() puts them on an app.
router = APIRouter()


# The frontend's GET-only catch-all suppresses Starlette's own /mcp -> /mcp/
# redirect (see test_mcp_mount.py), so issue it explicitly. 307 preserves method and
# body; Streamable HTTP uses POST, GET and DELETE.
@router.api_route("/mcp", methods=["GET", "POST", "DELETE"], include_in_schema=False)
async def mcp_slash_redirect() -> RedirectResponse:
    return RedirectResponse("/mcp/", status_code=307)


async def session_header(request: Request, call_next):
    """Identify the session from the header the SPA sends on every /api call.
    There is no cookie: a session is named by its id, not by the browser."""
    request.state.sid = request.headers.get("X-QV-Session") or ""
    # The unlock token for a locked connection (docs/user_guide/connect.md#locked-connections).
    request_token.set(request.headers.get("X-QV-Token"))
    return await call_next(request)


@router.get("/api/health")
async def health() -> dict[str, Any]:
    # `scratch`: the e2e suite refuses a backend on the default data dir.
    return {"status": "ok", "service": "queryview-backend", "scratch": bool(os.environ.get("DATA_DIR"))}


@router.get("/api/session")
async def session(request: Request) -> dict[str, Any]:
    return await get_session(request.state.sid)


_SESSION_ERRORS = {
    "unknown": (404, "unknown session"),
    "held": (409, "session is open in another tab"),
    "taken": (409, "session was taken by another tab"),
}


def _session_error(reason: str) -> JSONResponse:
    """A session store reason code as a response. The store returns codes, not
    prose, so rewording a message cannot silently change an HTTP status."""
    status, message = _SESSION_ERRORS.get(reason, (409, reason or "cannot do that"))
    return JSONResponse({"ok": False, "message": message}, status_code=status)


def _str_or_none(body: dict[str, Any], key: str) -> str | None:
    """A string field of a patch body, or None when absent. Unlike `_clean_str`
    an empty string is kept: that is how a label unpins."""
    value = body.get(key)
    return value if isinstance(value, str) else None


def _session_payload(rec: sessions.SessionRec) -> dict[str, Any]:
    return {
        "id": rec.id,
        "label": sessions.display_label(rec),
        "pinned": rec.label is not None,
        "connection": rec.connection_name,
        "connection_by": rec.connection_by,
        "database": rec.database,
        "workspace": rec.workspace,
        "url": rec.url,
        "ui": rec.ui,
        "tab": rec.tab,
    }


# Resolve and claim this tab's session (see sessions.attach); doubles as the
# claim heartbeat.
@router.post("/api/sessions/attach")
async def sessions_attach(request: Request):
    b = await _read_json(request) or {}
    tab = _clean_str(b.get("tab"))
    if not tab:
        return JSONResponse({"ok": False, "message": "tab is required"}, status_code=400)
    raw_id = _clean_str(b.get("session_id"))
    try:
        rec, created = await sessions.attach(tab, raw_id or None, keep=b.get("keep") is True)
    except sessions.SessionTaken:
        return _session_error("taken")
    return {"ok": True, "created": created, "session": _session_payload(rec)}


# Switch this tab to a specific session, or (id omitted/null) to a new one.
@router.post("/api/sessions/select")
async def sessions_select(request: Request):
    b = await _read_json(request) or {}
    tab = _clean_str(b.get("tab"))
    if not tab:
        return JSONResponse({"ok": False, "message": "tab is required"}, status_code=400)
    raw_id = _clean_str(b.get("id"))
    rec, reason = await sessions.select_session(tab, raw_id or None, force=b.get("force") is True)
    if rec is None:
        return _session_error(reason)
    return {"ok": True, "session": _session_payload(rec)}


@router.get("/api/sessions")
async def sessions_list() -> dict[str, Any]:
    return {"sessions": await sessions.list_sessions()}


@router.patch("/api/sessions/{sid}")
async def sessions_patch(sid: str, request: Request):
    b = await _read_json(request) or {}
    ui = b.get("ui")
    try:
        rec = await sessions.patch_session(
            sid,
            url=_str_or_none(b, "url"),
            ui=ui if isinstance(ui, dict) else None,
            label=_str_or_none(b, "label"),
            workspace=_str_or_none(b, "workspace"),
            table=_str_or_none(b, "table"),
        )
    except sessions.ReservedLabelError as e:
        return _status_error(e)
    if rec is None:
        return JSONResponse({"ok": False, "message": "unknown session"}, status_code=404)
    return {"ok": True, "session": _session_payload(rec)}


@router.delete("/api/sessions/{sid}")
async def sessions_delete(sid: str):
    ok, reason = await sessions.delete_session(sid)
    if not ok:
        return _session_error(reason)
    return {"ok": True}


# The pagehide beacon: apply whatever the tab had not flushed yet, then free its
# claim rather than waiting out the TTL. A reload fires pagehide, so this is what
# keeps a change made inside the client's debounce window.
@router.post("/api/sessions/release")
async def sessions_release(request: Request):
    b = await _read_json(request) or {}
    tab = _clean_str(b.get("tab"))
    if not tab:
        return {"ok": True}
    sid = _clean_str(b.get("session_id"))
    if sid:
        ui = b.get("ui")
        # No label: a rename is its own PATCH, never part of the beacon.
        await sessions.patch_session(
            sid,
            url=_str_or_none(b, "url"),
            ui=ui if isinstance(ui, dict) else None,
            workspace=_str_or_none(b, "workspace"),
        )
    await sessions.release(tab)
    return {"ok": True}


# Drop this session's active connection (disconnect command).
@router.post("/api/db/disconnect")
async def db_disconnect(request: Request) -> dict[str, Any]:
    return await disconnect(request.state.sid)


# This session's connections and the saved ones, for the Connect page's cards.
@router.get("/api/db/connections")
async def db_connections(request: Request) -> dict[str, Any]:
    return {"connections": await list_connections_for(request.state.sid)}


def _driver_and_config(body: Any):
    """Resolve (driver, config) from a request body's `type`, or the 400
    response to return for an unknown type / invalid config."""
    conn_type, config, error = parse_driver_config(body if isinstance(body, dict) else {})
    if error or config is None:
        return JSONResponse({"ok": False, "message": error}, status_code=400)
    return DRIVERS[conn_type], config


# Test only: a throwaway connectivity check, no save, no activation.
@router.post("/api/db/test")
async def db_test(request: Request):
    resolved = _driver_and_config(await _read_json(request))
    if isinstance(resolved, JSONResponse):
        return resolved
    driver, config = resolved
    await session_settings(request.state.sid)  # the probe runs within the session's query timeout
    return await driver.test(config)


# Create + open a connection for this session.
@router.post("/api/db/connect")
async def db_connect(request: Request):
    body = await _read_json(request)
    resolved = _driver_and_config(body)
    if isinstance(resolved, JSONResponse):
        return resolved
    driver, config = resolved
    b = body if isinstance(body, dict) else {}
    raw_name = b.get("name")
    name = raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else driver.type
    r = await connect_new(request.state.sid, name, config, driver.type, session_only=b.get("session") is True)
    return r if r["ok"] else _gate_error(r, ())


# Open a saved connection by name for this session (a Connect page card).
@router.post("/api/db/open")
async def db_open(request: Request):
    b = await _read_json(request) or {}
    raw_name = b.get("name") if isinstance(b, dict) else None
    name = raw_name.strip() if isinstance(raw_name, str) else ""
    if not name:
        return JSONResponse({"ok": False, "message": "name required"}, status_code=400)
    r = await open_saved(request.state.sid, name)
    if not r["ok"]:
        return JSONResponse({"ok": False, "message": r["message"]}, status_code=404 if r.get("not_found") else 200)
    # The full session state: a locked connection lands with `unlocked` so the
    # tab knows to ask for the passphrase.
    return {"ok": True, **await get_session(request.state.sid)}


def _lock_body(body: Any) -> tuple[str, str]:
    b = body if isinstance(body, dict) else {}
    passphrase = b.get("passphrase")
    return _clean_str(b.get("name")), passphrase if isinstance(passphrase, str) else ""


# Lock a saved connection behind a passphrase; this tab gets its unlock token.
@router.post("/api/db/lock")
async def db_lock(request: Request):
    name, passphrase = _lock_body(await _read_json(request))
    r = await lock_connection(request.state.sid, name, passphrase)
    return r if r["ok"] else _gate_error(r, (), default=400)


# Remove a lock, given its passphrase.
@router.delete("/api/db/lock")
async def db_lock_remove(request: Request):
    name, passphrase = _lock_body(await _read_json(request))
    r = await remove_lock(name, passphrase)
    return r if r["ok"] else _gate_error(r, (), default=400)


# Exchange a locked connection's passphrase for this tab's unlock token.
@router.post("/api/db/unlock")
async def db_unlock(request: Request):
    name, passphrase = _lock_body(await _read_json(request))
    r = await unlock_connection(request.state.sid, name, passphrase)
    return r if r["ok"] else _gate_error(r, (), default=400)


# A saved connection's config for the edit form, password blanked.
@router.get("/api/db/connections/{name:path}")
async def db_connection(name: str, request: Request):
    r = await saved_config(request.state.sid, name)
    return r if r["ok"] else _gate_error(r, (), default=404 if r.get("not_found") else 400)


# Delete a connection; a locked one takes its passphrase.
@router.delete("/api/db/connections")
async def db_connection_delete(request: Request):
    name, passphrase = _lock_body(await _read_json(request))
    r = await delete_connection(request.state.sid, name, passphrase)
    return r if r["ok"] else _gate_error(r, (), default=404 if r.get("not_found") else 400)


# Re-list this session's connection's databases, refreshing the cached list.
@router.get("/api/db/databases")
async def db_databases(request: Request):
    r = await refresh_databases(request.state.sid)
    return r if r["ok"] else _gate_error(r, ("no-session",))


# Select this session's active connection's database.
@router.post("/api/db/database")
async def db_database(request: Request):
    b = await _read_json(request) or {}
    raw_db = b.get("database") if isinstance(b, dict) else None
    database = raw_db if isinstance(raw_db, str) else ""
    r = await select_database(request.state.sid, database)
    if not r["ok"]:
        return _gate_error(r, ("no-session",), default=400)
    return r


def _gate_error(r: dict[str, Any], reasons_409: tuple[str, ...], default: int = 200) -> JSONResponse:
    """Failed query/describe/tables result → response. A locked connection is
    403, session-gate reasons in `reasons_409` 409; anything else (a driver
    error) stays `default`."""
    reason = r.get("reason")
    status = 403 if reason == "locked" else 409 if reason in reasons_409 else default
    return JSONResponse({"ok": False, "message": r["message"]}, status_code=status)


async def _with_params(
    request: Request, b: dict[str, Any], sql: str, reasons_409: tuple[str, ...]
) -> tuple[str, JSONResponse | None]:
    """A dashboard widget's query: with `params` in the body, `sql` is a
    template and `values` are substituted here (docs/user_guide/dashboard.md#dashboard-parameters).
    Returns the SQL to run, or the failed response."""
    if "params" not in b:
        return sql, None
    ready, err = await session_sql(request.state.sid, sql, b["params"], clean_values(b.get("values")))
    if ready is not None:
        return ready, None
    assert err is not None
    return sql, _gate_error(err, reasons_409, default=400 if err.get("reason") == "params" else 200)


async def _on_connection(request: Request, b: dict[str, Any], sql: str) -> tuple[Target, str] | JSONResponse:
    """A federated widget's query: the target its `connection` and `database`
    name (docs/designs/dashboards.md — "Which connection, which database")
    and the SQL with any `values` substituted, or the failed response."""
    database = b.get("database")
    t = await session_lookup(request.state.sid)(b["connection"], database if isinstance(database, str) else None)
    if isinstance(t, LookupError_):
        return JSONResponse({"ok": False, "reason": "query", "message": t.message}, status_code=400)
    if "params" not in b:
        return t, sql
    ready, why = ready_sql(sql, b["params"], clean_values(b.get("values")), dialect_of(t.driver))
    if ready is None:
        return JSONResponse({"ok": False, "message": why, "reason": "params"}, status_code=400)
    return t, ready


# Run a SQL query (paginated) against this session's selected database, or a named connection.
@router.post("/api/db/query")
async def db_query(request: Request):
    body = await _read_json(request)
    b = body if isinstance(body, dict) else {}
    raw_sql = b.get("query")
    sql = raw_sql.strip() if isinstance(raw_sql, str) else ""
    if not sql:
        return JSONResponse({"ok": False, "message": "query required"}, status_code=400)
    limit, offset = page_bounds(b.get("limit"), b.get("offset"))
    raw_order = b.get("order_by")
    order_by = raw_order if isinstance(raw_order, list) else None
    if isinstance(b.get("connection"), str):
        on = await _on_connection(request, b, sql)
        if isinstance(on, JSONResponse):
            return on
        t, sql = on
        if b.get("format") == "csv":
            csv = await t.driver.export_csv(t.config, sql, t.database, limit, offset, order_by)
            return {"ok": False, "message": csv.message} if isinstance(csv, Err) else {"ok": True, "output": csv.text}
        rows = await t.driver.run_query(t.config, sql, t.database, limit, offset, order_by)
        if isinstance(rows, Err):
            return {"ok": False, "message": rows.message}
        return {"ok": True, "meta": [c._asdict() for c in rows.rows.meta], "data": rows.rows.data}
    sql, failed = await _with_params(request, b, sql, ("no-session",))
    if failed is not None:
        return failed
    if b.get("format") == "csv":
        r = await export_csv(request.state.sid, sql, limit, offset, order_by)
        if not r["ok"]:
            return _gate_error(r, ("no-session",))
        return {"ok": True, "output": r["output"]}
    r = await run_query(request.state.sid, sql, limit, offset, order_by)
    if not r["ok"]:
        return _gate_error(r, ("no-session",))
    return {"ok": True, "meta": r["meta"], "data": r["data"]}


# Run a script as written, one result per statement (the Scripts page).
@router.post("/api/db/execute")
async def db_execute(request: Request):
    body = await _read_json(request)
    b = body if isinstance(body, dict) else {}
    sql = _clean_str(b.get("sql"))
    if not sql:
        return JSONResponse({"ok": False, "message": "sql required"}, status_code=400)
    r = await execute_script(request.state.sid, sql)
    if not r["ok"]:
        return _gate_error(r, ("no-session", "no-database"))
    return r


# Tables of this session's selected database (the Explorer page's sidebar).
@router.get("/api/db/tables")
async def db_tables(request: Request):
    r = await list_tables(request.state.sid, union=request.query_params.get("union") == "1")
    if not r["ok"]:
        return _gate_error(r, ("no-session", "no-database"))
    return r


# Describe a query's output columns (name + type) without scanning data.
@router.post("/api/db/describe")
async def db_describe(request: Request):
    body = await _read_json(request)
    b = body if isinstance(body, dict) else {}
    raw_sql = b.get("query")
    sql = raw_sql.strip() if isinstance(raw_sql, str) else ""
    if not sql:
        return JSONResponse({"ok": False, "message": "query required"}, status_code=400)
    if isinstance(b.get("connection"), str):
        on = await _on_connection(request, b, sql)
        if isinstance(on, JSONResponse):
            return on
        t, sql = on
        d = await t.driver.describe_query(t.config, sql, t.database)
        return {"ok": False, "message": d.message} if isinstance(d, Err) else {"ok": True, "fields": d.fields}
    sql, failed = await _with_params(request, b, sql, ("no-session", "no-database"))
    if failed is not None:
        return failed
    r = await describe_query(request.state.sid, sql)
    if not r["ok"]:
        return _gate_error(r, ("no-session", "no-database"))
    return {"ok": True, "fields": r["fields"]}


async def _resolve_workspace(raw: Any) -> workspaces.WorkspaceRec | JSONResponse:
    """The workspace for a request's optional `workspace` field (empty/missing
    means the fallback workspace), or the error response to return."""
    name = _clean_str(raw)
    try:
        return await (workspaces.resolve(name) if name else workspaces.fallback())
    except workspaces.WorkspaceError as e:
        return _status_error(e)


# --- Remote control (MCP push -> live browser session) --------------------

_SSE_POLL_SECONDS = 1.0
_SSE_HEARTBEAT_SECONDS = 15.0


def _sse(event: str, data: dict[str, Any]) -> bytes:
    import json

    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


async def _event_stream(remote_id: str, request: Request):
    """Yield SSE: a `ready` event with the id, then pushed payloads (each under the
    SSE event named by its `type` field) plus a heartbeat. Polls disconnect every
    second so disarming (the browser closing the EventSource) unregisters the
    channel promptly."""
    try:
        yield _sse("ready", {"id": remote_id})
        elapsed = 0.0
        while True:
            if await request.is_disconnected():
                break
            msg = await remote.next_message(remote_id, _SSE_POLL_SECONDS)
            if msg is None:
                elapsed += _SSE_POLL_SECONDS
                if elapsed >= _SSE_HEARTBEAT_SECONDS:
                    elapsed = 0.0
                    yield b": ping\n\n"
                continue
            yield _sse(msg.get("type", "message"), msg)
    finally:
        remote.unregister(remote_id)


# Open an SSE channel for this browser; the browser does this when the user
# arms "remote control". Closing the EventSource unregisters the channel.
@router.get("/api/remote/events")
async def remote_events(request: Request):
    # EventSource cannot send headers, so the browser passes its session id in
    # the query string; other callers still identify by header.
    remote_id = remote.register(request.query_params.get("session") or request.state.sid)
    return StreamingResponse(
        _event_stream(remote_id, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/remote/lock")
async def remote_lock(request: Request):
    """Browser-only edit-lock control for a live session. action=acquire is sent
    on panel focus (and as a ~10s heartbeat); action=release on blur. Owner is
    always 'human' — the agent never calls this."""
    body = await _read_json(request)
    b = body if isinstance(body, dict) else {}
    raw_sid = b.get("session_id")
    session_id = raw_sid.strip() if isinstance(raw_sid, str) else ""
    action = b.get("action")
    if not session_id or action not in ("acquire", "release"):
        return JSONResponse(
            {"ok": False, "message": "session_id and action (acquire|release) required"},
            status_code=400,
        )
    if action == "acquire":
        ok, message = remote.acquire(session_id, "human")
    else:
        ok, message = remote.release(session_id, "human")
    return {"ok": ok, "message": message}


# --- Dashboards (persist + reopen + run-against-a-named-connection) --------


# Run a dashboard's named queries on this session's connection and selected
# database, or a federated one's on the connections they name. Fail-fast: any
# failure returns an HTTP error and no partial results.
@router.post("/api/runqueries")
async def run_queries(request: Request):
    body = await _read_json(request)
    b = body if isinstance(body, dict) else {}
    queries = clean_queries(b.get("queries"))
    # With `params` the queries are templates, substituted here; a dashboard of
    # widgets alone sends none and still gets its selectors resolved.
    with_params = "params" in b
    if not queries and not with_params:
        return JSONResponse({"ok": False, "message": "queries are required"}, status_code=400)
    if with_params:
        r = await run_dashboard(request.state.sid, queries, b["params"], clean_values(b.get("values")))
    else:
        r = await run_dashboard_queries(request.state.sid, queries)
    resolved = resolved_part(r)
    if "connections" in r:
        resolved["connections"] = r["connections"]
    # Reading drops a malformed param rather than refuse the dashboard; say which, as saving would.
    dropped = dashboard_params_dropped(b["params"]) if with_params else []
    if dropped:
        resolved["warning"] = "; ".join(dropped)
    if not r["ok"]:
        # Not connected / no database: the session must act first, not the request.
        status = 400 if r.get("reason") in ("query", "params") else 409
        return JSONResponse(
            {"ok": False, "message": r["message"], "reason": r.get("reason"), **resolved}, status_code=status
        )
    return {"ok": True, "results": r["results"], **resolved}


# The user's Save: upsert a dashboard (in a synced workspace also one commit,
# docs/user_guide/gitsync.md) and, with a session_id, push it to a live browser session.
@router.post("/api/dashboards")
async def dashboards_upsert(request: Request):
    body = await _read_json(request)
    b = body if isinstance(body, dict) else {}
    name = _clean_str(b.get("name"))
    raw_html = b.get("html")
    html = raw_html if isinstance(raw_html, str) else ""
    queries = clean_queries(b.get("queries"))
    if not name or not html.strip():
        return JSONResponse({"ok": False, "message": "name and html are required"}, status_code=400)
    params = b.get("params")
    perr = dashboard_params_error(params)
    if perr is not None:
        return JSONResponse({"ok": False, "message": perr}, status_code=400)
    try:
        is_federated(queries, params)
    except ValueError:
        return JSONResponse({"ok": False, "message": MIXED}, status_code=400)
    ws = await _resolve_workspace(b.get("workspace"))
    if isinstance(ws, JSONResponse):
        return ws
    session_id = _clean_str(b.get("session_id"))
    try:
        pushed, committed, message = await gitsync.save_and_push(ws, name, html, queries, session_id or None, params)
    except gitsync.GitSyncError as e:
        return _status_error(e)
    return {"ok": True, "persisted": True, "pushed": pushed, "committed": committed, "message": message}


@router.get("/api/dashboards")
async def dashboards_list(request: Request):
    ws = await _resolve_workspace(request.query_params.get("workspace"))
    if isinstance(ws, JSONResponse):
        return ws
    return {"dashboards": await list_dashboards(ws.id)}


@router.get("/api/dashboards/{name:path}")
async def dashboards_get(name: str, request: Request):
    ws = await _resolve_workspace(request.query_params.get("workspace"))
    if isinstance(ws, JSONResponse):
        return ws
    d = await get_dashboard(name, ws.id)
    if d is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return d


# Rename / Delete: a user action, one commit in a synced workspace (docs/user_guide/gitsync.md).
# `:path`: a name may contain "/", which arrives decoded.
@router.post("/api/dashboards/{name:path}/rename")
async def dashboards_rename(name: str, request: Request):
    body = await _read_json(request)
    b = body if isinstance(body, dict) else {}
    new_name = _clean_str(b.get("new_name"))
    if not new_name:
        return JSONResponse({"ok": False, "message": "new_name is required"}, status_code=400)
    ws = await _resolve_workspace(b.get("workspace"))
    if isinstance(ws, JSONResponse):
        return ws
    return await _gitsync_json(gitsync.rename(ws, name, new_name))


@router.delete("/api/dashboards/{name:path}")
async def dashboards_delete(name: str, request: Request):
    ws = await _resolve_workspace(request.query_params.get("workspace"))
    if isinstance(ws, JSONResponse):
        return ws
    return await _gitsync_json(gitsync.delete(ws, name))


# --- Git sync: per-entity backup/restore (see docs/user_guide/gitsync.md) -------------


def _gitsync_args(kind: Any, name: Any) -> tuple[str, str] | JSONResponse:
    """Present (kind, name), or the 400 response to return, mirroring
    _driver_and_config's convention. Which kinds exist is gitsync's call."""
    kind = _clean_str(kind)
    name = _clean_str(name)
    if not kind or not name:
        return JSONResponse({"ok": False, "message": "kind and name are required"}, status_code=400)
    return kind, name


async def _gitsync_json(coro):
    """Await a gitsync operation, mapping its result (or GitSyncError) to the
    endpoint response — the one place the /api/git error contract lives."""
    try:
        r = await coro
    except gitsync.GitSyncError as e:
        return _status_error(e)
    return {"ok": True, **r}


@router.get("/api/git/status")
async def git_status(request: Request):
    ws = await _resolve_workspace(request.query_params.get("workspace"))
    if isinstance(ws, JSONResponse):
        return ws
    return {"configured": gitsync.configured(ws), "conflicts": gitsync.conflicts(ws)}


# The workspace panel's Sync: merge in what was committed elsewhere.
@router.post("/api/git/sync")
async def git_sync(request: Request):
    b = await _read_json(request)
    b = b if isinstance(b, dict) else {}
    ws = await _resolve_workspace(_clean_str(b.get("workspace")) or None)
    if isinstance(ws, JSONResponse):
        return ws
    return await _gitsync_json(gitsync.sync(ws))


async def _sync_attached(name: str) -> dict[str, Any]:
    """Merge a just-attached remote in. The workspace is saved either way, so a
    sync failure (unreachable remote) is reported, not raised."""
    try:
        return {"sync": await gitsync.sync(await workspaces.resolve(name))}
    except (gitsync.GitSyncError, workspaces.WorkspaceError) as e:
        return {"sync_error": str(e)}


@router.get("/api/git/history")
async def git_history(request: Request):
    q = request.query_params
    args = _gitsync_args(q.get("kind"), q.get("name"))
    if isinstance(args, JSONResponse):
        return args
    kind, name = args
    try:
        limit = max(1, min(int(q.get("limit") or 10), 100))
    except ValueError:
        limit = 10
    ws = await _resolve_workspace(q.get("workspace"))
    if isinstance(ws, JSONResponse):
        return ws
    return await _gitsync_json(gitsync.history(ws, kind, name, q.get("before") or None, limit))


@router.post("/api/git/restore")
async def git_restore(request: Request):
    body = await _read_json(request)
    b = body if isinstance(body, dict) else {}
    args = _gitsync_args(b.get("kind"), b.get("name"))
    if isinstance(args, JSONResponse):
        return args
    kind, name = args
    ws = await _resolve_workspace(b.get("workspace"))
    if isinstance(ws, JSONResponse):
        return ws
    return await _gitsync_json(gitsync.restore(ws, kind, name, _clean_str(b.get("ref")) or None))


# --- YAML export / import (see docs/user_guide/export-import.md) ----------------------


# Download one entity — or the whole workspace — as a self-describing YAML
# document (its `kind` field drives import, never the filename). Validation,
# dispatch and the download filename live in yamlio.export.
@router.get("/api/export")
async def export_yaml(request: Request):
    q = request.query_params
    ws = await _resolve_workspace(q.get("workspace"))
    if isinstance(ws, JSONResponse):
        return ws
    try:
        filename, text = await yamlio.export(_clean_str(q.get("kind")), _clean_str(q.get("name")), ws)
    except yamlio.YamlIOError as e:
        return _status_error(e)
    return PlainTextResponse(
        text,
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Import a YAML document (raw request body) into a workspace, upserting by
# name. The document's `kind` decides what gets written.
@router.post("/api/import")
async def import_yaml(request: Request):
    ws = await _resolve_workspace(request.query_params.get("workspace"))
    if isinstance(ws, JSONResponse):
        return ws
    text = (await request.body()).decode("utf-8", "replace")
    if not text.strip():
        return JSONResponse({"ok": False, "message": "YAML body required"}, status_code=400)
    try:
        r = await yamlio.import_text(text, ws.id)
    except yamlio.YamlIOError as e:
        return _status_error(e)
    return {"ok": True, **r}


# --- Workspaces (see docs/user_guide/workspace.md) ------------------------------------
# Admin configuration with secrets (the remote URL may embed a token): exposed
# over REST/UI only, deliberately not over MCP.


@router.get("/api/workspaces")
async def workspaces_list():
    return {"workspaces": await workspaces.list_workspaces()}


@router.post("/api/workspaces")
async def workspaces_create(request: Request):
    b = await _read_json(request)
    b = b if isinstance(b, dict) else {}
    name = _clean_str(b.get("name"))
    if not name:
        return JSONResponse({"ok": False, "message": "name is required"}, status_code=400)
    remote_url = _clean_str(b.get("remote")) or None
    branch = _clean_str(b.get("branch")) or "main"
    try:
        await workspaces.create_workspace(name, remote_url, branch)
    except workspaces.WorkspaceError as e:
        return _status_error(e)
    return {"ok": True, **(await _sync_attached(name) if remote_url else {})}


@router.patch("/api/workspaces/{name}")
async def workspaces_update(name: str, request: Request):
    b = await _read_json(request)
    b = b if isinstance(b, dict) else {}
    kwargs: dict[str, Any] = {}
    if "name" in b:
        kwargs["new_name"] = _clean_str(b.get("name")) or None
    if "remote" in b:  # present-but-null clears; absent leaves as-is
        kwargs["remote"] = _clean_str(b.get("remote")) or None
    if "branch" in b:
        kwargs["branch"] = _clean_str(b.get("branch")) or None
    try:
        before = await workspaces.resolve(name)
        await workspaces.update_workspace(name, **kwargs)
    except workspaces.WorkspaceError as e:
        return _status_error(e)
    current = kwargs.get("new_name") or name
    after = await workspaces.resolve(current)
    changed = (after.remote, after.branch) != (before.remote, before.branch)
    if changed:
        # A different repo: the old clone and sync state no longer apply.
        gitsync.forget(before.id)
    # Entering a remote (even the same one again) merges whatever it holds.
    if after.remote and (changed or kwargs.get("remote")):
        return {"ok": True, **(await _sync_attached(current))}
    return {"ok": True}


@router.delete("/api/workspaces/{name}")
async def workspaces_delete(name: str):
    try:
        ws = await workspaces.resolve(name)
        moved_to = await workspaces.delete_workspace(name)
    except workspaces.WorkspaceError as e:
        return _status_error(e)
    gitsync.forget(ws.id)
    # Sessions that were on it now are on this one.
    return {"ok": True, "workspace": moved_to}


@router.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def api_not_found(rest: str):
    return JSONResponse({"error": "not found"}, status_code=404)


async def spa(full_path: str, v: str | None = None):
    """The built frontend: a file, or the app's page for a client-side route."""
    return await serve_static(full_path, v is not None)


def create_app(frontend: bool = True) -> FastAPI:
    """The app: the API, the MCP endpoint and, with `frontend`, the built
    frontend on every other path. Without it (the API beside a dev server) a
    non-API path is a plain 404."""
    app = FastAPI(title="queryview-backend", lifespan=lifespan)
    app.mount("/mcp", mcp.streamable_http_app(streamable_http_path="/", stateless_http=True))
    app.middleware("http")(session_header)
    app.include_router(router)
    if frontend:
        # Last: it matches every path the routes above did not.
        app.add_api_route("/{full_path:path}", spa, methods=["GET"])
    return app


def create_api_app() -> FastAPI:
    """create_app without the frontend, as a name uvicorn can import: a
    reloading server re-imports its app by name, and a name carries no argument."""
    return create_app(frontend=False)
