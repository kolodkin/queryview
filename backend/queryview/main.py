"""FastAPI app: the JSON API under /api/*, the per-session cookie, and (when
SERVE_STATIC=1) serving the built SPA with an index.html fallback."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    StreamingResponse,
)

from . import gitsync, remote, sessions, workspaces, yamlio
from .connect import (
    _ensure_schema,
    connect_new,
    describe_query,
    disconnect,
    export_csv,
    get_session,
    list_connection_names,
    list_tables,
    open_saved,
    run_query,
    select_database,
)
from .dashboard_queries import run_queries_for_connection
from .dashboards import _upsert_and_push, get_dashboard, list_dashboards
from .drivers import DRIVERS
from .mcp_server import mcp
from .queries import list_predefined_queries_view, save_predefined_query
from .validation import cell_view_error, presentation_error

# SPA bundle shipped inside the wheel (release CI copies frontend/dist here);
# absent in a source checkout, where the repo's frontend/dist is used instead.
_PACKAGED_STATIC = Path(__file__).resolve().parent / "static"

# Opt-in in a source checkout; defaults on for an installed wheel (which ships
# its SPA bundle) so `pip install queryview` serves the UI out of the box.
SERVE_STATIC = os.environ.get("SERVE_STATIC", "1" if _PACKAGED_STATIC.is_dir() else "") == "1"


@lru_cache(maxsize=1)
def _static_root() -> Path:
    env = os.environ.get("STATIC_ROOT")
    if env:
        return Path(env).resolve()
    repo_dist = (Path(__file__).resolve().parent.parent.parent / "frontend" / "dist").resolve()
    if repo_dist.is_dir():
        return repo_dist
    return _PACKAGED_STATIC


async def _read_json(request: Request) -> Any:
    try:
        return await request.json()
    except Exception:
        return None


def _clean_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _clean_queries(raw: Any) -> dict[str, str]:
    """Keep only string→string entries with a non-empty name and SQL; ignore
    anything else so a malformed `queries` map can't reach the runner."""
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(k, str) and k and isinstance(v, str) and v.strip()}


def _parse_int(value: Any, default: int) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema to head before serving any request (single-process, no lock needed).
    await _ensure_schema()
    # A mounted sub-app's lifespan isn't run by the parent, so run the MCP session
    # manager here. streamable_http_app() (at mount, below) initializes
    # mcp.session_manager before this runs.
    async with mcp.session_manager.run():
        yield


app = FastAPI(title="queryview-backend", lifespan=lifespan)
app.mount("/mcp", mcp.streamable_http_app())


# The GET-only catch-all below suppresses Starlette's own /mcp -> /mcp/ redirect
# (see test_mcp_mount.py), so issue it explicitly. 307 preserves method and
# body; Streamable HTTP uses POST, GET and DELETE.
@app.api_route("/mcp", methods=["GET", "POST", "DELETE"], include_in_schema=False)
async def mcp_slash_redirect() -> RedirectResponse:
    return RedirectResponse("/mcp/", status_code=307)


@app.middleware("http")
async def session_header(request: Request, call_next):
    """Identify the session from the header the SPA sends. The `qv_session`
    cookie is still honored as a fallback while the frontend is migrated; it is
    removed once nothing depends on it."""
    request.state.sid = request.headers.get("X-QV-Session") or request.cookies.get("qv_session") or ""
    return await call_next(request)


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "queryview-backend"}


@app.get("/api/session")
async def session(request: Request) -> dict[str, Any]:
    return await get_session(request.state.sid)


def _session_payload(rec: sessions.SessionRec) -> dict[str, Any]:
    return {
        "id": rec.id,
        "label": sessions.display_label(rec),
        "pinned": rec.label is not None,
        "connection": rec.connection_name,
        "database": rec.database,
        "workspace": rec.workspace,
        "url": rec.url,
        "ui": rec.ui,
    }


# Resolve this tab's session: a refresh re-claims its own, a new tab resumes the
# last unheld session or gets a fresh one. Also serves as the claim heartbeat.
@app.post("/api/sessions/attach")
async def sessions_attach(request: Request):
    b = await _read_json(request) or {}
    tab = _clean_str(b.get("tab"))
    if not tab:
        return JSONResponse({"ok": False, "message": "tab is required"}, status_code=400)
    raw_id = _clean_str(b.get("session_id"))
    rec, created = await sessions.attach(tab, raw_id or None)
    return {"ok": True, "created": created, "session": _session_payload(rec)}


