# Folder-as-name for synced dashboards

## Intent

A synced dashboard's name is stored twice: as its folder
(`dashboards/<percent-encoded name>/`) and as `name` in `meta.yaml`. Make the
folder the only copy, so a rename is a pure folder move and the two can never
disagree. Refuse names the folder cannot hold, with a server-side message.

## Approaches

1. **The folder is the name.** `slug` is a reversible percent-encoding, so
   decoding the folder gives the name back exactly. **Picked.**
2. `name.txt` beside the files: a rename still rewrites one file, and every
   dashboard gains a fourth.
3. Keep `name` in `meta.yaml`: a rename keeps rewriting it.

## Design

Repo layout (`gitsync.py`):

- `dashboards/<slug>/dashboard.html` and `queries.yaml` are required.
  `meta.yaml` holds only `params` and is written only when params are declared.
- Reading: the name is the decoded folder. A `name` key in an older
  `meta.yaml` is ignored, so existing repos read unchanged and their recorded
  sync state stays valid.
- A folder whose name is not what `slug` would write for its decoded name
  (`a%41`, `%zz`) is skipped, like an incomplete folder.
- Rename: `git mv` alone.
- An agent's draft `dir` (`mcp_server.py`) is unchanged: its `meta.yaml` may
  still name the saved dashboard it edits.

Name checks, all server-side, each answering `{ok: false, message}`:

| Check | Rule | Status |
| --- | --- | --- |
| Length | `slug(name)` is over 255 bytes | 400 |
| Case twin | another dashboard in the workspace has the same `slug(name).lower()` | 409 |

- Applied to a name that is new to the workspace: Save of a new dashboard
  (`POST /api/dashboards`), Rename (`POST /api/dashboards/{name}/rename`) and
  YAML import (also between the entries of one bundle).
- In a synced workspace Save and Rename check after the fetch and merge and
  before the commit, so a twin another instance just pushed is seen.
- Renaming a dashboard to another case of its own name stays allowed.
- The UI adds nothing: Save and Rename already show the server's `message`.

Docs: `gitsync.md` layout and rename, `dashboard.md` and `api.md` where they
describe the files and the refusals.

Tests (pytest): the name read from the folder with an older `meta.yaml` name
ignored; a non-standard folder skipped; a rename commit that only moves files;
each check refused on Save, Rename and import; a case-only rename still works.

## Non-goals

- Windows-only rules (a trailing dot, reserved names such as `CON`).
- Repairing dashboards that are already overlong or case twins.
- Client-side validation.
- Rewriting an older `meta.yaml` on rename: its ignored `name` line stays
  until that dashboard's next Save.

## Risk

An older QueryView, including a viewer server, cannot read a dashboard saved
in this layout: every instance on a repo upgrades together.
