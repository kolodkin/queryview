# "Not in git" Picker Marker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In a workspace with a git remote, dashboard picker options with no `commit_sha` read `<name> · not in git`.

**Architecture:** `list_dashboards` returns `commit_sha`; `DashboardView` reads the cached `gitStatus(activeWorkspace())` and suffixes options.

**Tech Stack:** FastAPI/SQLModel backend, React frontend, Playwright e2e.

**Spec:** `docs/superpowers/specs/2026-11-15-not-in-git-marker-design.md`

## Global Constraints

- Suffix text exactly ` · not in git`.
- No suffix when the workspace has no remote (`gitStatus` not `true`).
- No styling, icon, count or action.

## Review Focus

- Restore of a dashboard: suffix must clear (Task 2 adds `loadDashboards()` to `onRestored`).
- YAML import over a synced dashboard: suffix appears (list already reloads on import; covered by backend clearing test).
- Workspace switch to one without a remote: no suffix (gitStatus is per workspace).

---

### Task 1: List returns `commit_sha`

**Files:**
- Modify: `backend/queryview/dashboards.py` (`list_dashboards`)
- Test: `backend/queryview/test_dashboards.py::test_list_dashboards_orders_by_name_and_omits_payload`

**Interfaces:**
- Produces: `GET /api/dashboards` items `{name: str, updated_at: int, commit_sha: str | null}`

- [ ] Change the test's key assertion to `{"name", "updated_at", "commit_sha"}` and assert `row["commit_sha"] is None`; run, see it fail.
- [ ] Add `"commit_sha": r.commit_sha` to `list_dashboards`' dicts; run `uv run --group test pytest backend/queryview -q`, all pass.
- [ ] Update `docs/architecture/api.md` `GET /api/dashboards` row to name `commit_sha`.

### Task 2: Picker suffix

**Files:**
- Modify: `frontend/src/app/DashboardView.tsx` (`DashboardSummary`, option render, `onRestored`)
- Modify: `docs/system/gitsync.md` (`## UI`)
- Test: `e2e/workspaces.spec.ts::git save and restore dashboard round trip`

**Interfaces:**
- Consumes: Task 1's `commit_sha`; `gitStatus(workspace: string): Promise<boolean>` from `./gitsync`.

- [ ] In the e2e round trip, after the restore, assert `page.getByTestId("dashboard-select").locator("option", { hasText: name })` has text exactly `name` (no suffix). The positive case (suffix shown) has no e2e: every API save in a synced stack commits.
- [ ] `DashboardSummary` gains `commit_sha: string | null`; state `gitOn` from `gitStatus(activeWorkspace())` in an effect; option text `{d.name}{gitOn && d.commit_sha === null ? ' · not in git' : ''}`.
- [ ] `onRestored` also calls `void loadDashboards()`.
- [ ] `npm test -w frontend`, `npm run lint -w frontend`, `npm run build` pass.
- [ ] `docs/system/gitsync.md` UI section: one sentence on the suffix.
- [ ] Commit and push.