# Switch this tab to a specific session, or (id omitted/null) to a new one.
@app.post("/api/sessions/select")
async def sessions_select(request: Request):
    b = await _read_json(request) or {}
    tab = _clean_str(b.get("tab"))
    if not tab:
        return JSONResponse({"ok": False, "message": "tab is required"}, status_code=400)
    raw_id = _clean_str(b.get("id"))
    rec, message = await sessions.select_session(tab, raw_id or None)
    if rec is None:
        return JSONResponse({"ok": False, "message": message}, status_code=409)
    return {"ok": True, "session": _session_payload(rec)}


@app.get("/api/sessions")
async def sessions_list() -> dict[str, Any]:
    return {"sessions": await sessions.list_sessions()}


@app.patch("/api/sessions/{sid}")
async def sessions_patch(sid: str, request: Request):
    b = await _read_json(request) or {}
    ui = b.get("ui")
    ok = await sessions.patch_session(
        sid,
        url=b.get("url") if isinstance(b.get("url"), str) else None,
        ui=ui if isinstance(ui, dict) else None,
        label=b.get("label") if isinstance(b.get("label"), str) else None,
        workspace=b.get("workspace") if isinstance(b.get("workspace"), str) else None,
    )
    if not ok:
        return JSONResponse({"ok": False, "message": "unknown session"}, status_code=404)
    return {"ok": True}


@app.delete("/api/sessions/{sid}")
async def sessions_delete(sid: str):
    ok, message = await sessions.delete_session(sid)
    if not ok:
        status = 404 if message == "unknown session" else 409
        return JSONResponse({"ok": False, "message": message}, status_code=status)
    return {"ok": True}


# Sent by the pagehide beacon so a closed tab frees its session immediately
# rather than waiting out the claim TTL.
@app.post("/api/sessions/release")
async def sessions_release(request: Request):
    b = await _read_json(request) or {}
    tab = _clean_str(b.get("tab"))
    if tab:
        await sessions.release(tab)
    return {"ok": True}


# Drop this session's active connection (disconnect command).
@app.post("/api/db/disconnect")
async def db_disconnect(request: Request) -> dict[str, Any]:
    return await disconnect(request.state.sid)


# Saved connection names, for the `connect <name>` autocomplete.
@app.get("/api/db/connections")
async def db_connections() -> dict[str, Any]:
    return {"names": await list_connection_names()}


def _driver_and_config(body: Any):
    """Resolve (driver, config) from a request body's `type`, or the 400
    response to return for an unknown type / invalid config."""
    b = body if isinstance(body, dict) else {}
    raw_type = b.get("type")
    conn_type = raw_type if isinstance(raw_type, str) else ""
    driver = DRIVERS.get(conn_type)
    if driver is None:
        message = f"unknown connection type: {conn_type or '(none)'}"
        return JSONResponse({"ok": False, "message": message}, status_code=400)
    config, error = driver.parse_config(b)
    if error or config is None:
        return JSONResponse({"ok": False, "message": error}, status_code=400)
    return driver, config


# Test only: a throwaway connectivity check, no save, no activation.
@app.post("/api/db/test")
async def db_test(request: Request):
    resolved = _driver_and_config(await _read_json(request))
    if isinstance(resolved, JSONResponse):
        return resolved
    driver, config = resolved
    return await driver.test(config)


# Create + open a connection for this session.
@app.post("/api/db/connect")
async def db_connect(request: Request):
    body = await _read_json(request)
    resolved = _driver_and_config(body)
    if isinstance(resolved, JSONResponse):
        return resolved
    driver, config = resolved
    b = body if isinstance(body, dict) else {}
    raw_name = b.get("name")
    name = raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else driver.type
    return await connect_new(request.state.sid, name, config, driver.type)


# Open a saved connection by name for this session (connect <name>).
@app.post("/api/db/open")
async def db_open(request: Request):
    b = await _read_json(request) or {}
    raw_name = b.get("name") if isinstance(b, dict) else None
    name = raw_name.strip() if isinstance(raw_name, str) else ""
    if not name:
        return JSONResponse({"ok": False, "message": "name required"}, status_code=400)
    r = await open_saved(request.state.sid, name)
    if not r["ok"]:
        return JSONResponse(
            {"ok": False, "message": r["message"]},
            status_code=404 if r.get("not_found") else 200,
        )
    return {"ok": True, "name": r["name"], "type": r["type"], "databases": r["databases"]}


