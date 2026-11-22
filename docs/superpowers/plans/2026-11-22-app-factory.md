# App Factory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `SERVE_STATIC` env switch with an app factory whose mode is a command-line argument.

**Architecture:** `main.py` becomes `app.py`: routes on a module-level `APIRouter`, `create_app(frontend)` assembles the app, and no app is built at import. `__main__.py` is the one entry point and hands uvicorn a factory name.

**Tech Stack:** FastAPI, uvicorn, pytest, Playwright.

**Spec:** `docs/superpowers/specs/2026-11-22-app-factory-design.md`

## Global Constraints

- `uv run` for Python; load the project `testing` skill before changing tests.
- Imports at the top of the file; no `__all__`.
- Commit messages carry no AI attribution trailers.
- No backwards compatibility: `SERVE_STATIC` and `queryview-backend` are deleted, not deprecated.
- The viewer server (`backend/queryview/server/`) is not touched beyond a docstring.

## Review Focus

- A frontend route with no build on disk: a 404, not a failed response (Task 1).
- `queryview --api-only` on a machine that has a build: `/` is still a 404 (Task 2).
- `/mcp` with and without the frontend: the redirect to `/mcp/` holds in both (Task 2).
- An unknown argument or a non-numeric `--port`: argparse's usage error, exit code 2 (Task 3).
- `--reload` through the command: the server restarts on a code change (Task 3, checked by hand).

---

### Task 1: A missing build is a 404

**Files:** Modify `backend/queryview/serving.py`; Test `backend/queryview/test_static.py`

- [ ] **Step 1: Failing test**

```python
def test_a_route_with_no_build_on_disk_is_a_404(tmp_path, monkeypatch):
    monkeypatch.setenv("STATIC_ROOT", str(tmp_path))  # empty: nothing was built
    serving.static_root.cache_clear()
    try:
        assert asyncio.run(serving.serve_static("dashboard")).status_code == 404
        assert asyncio.run(serving.serve_static("")).status_code == 404
    finally:
        serving.static_root.cache_clear()
```

- [ ] **Step 2:** Run it, see it fail (a `FileResponse` for a file that is not there).
- [ ] **Step 3:** In `serve_static`, return the 404 when `root / index` is not a file.
- [ ] **Step 4:** `uv run --group test pytest backend/queryview/test_static.py` passes.
- [ ] **Step 5:** Commit `A frontend route with no build is a 404`.

### Task 2: The factory

**Files:**
- Rename: `backend/queryview/main.py` -> `backend/queryview/app.py`
- Modify: `backend/queryview/conftest.py`, the nine test files importing `app` from `queryview.main`, docstrings naming `main.py` (`mcp_server.py`, `connect.py`, `remote.py`, `server/main.py`)
- Test: `backend/queryview/test_app.py` (new)

**Interfaces:**
- Produces, in `app.py`: `router: APIRouter`, `create_app(frontend: bool = True) -> FastAPI`, `create_api_app() -> FastAPI`. In `conftest.py`: `app = create_app()`, the one app the tests share.

- [ ] **Step 1: Failing tests** in `test_app.py`, with a `STATIC_ROOT` fixture holding an `index.html`:

```python
def test_the_full_app_serves_the_frontend(built):
    assert TestClient(create_app()).get("/dashboard").text == "<!doctype html>"

def test_the_api_only_app_serves_no_frontend(built):
    c = TestClient(create_api_app())
    assert c.get("/").status_code == 404 and c.get("/dashboard").status_code == 404
    assert c.get("/api/health").status_code == 200

@pytest.mark.parametrize("make", [create_app, create_api_app])
def test_both_apps_have_the_api_and_the_mcp_redirect(make):
    c = TestClient(make(), follow_redirects=False)
    assert c.get("/api/nope").status_code == 404 and c.get("/api/nope").json() == {"error": "not found"}
    r = c.post("/mcp")
    assert r.status_code == 307 and r.headers["location"] == "/mcp/"

def test_importing_the_module_builds_no_app():
    assert not hasattr(queryview.app, "app")
```

- [ ] **Step 2:** Run, see them fail on import.
- [ ] **Step 3:** `git mv` the module; change every `@app.<method>` route to `@router.<method>`; move the app construction (lifespan, MCP mount, session middleware, router, and the catch-all only when `frontend`) into `create_app`; delete `SERVE_STATIC`, the `else` catch-all and `run()`.
- [ ] **Step 4:** `conftest.py` builds the shared `app`; the nine test files import it from `queryview.conftest`.
- [ ] **Step 5:** `uv run --group test pytest backend/queryview` passes.
- [ ] **Step 6:** Commit `The app is built by a factory`.

### Task 3: The entry point

**Files:**
- Create: `backend/queryview/__main__.py`
- Modify: `backend/queryview/serving.py` (the `--port` parser becomes reusable), `pyproject.toml`, `package.json`, `e2e/fixtures.ts`, `CONTRIBUTING.md`, `.github/workflows/publish.yaml` (comment)
- Test: `backend/queryview/test_main.py`

**Interfaces:**
- Produces: `queryview.__main__.run(argv: list[str] | None = None) -> None`; `serving.port_parser(prog: str) -> argparse.ArgumentParser` and `serving.port_of(args) -> int`, with `resolve_port` built on them.
- `[project.scripts]`: `queryview = "queryview.__main__:run"`; `queryview-backend` removed.

- [ ] **Step 1: Failing tests**, with `uvicorn.run` replaced by a recorder:

```python
def test_runs_the_full_app_by_default(started):
    run([])
    assert started == [("queryview.app:create_app", {"factory": True, "host": "0.0.0.0", "port": 8000, "reload": False})]

def test_api_only_reload_and_port(started):
    run(["--api-only", "--reload", "--port", "9000"])
    assert started == [("queryview.app:create_api_app", {"factory": True, "host": "0.0.0.0", "port": 9000, "reload": True})]

@pytest.mark.parametrize("argv", [["--nope"], ["--port", "x"]])
def test_a_bad_argument_is_a_usage_error(argv, started):
    with pytest.raises(SystemExit) as e:
        run(argv)
    assert e.value.code == 2 and started == []
```

- [ ] **Step 2:** Run, see them fail.
- [ ] **Step 3:** Implement `run`: the factory is named, not passed, because `--reload` re-imports it.
- [ ] **Step 4:** Update the scripts: `backend` -> `uv run queryview --api-only --reload --port 8000`; `debug`'s backend -> `uv run queryview --reload --port ${PORT:-8000}`; `start` -> `uv run queryview`. The e2e fixture starts `queryview` with no `SERVE_STATIC`.
- [ ] **Step 5:** Verify: backend suite, `npm test -w frontend`, `claudeai/run.sh` then the full e2e; by hand, `uv run python -m queryview --api-only --port <p>` answers `/api/health` and 404s `/`, and `--reload` restarts on a touched file.
- [ ] **Step 6:** Delete this plan and its spec; commit `One entry point: queryview with --api-only and --reload`.
