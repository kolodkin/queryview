# `run_dashboard` MCP Tool Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** An MCP tool that runs a draft dashboard's queries with `{placeholders}` substituted and returns the rows to the agent.

**Architecture:** `mcp_server.run_dashboard` wraps `dashboard_queries.run_dashboard`, the function the page's own run uses, so resolution, substitution and the `each` fan-out are shared. The only backend change outside the tool is a `limit` argument threaded to `run_queries_on`.

**Tech Stack:** Python, the `mcp` server already in `backend/queryview/mcp_server.py`, pytest on in-memory DuckDB.

**Spec:** `docs/superpowers/specs/2026-11-24-run-dashboard-tool-design.md`

## Global Constraints

- Run everything with `uv run` (`uv run --group test pytest backend/queryview`).
- Imports at the top of the file; no `__all__`.
- Test data uses invented names only; no `Co-Authored-By` trailers in commits.
- Load the project `testing` skill before writing tests and `docs-writing` before editing `docs/`.
- `limit`: default `100`, clamped to `1..DASHBOARD_ROW_CAP` (1000).
- The page's behavior does not change: `run_dashboard` and `run_dashboard_on` keep `DASHBOARD_ROW_CAP` as their default.

## Review Focus

- A value the param's options do not offer: falls back to the default, as on the page (test in Task 1).
- `values` holding a non-string (`{"n": 3}`) or not a map: dropped by `clean_values`, never an exception (Task 1).
- `limit` out of range (`0`, `99999`): clamped, never an error (Task 1).
- A write statement as a query (`DROP TABLE …`): fails as a query error, nothing dropped (Task 1).
- A failing query after the params resolved: the reply still carries `params` (Task 1).

---

### Task 1: The tool

**Files:**
- Modify: `backend/queryview/dashboard_queries.py` (`run_dashboard_on`, `run_dashboard`)
- Modify: `backend/queryview/mcp_server.py` (new tool after `push_dashboard`)
- Create: `backend/queryview/test_mcp_dashboards.py`
- Modify: `backend/queryview/test_locked_connections.py` (`test_mcp_tools_are_refused_on_a_locked_connection`)

**Interfaces:**
- Produces: `dashboard_queries.run_dashboard(sid, queries, params, values, limit: int = DASHBOARD_ROW_CAP)` and `run_dashboard_on(..., values, limit: int = DASHBOARD_ROW_CAP)`, both passing `limit` to `run_queries_on`.
- Produces: `mcp_server.run_dashboard(session_id: str, queries: dict[str, str] | None = None, params: list[dict[str, Any]] | None = None, values: dict[str, str] | None = None, dir: str | None = None, limit: int = 100) -> dict[str, Any]`.

- [ ] **Step 1: Write the failing tests** in `test_mcp_dashboards.py`, importing `_connected_session` and `_run` from `queryview.test_mcp_connections` as `test_mcp_scripts.py` does.

```python
REGION = [{"name": "region", "options": ["eu", "us"]}]
Q = {"q": "SELECT {region} AS v"}


def test_substitutes_the_given_value():
    out = _run(run_dashboard(_connected_session("rd-value"), Q, REGION, {"region": "us"}))
    assert out["ok"] is True and out["results"] == {"q": {"v": ["us"]}}
    assert out["meta"]["q"][0]["name"] == "v"
    assert out["params"][0]["value"] == "us" and "database" in out


def test_a_param_left_out_or_not_offered_takes_its_default():
    sid = _connected_session("rd-default")
    for values in (None, {"region": "mars"}, {"region": 3}, "notamap"):
        assert _run(run_dashboard(sid, Q, REGION, values))["results"] == {"q": {"v": ["eu"]}}


def test_a_query_waiting_on_a_choice_is_left_out():
    params = [{**REGION[0], "default": "none"}]
    out = _run(run_dashboard(_connected_session("rd-wait"), Q, params))
    assert out["ok"] is True and out["results"] == {}


def test_each_runs_once_per_option():
    params = [{"name": "region", "kind": "each", "options": ["eu", "us"]}]
    out = _run(run_dashboard(_connected_session("rd-each"), Q, params))
    assert out["results"] == {"q": {"v": ["eu", "us"]}}


def test_limit_cuts_rows_and_is_clamped():
    sid = _connected_session("rd-limit")
    q = {"q": "SELECT * FROM range(5) AS t(i)"}
    assert _run(run_dashboard(sid, q, limit=2))["results"]["q"]["i"] == [0, 1]
    assert _run(run_dashboard(sid, q, limit=0))["results"]["q"]["i"] == [0]
    assert len(_run(run_dashboard(sid, q, limit=99999))["results"]["q"]["i"]) == 5


def test_reads_a_folder(tmp_path):
    (tmp_path / "dashboard.html").write_text("<p></p>")
    (tmp_path / "queries.yaml").write_text("q: SELECT {region} AS v\n")
    (tmp_path / "meta.yaml").write_text("params:\n  - name: region\n    options: [eu, us]\n")
    sid = _connected_session("rd-dir")
    assert _run(run_dashboard(sid, dir=str(tmp_path)))["results"] == {"q": {"v": ["eu"]}}
    both = _run(run_dashboard(sid, Q, dir=str(tmp_path)))
    assert both == {"ok": False, "message": "pass either `queries`, or `dir`"}


def test_refusals():
    sid = _connected_session("rd-refuse")
    assert _run(run_dashboard(sid)) == {"ok": False, "message": "pass `queries`, or `dir`"}
    assert "exactly one" in _run(run_dashboard(sid, Q, [{"name": "region"}]))["message"]
    rec = _run(sessions.create_session())
    assert _run(run_dashboard(rec.id, Q, REGION)) == {"ok": False, "message": "not connected"}


def test_a_failing_query_names_itself_and_keeps_the_params():
    sid = _connected_session("rd-fail")
    out = _run(run_dashboard(sid, {"q": "SELECT {region} FROM no_such_table"}, REGION))
    assert out["ok"] is False and out["message"].startswith("q:") and out["params"][0]["value"] == "eu"
    _run(run_script(sid, "CREATE TABLE kept (a INTEGER)"))
    assert _run(run_dashboard(sid, {"q": "DROP TABLE kept"}))["ok"] is False
    assert _run(run_sql(sid, "SELECT count(*) FROM kept"))["ok"] is True
```