# Select this session's active connection's database.
@app.post("/api/db/database")
async def db_database(request: Request):
    b = await _read_json(request) or {}
    raw_db = b.get("database") if isinstance(b, dict) else None
    database = raw_db if isinstance(raw_db, str) else ""
    r = await select_database(request.state.sid, database)
    if not r["ok"]:
        return JSONResponse(
            {"ok": False, "message": r["message"]},
            status_code=409 if r["reason"] == "no-session" else 400,
        )
    return {"ok": True}


def _gate_error(r: dict[str, Any], reasons_409: tuple[str, ...]) -> JSONResponse:
    """Failed query/describe/tables result → response. Session-gate reasons in
    `reasons_409` map to 409; anything else (a driver error) stays 200."""
    status = 409 if r.get("reason") in reasons_409 else 200
    return JSONResponse({"ok": False, "message": r["message"]}, status_code=status)


# Run a SQL query (paginated) against this session's selected database.
@app.post("/api/db/query")
async def db_query(request: Request):
    body = await _read_json(request)
    b = body if isinstance(body, dict) else {}
    raw_sql = b.get("query")
    sql = raw_sql.strip() if isinstance(raw_sql, str) else ""
    if not sql:
        return JSONResponse({"ok": False, "message": "query required"}, status_code=400)
    limit = _parse_int(b.get("limit"), 100)
    limit = 100 if limit < 1 else min(limit, 1000)
    offset = _parse_int(b.get("offset"), 0)
    offset = 0 if offset < 0 else offset
    raw_order = b.get("order_by")
    order_by = raw_order if isinstance(raw_order, list) else None
    if b.get("format") == "csv":
        r = await export_csv(request.state.sid, sql, limit, offset, order_by)
        if not r["ok"]:
            return _gate_error(r, ("no-session",))
        return {"ok": True, "output": r["output"]}
    r = await run_query(request.state.sid, sql, limit, offset, order_by)
    if not r["ok"]:
        return _gate_error(r, ("no-session",))
    return {"ok": True, "meta": r["meta"], "data": r["data"]}


# Tables of this session's selected database (the Explorer page's sidebar).
@app.get("/api/db/tables")
async def db_tables(request: Request):
    r = await list_tables(request.state.sid)
    if not r["ok"]:
        return _gate_error(r, ("no-session", "no-database"))
    return {"ok": True, "tables": r["tables"]}


# Describe a query's output columns (name + type) without scanning data.
@app.post("/api/db/describe")
async def db_describe(request: Request):
    body = await _read_json(request)
    b = body if isinstance(body, dict) else {}
    raw_sql = b.get("query")
    sql = raw_sql.strip() if isinstance(raw_sql, str) else ""
    if not sql:
        return JSONResponse({"ok": False, "message": "query required"}, status_code=400)
    r = await describe_query(request.state.sid, sql)
    if not r["ok"]:
        return _gate_error(r, ("no-session", "no-database"))
    return {"ok": True, "fields": r["fields"]}


async def _resolve_workspace(raw: Any) -> workspaces.WorkspaceRec | JSONResponse:
    """The workspace for a request's optional `workspace` field (empty/missing
    means the default workspace), or the error response to return."""
    name = _clean_str(raw) or workspaces.DEFAULT_WORKSPACE
    try:
        return await workspaces.resolve(name)
    except workspaces.WorkspaceError as e:
        return JSONResponse({"ok": False, "message": str(e)}, status_code=e.status)


# Predefined queries: keyed by connection type within a workspace.
@app.get("/api/predefined-queries")
async def predefined_queries_list(request: Request):
    conn_type = request.query_params.get("type") or "clickhouse"
    ws = await _resolve_workspace(request.query_params.get("workspace"))
    if isinstance(ws, JSONResponse):
        return ws
    return {"queries": await list_predefined_queries_view(conn_type, ws.id)}


