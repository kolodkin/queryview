"""The viewer server: a display-only deployment that shows a git repo's
dashboards on the connections of a config file. See docs/viewer_server.

A separate app from queryview.app, so what a viewer must not reach — saving,
connecting, running SQL of their own, MCP — is not switched off but absent.
The browser sends names and parameter values; the SQL stays here."""

from __future__ import annotations

import asyncio
import logging
import sys
from contextlib import asynccontextmanager, suppress
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from ..dashboard_params import ParamError, needed, parse_params
from ..dashboard_queries import (
    WAITING,
    clean_values,
    dialect_of,
    ready_sql,
    resolve_on,
    resolved_part,
    run_dashboard_on,
)
from ..drivers import DRIVERS
from ..drivers.base import Err
from ..drivers.clickhouse import close_client
from ..gitsync import GitSyncError
from ..serving import resolve_port, serve_static
from ..validation import page_bounds
from .config import ConfigError, Connection, ServerConfig, config_path, load_config
from .repo import Repo

log = logging.getLogger("queryview.server")


def _fail(message: str, status: int = 400, **extra: Any) -> JSONResponse:
    return JSONResponse({"ok": False, "message": message, **extra}, status_code=status)


def _not_found(dashboard: Any) -> str:
    """What the page shows for a dashboard that is not (or no longer) in the repo."""
    return f"Dashboard “{dashboard}” not found." if isinstance(dashboard, str) else "unknown dashboard"


async def _poll(repo: Repo, interval: float) -> None:
    """Keep the dashboards at the branch head. A failed fetch is logged and the
    last good copy keeps serving."""
    while True:
        await asyncio.sleep(interval)
        try:
            await repo.refresh()
        except GitSyncError as e:
            log.warning("sync failed, still showing the last copy: %s", e)
        except Exception:
            # Anything else must not end the loop: the page would go stale for good.
            log.exception("sync failed unexpectedly, still showing the last copy")


