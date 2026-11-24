# Folder-as-name Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A synced dashboard's folder is its only stored name, and names the folder cannot hold are refused server-side.

**Architecture:** `yamlio.py` gains the inverse of `slug` and one pure name check. `gitsync.py` reads the name from the folder, writes `meta.yaml` only for params, and runs the check inside Save and Rename; `yamlio.import_text` runs it for imports.

**Tech Stack:** Python, pytest (`uv run --group test pytest backend/queryview`), git CLI.

**Spec:** `docs/superpowers/specs/2026-11-24-folder-as-name-design.md`

## Global Constraints

- Limit: `slug(name)` at most 255 bytes; over it is status 400.
- Case twin: same `slug(name).lower()` as another dashboard in the workspace; status 409.
- Checks apply only to a name new to the workspace; existing rows are never refused.
- An older `meta.yaml` with a `name` key reads unchanged; recorded sync oids stay valid (oid order stays meta, html, queries, `""` for an absent file).
- No frontend change. No imports inside functions, no `__all__` (root `AGENTS.md`).
- Load the project `testing` skill before touching tests; invented example names only.
- Commit messages carry no AI attribution trailers.

## Review Focus

1. An existing repo whose `meta.yaml` names differ from its folder: the folder wins (Task 2 test).
2. A hand-made folder `a%41` beside a real `aA`: skipped, never a second `aA` (Task 2 test).
3. The viewer server serving a dashboard that has no `meta.yaml` (Task 2 test in `server/test_repo.py`).
4. Saving an existing dashboard that already has a case twin: still allowed (Task 3 test).
5. A twin pushed by another instance since the last fetch: refused, nothing committed (Task 3 test).

---

### Task 1: `unslug` and `name_error`

**Files:**
- Modify: `backend/queryview/yamlio.py` (beside `slug`)
- Test: `backend/queryview/test_yamlio.py`

**Interfaces:**
- Produces: `unslug(folder: str) -> str | None`: the name `slug` writes as `folder`, else None (not canonical, or empty).
- Produces: `name_error(name: str, others: Iterable[str]) -> tuple[int, str] | None`: None when `name` is in `others` or fits; else `(400, "dashboard name is too long: <n> bytes encoded, at most 255")` or `(409, "dashboard <twin!r> already exists: names must differ by more than letter case")`.

- [ ] **Step 1: Failing tests**

```python
def test_unslug_inverts_slug_and_refuses_other_spellings():
    for name in ["Sales 2026", ".hidden", "100% done", "a/b\\c", "销售", "x%41", ".."]:
        assert unslug(slug(name)) == name
    assert unslug("a%41") is None  # slug writes "aA"
    assert unslug("%zz") is None and unslug("%FF") is None and unslug("a%2f") is None


def test_name_error():
    assert name_error("x" * 255, []) is None
    assert name_error("x" * 256, [])[0] == 400
    assert name_error("é" * 43, [])[0] == 400  # 258 bytes encoded
    status, message = name_error("Sales", ["sales"])
    assert status == 409 and "'sales'" in message
    assert name_error("sales", ["sales", "Sales"]) is None  # not new
    assert name_error("É", ["é"]) is None  # folders differ on any filesystem
```

- [ ] **Step 2:** `uv run --group test pytest backend/queryview/test_yamlio.py -k "unslug or name_error"` fails on the import.
- [ ] **Step 3:** Implement both with `urllib.parse.unquote`; update the `slug` docstring (export filenames: the content is canonical; gitsync folders: the folder is the name).
- [ ] **Step 4:** Same command passes.
- [ ] **Step 5:** Commit `yamlio: decode a folder name and check a new dashboard name`.

### Task 2: The folder is the name

**Files:**
- Modify: `backend/queryview/gitsync.py` (`dashboard_to_files`, `dashboard_from_files`, `_repo_entities`, `_read_repo_entity`, `restore`, `rename`)
- Modify: `backend/queryview/mcp_server.py:493` (drop the `require_name` argument)
- Test: `backend/queryview/test_gitsync.py`, `backend/queryview/server/test_repo.py`

