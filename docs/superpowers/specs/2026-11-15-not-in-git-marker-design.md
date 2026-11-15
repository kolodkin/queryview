# "Not in git" marker in the dashboard picker

## Intent

In a synced workspace, let the user see at a glance which dashboards no git
commit holds (`commit_sha` is `NULL`: never saved to git, or overwritten by a
YAML import). Informational only: no action attached.

## Approaches

1. **Suffix in the picker option** (`sales · not in git`): every unsynced
   dashboard visible in one glance; plain text only. **Picked.**
2. Chip beside the picker for the open dashboard: more visible, one at a time.
3. List in the ⚠ workspace panel: all in one place, but reads as a warning.

## Design

- `GET /api/dashboards` items gain `commit_sha` (`list_dashboards`).
- `DashboardView` reads `gitStatus(activeWorkspace())`, as `GitSyncControls`
  does; only when it is `true` does an option with `commit_sha === null` read
  `<name> · not in git`. Without a remote nothing changes.
- The list already reloads after Save / Rename / Delete and a workspace sync;
  Restore's `onRestored` also calls `loadDashboards()` so the suffix clears.
- Docs: `api.md` list row, `gitsync.md` UI section.
- Tests: backend list returns `commit_sha`; one e2e/unit check of the suffix
  where the existing git e2e already runs.

## Non-goals

No styling, icon, count, or action button.