def create_app(config: ServerConfig) -> FastAPI:
    repo = Repo(config.remote, config.branch)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await repo.refresh()  # the first clone: a failure aborts startup
        poll = asyncio.create_task(_poll(repo, config.sync_interval))
        try:
            yield
        finally:
            poll.cancel()
            with suppress(asyncio.CancelledError):
                await poll
            await close_client()

    app = FastAPI(title="queryview-server", lifespan=lifespan)
    app.state.repo = repo

    async def _target(request: Request) -> tuple[Connection, dict[str, Any], dict[str, Any]] | JSONResponse:
        """A POST body's connection and dashboard, by name, plus the body."""
        try:
            body = await request.json()
        except Exception:
            return _fail("a JSON body is required")
        if not isinstance(body, dict):
            return _fail("a JSON object is required")
        cname, dname = body.get("connection"), body.get("dashboard")
        conn = config.connections.get(cname) if isinstance(cname, str) else None
        if conn is None:
            return _fail("unknown connection", 404)
        dash = repo.get(dname) if isinstance(dname, str) else None
        if dash is None:
            return _fail(_not_found(dname), 404)
        return conn, dash, body

    async def _widget_sql(conn: Connection, dash: dict[str, Any], body: dict[str, Any]) -> str | JSONResponse:
        """The dashboard query a widget named, with the sent values applied.
        Values are resolved first, so each is one of its param's options."""
        qname = body.get("query")
        template = dash["queries"].get(qname) if isinstance(qname, str) else None
        if template is None:
            return _fail("unknown query", 404)
        driver = DRIVERS[conn.type]
        # Only the selectors this query needs: each options_sql is a query.
        declared = needed(template, parse_params(dash["params"]))
        try:
            resolved = await resolve_on(driver, conn.config, conn.database, declared, clean_values(body.get("values")))
        except ParamError as e:
            return _fail(str(e))
        values = {p["name"]: p["value"] for p in resolved}
        sql, why = ready_sql(template, dash["params"], values, dialect_of(driver))
        return sql if sql is not None else _fail(why or WAITING)

    @app.get("/api/health")
    async def health() -> dict[str, Any]:
        return {"status": "ok", "service": "queryview-server"}

    @app.get("/api/connections")
    async def connections() -> list[dict[str, str]]:
        return [{"name": c.name, "type": c.type} for c in config.connections.values()]

    @app.get("/api/dashboards")
    async def dashboards() -> list[dict[str, str]]:
        return [{"name": name} for name in repo.names()]

    # `:path`: a name may contain "/", which arrives decoded.
    @app.get("/api/dashboards/{name:path}")
    async def dashboard(name: str):
        d = repo.get(name)
        if d is None:
            return _fail(_not_found(name), 404)
        # Query names only: the SQL and the params' options_sql stay here.
        return {"name": d["name"], "html": d["html"], "queries": list(d["queries"])}

    # Run a dashboard's own queries (all, or the named ones) with its selectors
    # resolved from `values`.
    @app.post("/api/run")
    async def run_dashboard(request: Request):
        target = await _target(request)
        if isinstance(target, JSONResponse):
            return target
        conn, dash, body = target
        names = body.get("queries")
        if names is None:
            names = list(dash["queries"])
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            return _fail("queries must be a list of names")
        if any(n not in dash["queries"] for n in names):
            return _fail("unknown query", 404)
        r = await run_dashboard_on(
            DRIVERS[conn.type],
            conn.config,
            conn.database,
            {n: dash["queries"][n] for n in names},
            dash["params"],
            clean_values(body.get("values")),
        )
        resolved = resolved_part(r)
        if not r["ok"]:
            return _fail(r["message"], **resolved)
        return {"ok": True, "results": r["results"], **resolved}

    # One page of a widget's query, or its CSV.
    @app.post("/api/query")
    async def query(request: Request):
        target = await _target(request)
        if isinstance(target, JSONResponse):
            return target
        conn, dash, body = target
        sql = await _widget_sql(conn, dash, body)
        if isinstance(sql, JSONResponse):
            return sql
        limit, offset = page_bounds(body.get("limit"), body.get("offset"))
        order_by = body.get("order_by") if isinstance(body.get("order_by"), list) else None
        driver = DRIVERS[conn.type]
        if body.get("format") == "csv":
            text = await driver.export_csv(conn.config, sql, conn.database, limit, offset, order_by)
            return _fail(text.message) if isinstance(text, Err) else {"ok": True, "output": text.text}
        r = await driver.run_query(conn.config, sql, conn.database, limit, offset, order_by)
        if isinstance(r, Err):
            return _fail(r.message)
        return {"ok": True, "meta": [c._asdict() for c in r.rows.meta], "data": r.rows.data}

    # A widget query's output columns.
    @app.post("/api/describe")
    async def describe(request: Request):
        target = await _target(request)
        if isinstance(target, JSONResponse):
            return target
        conn, dash, body = target
        sql = await _widget_sql(conn, dash, body)
        if isinstance(sql, JSONResponse):
            return sql
        r = await DRIVERS[conn.type].describe_query(conn.config, sql, conn.database)
        return _fail(r.message) if isinstance(r, Err) else {"ok": True, "fields": r.fields}

    @app.api_route("/api/{rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
    async def api_not_found(rest: str):
        return _fail("not found", 404)

    # The page has no client-side routes: `/` is the page, anything else a file.
    @app.get("/{full_path:path}")
    async def page(full_path: str, v: str | None = None) -> Response:
        return await serve_static(full_path or "viewer.html", v is not None, index=None)

    return app


def run() -> None:
    """Console-script entry point: load the config, then serve."""
    port = resolve_port(prog="queryview-server")
    try:
        config = load_config(config_path())
    except ConfigError as e:
        sys.exit(f"queryview-server: {e}")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    uvicorn.run(create_app(config), host="0.0.0.0", port=port)