**Interfaces:**
- Consumes: `unslug` (Task 1).
- Produces: `dashboard_to_files(d)` returns `dashboard.html`, `queries.yaml`, and `meta.yaml` (`params` only) when `d["params"]` is non-empty.
- Produces: `dashboard_from_files(files)`: `meta.yaml` optional; `name` is the meta's name or None.
- Produces: `_read_repo_entity(wd, ref, relpath)` reads the files present and sets `name = unslug(folder)`.

- [ ] **Step 1: Failing tests** in `test_gitsync.py`; update the tests the layout change invalidates (`test_dashboard_files_round_trip`, `test_dashboard_from_files_rejects_malformed_meta`, `test_store_dashboard_touches_only_its_dir`, `test_an_older_meta_yaml_naming_a_connection_still_reads`, `test_dashboard_params_round_trip_through_meta_yaml`, `test_restore_of_a_dashboard_missing_meta_names_the_file`).

```python
def _legacy(wd: Path, folder: str, meta: str) -> None:
    d = wd / "dashboards" / folder
    d.mkdir(parents=True)
    (d / "meta.yaml").write_text(meta, encoding="utf-8")
    (d / "dashboard.html").write_text("<p>l</p>", encoding="utf-8")
    (d / "queries.yaml").write_text("{}\n", encoding="utf-8")


def test_the_folder_names_the_dashboard(git_env, tmp_path):
    _run(gitsync.save(_default_ws(), _dash("fn seed", "<p>s</p>")))  # an empty remote has no main
    _hand_edit(git_env, tmp_path, lambda wd: _legacy(wd, "fn folder", "name: fn other\n"))
    r = _run(gitsync.sync(_default_ws()))
    assert r["imported"] == [{"kind": "dashboard", "name": "fn folder"}]
    assert _html("fn folder") == "<p>l</p>" and _html("fn other") is None


def test_a_folder_slug_would_not_write_is_skipped(git_env, tmp_path):
    _run(gitsync.save(_default_ws(), _dash("fn seed", "<p>s</p>")))
    _hand_edit(git_env, tmp_path, lambda wd: _legacy(wd, "fn%41", "{}\n"))
    assert _run(gitsync.sync(_default_ws()))["imported"] == []
    assert _html("fnA") is None


def test_a_params_free_dashboard_has_no_meta_yaml(git_env):
    _run(gitsync.save(_default_ws(), _dash("fn plain", "<p>p</p>")))
    assert f"{dashboard_reldir('fn plain')}/meta.yaml" not in _repo_files(git_env)
```

Rewrite `test_rename_moves_folder_in_one_commit`'s meta assertions as: the rename commit's `git show --name-status -M --format= main` lists only `R100` lines; and a legacy folder renamed reads under the new name (`other_instance` sync imports `{"kind": "dashboard", "name": <new>}`).

In `server/test_repo.py`, following its existing repo-building helper: a dashboard folder with no `meta.yaml` is served by `Repo.get(<folder name>)`.

- [ ] **Step 2:** `uv run --group test pytest backend/queryview/test_gitsync.py backend/queryview/server/test_repo.py` shows the new tests failing.
- [ ] **Step 3:** Implement. `_repo_entities` keys on `queries.yaml`, requires `dashboard.html` and `unslug(folder) is not None`, and joins oids over `DASHBOARD_FILES` with `""` for an absent `meta.yaml`. `restore` requires only the two files. `rename.stage` keeps the `git mv` calls and drops the meta rewrite.
- [ ] **Step 4:** `uv run --group test pytest backend/queryview` passes.
- [ ] **Step 5:** Commit `gitsync: a dashboard's folder is its name`.

### Task 3: Refuse names the folder cannot hold

**Files:**
- Modify: `backend/queryview/gitsync.py` (`save`, `rename`), `backend/queryview/yamlio.py` (`import_text`)
- Test: `backend/queryview/test_gitsync.py`, `backend/queryview/test_yamlio.py`