@app.post("/api/predefined-queries")
async def predefined_queries_save(request: Request):
    body = await _read_json(request)
    b = body if isinstance(body, dict) else {}
    name = b.get("query_name")
    conn_type = b.get("type")
    query = b.get("query")
    name = name.strip() if isinstance(name, str) else ""
    conn_type = conn_type.strip() if isinstance(conn_type, str) else ""
    query = query.strip() if isinstance(query, str) else ""
    if not name or not conn_type or not query:
        return JSONResponse(
            {"ok": False, "message": "query_name, type and query are required"},
            status_code=400,
        )
    raw_cv = b.get("cell_view")
    cverr = cell_view_error(raw_cv)
    if cverr is not None:
        return JSONResponse({"ok": False, "message": cverr}, status_code=400)
    # Store the raw YAML text verbatim; empty string => NULL (no custom views).
    cell_view = raw_cv if isinstance(raw_cv, str) and raw_cv.strip() else None
    order_by_arr = b.get("order_by")
    fields_arr = b.get("fields")
    perr = presentation_error(order_by_arr, fields_arr)
    if perr is not None:
        return JSONResponse({"ok": False, "message": perr}, status_code=400)
    import json

    order_by = json.dumps(order_by_arr) if isinstance(order_by_arr, list) and order_by_arr else None
    fields = json.dumps(fields_arr) if isinstance(fields_arr, list) and fields_arr else None
    ws = await _resolve_workspace(b.get("workspace"))
    if isinstance(ws, JSONResponse):
        return ws
    await save_predefined_query(name, conn_type, query, cell_view, order_by, fields, workspace_id=ws.id)
    return {"ok": True}


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
            yield _sse(msg.get("type", "query"), msg)
    finally:
        remote.unregister(remote_id)