In `test_locked_connections.py`, add beside the `run_sql` line:

```python
    assert _run(mcp_server.run_dashboard(sid, {"q": "SELECT 1"}))["message"] == "connection is locked"
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run --group test pytest backend/queryview/test_mcp_dashboards.py -q`
Expected: collection error, `cannot import name 'run_dashboard'`.

- [ ] **Step 3: Thread `limit`** through `run_dashboard_on` and `run_dashboard` in `dashboard_queries.py`, as the last parameter, default `DASHBOARD_ROW_CAP`, passed to `run_queries_on`.

- [ ] **Step 4: Implement `run_dashboard` in `mcp_server.py`**, decorated `@mcp.tool()`, placed after `push_dashboard`.

- Import `dashboard_queries` as a module at the top (`from . import dashboard_queries, gitsync, remote, sessions`): the tool shares the name of the function it calls.
- Order of checks: both `queries` and `dir` → `"pass either `queries`, or `dir`"`; `dir` read with `asyncio.to_thread(_read_dashboard_dir, dir)`, its `ValueError` / `gitsync.GitSyncError` message returned, inline `params` winning over the folder's; no queries → `"pass `queries`, or `dir`"`; `dashboard_params_error(params)`.
- Then `dashboard_queries.run_dashboard(session_id, queries, params, dashboard_queries.clean_values(values), max(1, min(limit, dashboard_queries.DASHBOARD_ROW_CAP)))`.
- Success: `{"ok": True, "database": await sessions.database_of(session_id), "results", "meta", "params"}`. Failure: `{"ok": False, "message", **dashboard_queries.resolved_part(r)}`.
- Docstring, the tool's description to the agent: what it is for (test a draft's queries before `push_dashboard`), that rows come back to the agent and nothing reaches the browser, the reply shape, that a query waiting on a choice is absent from `results`, that a run stops at the first failing query, and the `Args`.

- [ ] **Step 5: Run the backend suite**

Run: `uv run --group test pytest backend/queryview -q`
Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add backend/queryview
git commit -m "MCP: run_dashboard runs a draft's queries for the agent"
```

### Task 2: Docs

**Files:**
- Modify: `docs/mcp.md` (tool list, after `push_dashboard`)
- Modify: `docs/dashboard.md` (`## The push_dashboard MCP tool`)
- Modify: `backend/queryview/skills/queryview/SKILL.md` (`## Dashboards`)
- Modify: `docs/future.md` (remove the **Run a dashboard for an agent** bullet)
- Delete: this plan and its spec, per `docs/AGENTS.md`

- [ ] **Step 1: `mcp.md`**: a bullet `run_dashboard(session_id, queries?, params?, values?, dir?, limit?=100)`: runs a draft's queries with `values` substituted and returns `{ok, database, results, meta, params}` to the agent; `results` in the `window.queries` shape; at most `limit` rows a query (max 1000); stops at the first failing query; linking [dashboard.md](./dashboard.md#dashboard-parameters).
- [ ] **Step 2: `dashboard.md`**: one bullet under the `push_dashboard` one naming `run_dashboard` as the way an agent tests a draft's queries, linking `./mcp.md#tools`.
- [ ] **Step 3: `SKILL.md`**: one sentence in `## Dashboards`: test a draft's queries with `run_dashboard` before `push_dashboard`.
- [ ] **Step 4: `future.md`**: remove the bullet; `grep -rn "Run a dashboard for an agent" docs backend` returns nothing.
- [ ] **Step 5: Delete** `docs/superpowers/plans/2026-11-24-run-dashboard-tool.md` and `docs/superpowers/specs/2026-11-24-run-dashboard-tool-design.md`; run `devpowers:shortify` on the pages touched.
- [ ] **Step 6: Verify and commit**

Run: `uv run --group test pytest backend/queryview -q` (the skill file ships in the wheel)
Expected: all pass.

```bash
git add -A docs backend/queryview/skills
git commit -m "Docs: the run_dashboard MCP tool"
```