**Interfaces:**
- Consumes: `name_error` (Task 1), `dashboards.list_dashboards`.
- Produces: `gitsync._check_new_name(ws: WorkspaceRec, name: str, old: str | None = None) -> None`, raising `GitSyncError(message, status=...)`; `old` is left out of the compared names so a case-only rename passes.

- [ ] **Step 1: Failing tests**

```python
def test_save_refuses_a_case_twin_and_an_overlong_name(git_env):
    _run(gitsync.save(_default_ws(), _dash("nc Sales", "<p>a</p>")))
    before = _remote_log(git_env)
    for name, status in [("nc sales", 409), ("n" * 256, 400)]:
        with pytest.raises(GitSyncError) as e:
            _run(gitsync.save(_default_ws(), _dash(name, "<p>b</p>")))
        assert e.value.status == status and _html(name) is None
    assert _remote_log(git_env) == before


def test_save_without_a_remote_refuses_them_too():
    _run(gitsync.save(_default_ws(), _dash("nc Local", "<p>a</p>")))
    with pytest.raises(GitSyncError) as e:
        _run(gitsync.save(_default_ws(), _dash("nc local", "<p>b</p>")))
    assert e.value.status == 409 and _html("nc local") is None


def test_an_existing_twin_can_still_be_saved():
    _save("nc Pair", "<p>1</p>")
    _save("nc pair", "<p>2</p>")
    _run(gitsync.save(_default_ws(), _dash("nc pair", "<p>3</p>")))
    assert _html("nc pair") == "<p>3</p>"


def test_rename_refuses_a_twin_of_another_dashboard(git_env):
    _run(gitsync.save(_default_ws(), _dash("nc One", "<p>1</p>")))
    _run(gitsync.save(_default_ws(), _dash("nc two", "<p>2</p>")))
    for new, status in [("nc one", 409), ("n" * 256, 400)]:
        with pytest.raises(GitSyncError) as e:
            _run(gitsync.rename(_default_ws(), "nc two", new))
        assert e.value.status == status
    assert _html("nc two") == "<p>2</p>"


def test_a_twin_another_instance_pushed_is_seen(other_instance, git_env):
    _run(gitsync.save(other_instance, _dash("nc Remote", "<p>r</p>")))
    with pytest.raises(GitSyncError) as e:
        _run(gitsync.save(_default_ws(), _dash("nc remote", "<p>l</p>")))
    assert e.value.status == 409 and _html("nc remote") is None
```

In `test_yamlio.py`: importing a dashboard document named `Imp sales` beside a saved `imp sales` raises `YamlIOError` with status 409 and writes nothing; a workspace bundle holding `imp A` and `imp a` raises 409 and writes neither. The existing `test_rename_changing_only_the_case` must keep passing.

- [ ] **Step 2:** The new tests fail.
- [ ] **Step 3:** Implement. In `save` and `rename`, call `_check_new_name` first thing in `stage` (synced: after the merge) and first thing in `after` when `wd is None` (unsynced: `stage` never ran). In `import_text`, check each entry against the workspace's names plus the entries before it, before the upsert.
- [ ] **Step 4:** `uv run --group test pytest backend/queryview` and `uv run ruff check backend && uv run ruff format --check backend` pass.
- [ ] **Step 5:** Commit `Refuse a dashboard name its repo folder cannot hold`.

### Task 4: Docs and cleanup

**Files:**
- Modify: `docs/gitsync.md` (layout block, the "canonical name" sentence, Rename refusals), `docs/api.md` (Save, Rename and import rows: `400` too long, `409` case twin), `docs/export-import.md` (import refusals), `e2e/fixtures.ts:368` (write `meta.yaml` only for params, without `name`)
- Delete: this plan and its spec (`docs/AGENTS.md`: removed once implemented)

- [ ] **Step 1:** Edit the pages per the `docs-writing` skill, then run `devpowers:shortify` on them.
- [ ] **Step 2:** `grep -rn "canonical name\|meta.yaml" docs backend/queryview/skills` shows no line still saying the name lives in `meta.yaml` of a synced folder.
- [ ] **Step 3:** Commit `Document folder-as-name and the name checks`, then push.