# Open an SSE channel for this browser; the browser does this when the user
# arms "remote control". Closing the EventSource unregisters the channel.
@app.get("/api/remote/events")
async def remote_events(request: Request):
    remote_id = remote.register()
    return StreamingResponse(
        _event_stream(remote_id, request),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Push a query to a live session (used by the MCP tool and, in tests, directly).
@app.post("/api/remote/push")
async def remote_push(request: Request):
    body = await _read_json(request)
    b = body if isinstance(body, dict) else {}
    raw_sid = b.get("session_id")
    session_id = raw_sid.strip() if isinstance(raw_sid, str) else ""
    raw_sql = b.get("query")
    query = raw_sql.strip() if isinstance(raw_sql, str) else ""
    if not session_id or not query:
        return JSONResponse(
            {"ok": False, "message": "session_id and query are required"},
            status_code=400,
        )
    limit = _parse_int(b.get("limit"), 100)
    offset = _parse_int(b.get("offset"), 0)
    raw_cv = b.get("cell_view")
    cell_view = raw_cv if isinstance(raw_cv, str) and raw_cv.strip() else None
    raw_name = b.get("name")
    name = raw_name if isinstance(raw_name, str) and raw_name.strip() else None
    # Pass order_by/fields raw so remote.push's validator can reject malformed
    # input (fail-fast) rather than silently coercing it away.
    payload = {
        "type": "query",
        "query": query,
        "limit": limit,
        "offset": offset,
        "order_by": b.get("order_by"),
        "fields": b.get("fields"),
        "cell_view": cell_view,
        "name": name,
    }
    ok, message = remote.push(session_id, payload)
    return {"ok": ok, "message": message}


@app.post("/api/remote/db")
async def remote_db(request: Request):
    """Browser reports the database its live session targets, so the agent's
    push_query/push_dashboard responses can echo it. Called on arm and whenever
    the active database changes."""
    body = await _read_json(request)
    b = body if isinstance(body, dict) else {}
    raw_sid = b.get("session_id")
    session_id = raw_sid.strip() if isinstance(raw_sid, str) else ""
    raw_db = b.get("database")
    database = raw_db if isinstance(raw_db, str) and raw_db else None
    if not session_id:
        return JSONResponse({"ok": False, "message": "session_id required"}, status_code=400)
    ok = remote.set_session_database(session_id, database)
    if "workspace" in b:
        raw_ws = b.get("workspace")
        remote.set_session_workspace(session_id, raw_ws if isinstance(raw_ws, str) and raw_ws else None)
    return {"ok": ok}


@app.post("/api/remote/lock")
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


# Run a dashboard's named queries against a named connection. Fail-fast: any
# failure returns an HTTP error and no partial results.
@app.post("/api/runqueries")
async def run_queries(request: Request):
    body = await _read_json(request)
    b = body if isinstance(body, dict) else {}
    connection = _clean_str(b.get("connection"))
    queries = _clean_queries(b.get("queries"))
    if not connection or not queries:
        return JSONResponse(
            {"ok": False, "message": "connection and queries are required"},
            status_code=400,
        )
    r = await run_queries_for_connection(connection, queries)
    if not r["ok"]:
        status = 404 if r.get("reason") == "no-connection" else 400
        return JSONResponse({"ok": False, "message": r["message"]}, status_code=status)
    return {"ok": True, "results": r["results"]}


# Upsert a dashboard and (with a session_id) push it to a live browser session.
# REST mirror of the upsert_dashboard MCP tool.
@app.post("/api/dashboards")
async def dashboards_upsert(request: Request):
    body = await _read_json(request)
    b = body if isinstance(body, dict) else {}
    name = _clean_str(b.get("name"))
    connection = _clean_str(b.get("connection"))
    raw_html = b.get("html")
    html = raw_html if isinstance(raw_html, str) else ""
    queries = _clean_queries(b.get("queries"))
    if not name or not connection or not html.strip():
        return JSONResponse(
            {"ok": False, "message": "name, connection and html are required"},
            status_code=400,
        )
    ws = await _resolve_workspace(b.get("workspace"))
    if isinstance(ws, JSONResponse):
        return ws
    session_id = _clean_str(b.get("session_id"))
    persisted, pushed, message = await _upsert_and_push(
        name, connection, html, queries, session_id or None, workspace_id=ws.id
    )
    return {"ok": persisted, "persisted": persisted, "pushed": pushed, "message": message}


@app.get("/api/dashboards")
async def dashboards_list(request: Request):
    ws = await _resolve_workspace(request.query_params.get("workspace"))
    if isinstance(ws, JSONResponse):
        return ws
    return {"dashboards": await list_dashboards(ws.id)}


@app.get("/api/dashboards/{name}")
async def dashboards_get(name: str, request: Request):
    ws = await _resolve_workspace(request.query_params.get("workspace"))
    if isinstance(ws, JSONResponse):
        return ws
    d = await get_dashboard(name, ws.id)
    if d is None:
        return JSONResponse({"error": "not found"}, status_code=404)
    return d


# --- Git sync: per-entity backup/restore (see docs/gitsync.md) -------------


def _gitsync_args(kind: Any, name: Any, conn_type: Any) -> tuple[str, str, str | None] | JSONResponse:
    """Validated (kind, name, conn_type), or the 400 response to return,
    mirroring _driver_and_config's convention."""
    kind = _clean_str(kind)
    name = _clean_str(name)
    conn_type = _clean_str(conn_type)
    if kind not in ("query", "dashboard") or not name or (kind == "query" and not conn_type):
        return JSONResponse(
            {
                "ok": False,
                "message": "kind ('query'|'dashboard'), name and (for queries) conn_type are required",
            },
            status_code=400,
        )
    return kind, name, conn_type or None


async def _gitsync_json(coro):
    """Await a gitsync operation, mapping its result (or GitSyncError) to the
    endpoint response — the one place the /api/git error contract lives."""
    try:
        r = await coro
    except gitsync.GitSyncError as e:
        return JSONResponse({"ok": False, "message": str(e)}, status_code=e.status)
    return {"ok": True, **r}


@app.get("/api/git/status")
async def git_status(request: Request):
    ws = await _resolve_workspace(request.query_params.get("workspace"))
    if isinstance(ws, JSONResponse):
        return ws
    return {"configured": gitsync.configured(ws)}


@app.post("/api/git/store")
async def git_store(request: Request):
    body = await _read_json(request)
    b = body if isinstance(body, dict) else {}
    args = _gitsync_args(b.get("kind"), b.get("name"), b.get("conn_type"))
    if isinstance(args, JSONResponse):
        return args
    kind, name, conn_type = args
    ws = await _resolve_workspace(b.get("workspace"))
    if isinstance(ws, JSONResponse):
        return ws
    message = _clean_str(b.get("message")) or None
    return await _gitsync_json(gitsync.store(ws, kind, name, conn_type, message))


@app.get("/api/git/history")
async def git_history(request: Request):
    q = request.query_params
    args = _gitsync_args(q.get("kind"), q.get("name"), q.get("conn_type"))
    if isinstance(args, JSONResponse):
        return args
    kind, name, conn_type = args
    try:
        limit = max(1, min(int(q.get("limit") or 10), 100))
    except ValueError:
        limit = 10
    ws = await _resolve_workspace(q.get("workspace"))
    if isinstance(ws, JSONResponse):
        return ws
    return await _gitsync_json(gitsync.history(ws, kind, name, conn_type, q.get("before") or None, limit))


@app.post("/api/git/restore")
async def git_restore(request: Request):
    body = await _read_json(request)
    b = body if isinstance(body, dict) else {}
    args = _gitsync_args(b.get("kind"), b.get("name"), b.get("conn_type"))
    if isinstance(args, JSONResponse):
        return args
    kind, name, conn_type = args
    ws = await _resolve_workspace(b.get("workspace"))
    if isinstance(ws, JSONResponse):
        return ws
    return await _gitsync_json(gitsync.restore(ws, kind, name, conn_type, _clean_str(b.get("ref")) or None))


# --- YAML export / import (see docs/export-import.md) ----------------------


# Download one entity — or the whole workspace — as a self-describing YAML
# document (its `kind` field drives import, never the filename). Validation,
# dispatch and the download filename live in yamlio.export.
@app.get("/api/export")
async def export_yaml(request: Request):
    q = request.query_params
    ws = await _resolve_workspace(q.get("workspace"))
    if isinstance(ws, JSONResponse):
        return ws
    try:
        filename, text = await yamlio.export(
            _clean_str(q.get("kind")), _clean_str(q.get("name")), _clean_str(q.get("conn_type")), ws
        )
    except yamlio.YamlIOError as e:
        return JSONResponse({"ok": False, "message": str(e)}, status_code=e.status)
    return PlainTextResponse(
        text,
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# Import a YAML document (raw request body) into a workspace, upserting by
# name. The document's `kind` decides what gets written.
@app.post("/api/import")
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
        return JSONResponse({"ok": False, "message": str(e)}, status_code=e.status)
    return {"ok": True, **r}


# --- Workspaces (see docs/workspace.md) ------------------------------------
# Admin configuration with secrets (the remote URL may embed a token): exposed
# over REST/UI only, deliberately not over MCP.


def _workspace_error(e: workspaces.WorkspaceError) -> JSONResponse:
    return JSONResponse({"ok": False, "message": str(e)}, status_code=e.status)


@app.get("/api/workspaces")
async def workspaces_list():
    return {"workspaces": await workspaces.list_workspaces()}


@app.post("/api/workspaces")
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
        return _workspace_error(e)
    return {"ok": True}


@app.patch("/api/workspaces/{name}")
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
        await workspaces.update_workspace(name, **kwargs)
    except workspaces.WorkspaceError as e:
        return _workspace_error(e)
    return {"ok": True}


@app.delete("/api/workspaces/{name}")
async def workspaces_delete(name: str):
    try:
        await workspaces.delete_workspace(name)
    except workspaces.WorkspaceError as e:
        return _workspace_error(e)
    return {"ok": True}


@app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def api_not_found(rest: str):
    return JSONResponse({"error": "not found"}, status_code=404)


if SERVE_STATIC:

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        root = _static_root()
        candidate = (root / full_path).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            candidate = None
        if candidate is not None and candidate.is_file():
            return FileResponse(candidate)
        # SPA fallback: serve index.html (200) for any unknown path so
        # client-side routing works.
        return FileResponse(root / "index.html")

else:

    @app.get("/{full_path:path}")
    async def not_found(full_path: str):
        return JSONResponse({"error": "not found"}, status_code=404)


def _resolve_port(argv: list[str] | None = None) -> int:
    """Listen port: --port beats the PORT env var, which beats 8000."""
    import argparse

    parser = argparse.ArgumentParser(prog="queryview")
    parser.add_argument("--port", type=int, help="listen port (default: $PORT or 8000)")
    args = parser.parse_args(argv)
    if args.port is not None:
        return args.port
    return int(os.environ.get("PORT", "8000"))


def run() -> None:
    """Console-script entry point: launch uvicorn on the resolved port."""
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=_resolve_port())
