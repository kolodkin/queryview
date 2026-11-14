"""Git sync: serializer round-trips (dashboards <-> repo files) and, in later
tests, store/history/restore against a local bare repo (no network)."""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

import pytest

from queryview import gitsync, workspaces
from queryview.gitsync import (
    DASHBOARD_FILES,
    GitSyncError,
    dashboard_from_files,
    dashboard_reldir,
    dashboard_to_files,
)


def _run(coro):
    return asyncio.run(coro)


def test_relpaths():
    assert dashboard_reldir("sales/eu") == "dashboards/sales%2Feu"


def test_dashboard_files_round_trip():
    d = {
        "name": "sales",
        "html": "<html>\n<body>hi — ünicode</body>\n</html>",
        "queries": {"revenue": "SELECT 1", "multi": "SELECT a\nFROM b"},
        "params": [],
    }
    files = dashboard_to_files(d)
    assert set(files) == set(DASHBOARD_FILES)
    assert files["dashboard.html"] == d["html"]  # verbatim
    assert dashboard_from_files(files) == d


def test_dashboard_from_files_rejects_malformed_meta():
    with pytest.raises(GitSyncError):
        dashboard_from_files({"meta.yaml": "connection: x", "dashboard.html": "", "queries.yaml": ""})


# The git_env fixture (bare repo + redirected clone base) lives in conftest.py.


def _default_ws_id() -> int:
    from queryview.workspaces import DEFAULT_WORKSPACE, resolve

    return _run(resolve(DEFAULT_WORKSPACE)).id


def _default_ws():
    """The default workspace, re-resolved so per-test remote changes are seen."""
    from queryview.workspaces import DEFAULT_WORKSPACE, resolve

    return _run(resolve(DEFAULT_WORKSPACE))


def _remote_log(remote) -> str:
    return subprocess.run(
        ["git", "log", "--format=%H %s", "main"],
        cwd=remote,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def _save(name: str, html: str, ws_id: int | None = None) -> None:
    from queryview.dashboards import upsert_dashboard

    _run(upsert_dashboard(name, html, {"q": "SELECT 1"}, workspace_id=ws_id or _default_ws_id()))


def _html(name: str, ws_id: int | None = None) -> str | None:
    from queryview.dashboards import get_dashboard

    d = _run(get_dashboard(name, ws_id or _default_ws_id()))
    return d["html"] if d else None


def test_store_unconfigured_is_409():
    # Outside git_env the default workspace has no remote configured.
    with pytest.raises(GitSyncError) as e:
        _run(gitsync.store(_default_ws(), "dashboard", "anything"))
    assert e.value.status == 409
    assert "no git remote" in str(e.value)


@pytest.mark.parametrize("kind", ["dashbord", "query"])
def test_unknown_kind_is_400(kind):
    """Dashboards are the only kind; the removed 'query' kind is refused too."""
    for op in (gitsync.store, gitsync.history, gitsync.restore):
        with pytest.raises(GitSyncError) as e:
            _run(op(_default_ws(), kind, "x"))
        assert e.value.status == 400
        assert "kind" in str(e.value)


def test_store_missing_entity_is_404(git_env):
    with pytest.raises(GitSyncError) as e:
        _run(gitsync.store(_default_ws(), "dashboard", "no such dashboard xyz"))
    assert e.value.status == 404


def test_store_commits_and_pushes(git_env):
    _save("gs top", "<html>1</html>")
    r = _run(gitsync.store(_default_ws(), "dashboard", "gs top"))
    assert r["committed"] is True and r["sha"]
    log = _remote_log(git_env)
    assert r["sha"] in log
    assert "store dashboard gs top" in log


def test_store_no_change_makes_no_commit(git_env):
    _save("gs same", "<html>2</html>")
    r1 = _run(gitsync.store(_default_ws(), "dashboard", "gs same"))
    r2 = _run(gitsync.store(_default_ws(), "dashboard", "gs same"))
    assert r1["committed"] is True
    assert {k: r2[k] for k in ("committed", "sha", "message")} == {
        "committed": False,
        "sha": None,
        "message": "no changes",
    }
    assert _remote_log(git_env).count("\n") == 1  # exactly one commit


def test_store_dashboard_touches_only_its_dir(git_env):
    from queryview.dashboards import upsert_dashboard

    _run(upsert_dashboard("gs dash", "<html>v1</html>", {"q": "SELECT 1"}, workspace_id=_default_ws_id()))
    r = _run(gitsync.store(_default_ws(), "dashboard", "gs dash"))
    assert r["committed"] is True
    out = subprocess.run(
        ["git", "show", "--name-only", "--format=", r["sha"]],
        cwd=git_env,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    files = [line for line in out.splitlines() if line.strip()]
    assert files and all(f.startswith("dashboards/gs dash/") for f in files)
    assert set(files) == {
        "dashboards/gs dash/meta.yaml",
        "dashboards/gs dash/dashboard.html",
        "dashboards/gs dash/queries.yaml",
    }


def test_store_custom_message(git_env):
    _save("gs msg", "<html>3</html>")
    _run(gitsync.store(_default_ws(), "dashboard", "gs msg", message="before migration"))
    assert "before migration" in _remote_log(git_env)


def test_store_unreachable_remote_raises_without_init(tmp_path, clone_base):
    from queryview.workspaces import DEFAULT_WORKSPACE, update_workspace

    _run(update_workspace(DEFAULT_WORKSPACE, remote=str(tmp_path / "does-not-exist.git")))
    try:
        _save("gs unreachable", "<html>1</html>")
        ws = _default_ws()
        with pytest.raises(GitSyncError) as e:
            _run(gitsync.store(ws, "dashboard", "gs unreachable"))
        assert e.value.status == 502
        # No spurious local repo in this workspace's clone dir.
        assert not (clone_base / str(ws.id) / ".git").exists()
    finally:
        _run(update_workspace(DEFAULT_WORKSPACE, remote=None))


def _clone_head() -> str:
    wd = gitsync._clone_base() / str(_default_ws_id())
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=wd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _store_versions(name: str, htmls: list[str]) -> list[str]:
    """Save+store the dashboard once per HTML; returns the commit shas in order."""
    shas = []
    for html in htmls:
        _save(name, html)
        shas.append(_run(gitsync.store(_default_ws(), "dashboard", name))["sha"])
    return shas


def test_history_pages_newest_first(git_env):
    shas = _store_versions("gs hist", ["<p>1</p>", "<p>2</p>", "<p>3</p>"])
    page1 = _run(gitsync.history(_default_ws(), "dashboard", "gs hist", limit=2))
    assert [r["sha"] for r in page1["revisions"]] == [shas[2], shas[1]]
    assert page1["has_more"] is True
    assert all(isinstance(r["date"], int) and r["message"] for r in page1["revisions"])
    page2 = _run(gitsync.history(_default_ws(), "dashboard", "gs hist", before=shas[1], limit=2))
    assert [r["sha"] for r in page2["revisions"]] == [shas[0]]
    assert page2["has_more"] is False
    # Paging past the oldest commit yields an empty page, not an error.
    page3 = _run(gitsync.history(_default_ws(), "dashboard", "gs hist", before=shas[0], limit=2))
    assert page3 == {"revisions": [], "has_more": False}


def test_history_garbage_before_is_404(git_env):
    _store_versions("gs badbefore", ["<p>1</p>"])
    with pytest.raises(GitSyncError) as e:
        _run(gitsync.history(_default_ws(), "dashboard", "gs badbefore", before="not-a-sha"))
    assert e.value.status == 404


def test_history_only_sees_own_entity(git_env):
    _store_versions("gs mine", ["<p>1</p>"])
    _store_versions("gs other", ["<p>9</p>"])
    h = _run(gitsync.history(_default_ws(), "dashboard", "gs mine"))
    assert len(h["revisions"]) == 1


def test_restore_old_version_overwrites_db_without_moving_head(git_env):
    shas = _store_versions("gs restore", ["<p>1</p>", "<p>2</p>"])
    head_before = _clone_head()
    r = _run(gitsync.restore(_default_ws(), "dashboard", "gs restore", ref=shas[0]))
    assert r["restored"] is True
    assert _html("gs restore") == "<p>1</p>"
    assert _clone_head() == head_before  # HEAD never moves


def test_restore_default_ref_is_remote_head(git_env):
    _store_versions("gs latest", ["<p>1</p>", "<p>2</p>"])
    _save("gs latest", "<p>999</p>")  # local drift
    _run(gitsync.restore(_default_ws(), "dashboard", "gs latest"))
    assert _html("gs latest") == "<p>2</p>"


def test_restore_dashboard_round_trip(git_env):
    from queryview.dashboards import get_dashboard, upsert_dashboard

    _run(upsert_dashboard("gs rdash", "<html>v1</html>", {"q": "SELECT 1"}, workspace_id=_default_ws_id()))
    _run(gitsync.store(_default_ws(), "dashboard", "gs rdash"))
    _run(upsert_dashboard("gs rdash", "<html>v2</html>", {"q": "SELECT 2"}, workspace_id=_default_ws_id()))
    _run(gitsync.restore(_default_ws(), "dashboard", "gs rdash"))
    d = _run(get_dashboard("gs rdash", _default_ws_id()))
    assert d == {
        "name": "gs rdash",
        "html": "<html>v1</html>",
        "queries": {"q": "SELECT 1"},
        "params": [],
    }


def test_restore_missing_at_ref_is_404(git_env):
    _store_versions("gs exists", ["<p>1</p>"])
    with pytest.raises(GitSyncError) as e:
        _run(gitsync.restore(_default_ws(), "dashboard", "never stored"))
    assert e.value.status == 404


def _bare(tmp_path, name):
    remote = tmp_path / name
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
    )
    return remote


def test_store_is_isolated_per_workspace(tmp_path, clone_base):
    """A commit in workspace A lands only in A's remote; B's stays empty; a
    workspace without a remote is 409."""
    from queryview.workspaces import create_workspace, resolve

    ra, rb = _bare(tmp_path, "a.git"), _bare(tmp_path, "b.git")
    _run(create_workspace("t5-a", remote=str(ra)))
    _run(create_workspace("t5-b", remote=str(rb)))
    _run(create_workspace("t5-none"))
    wa, wb = _run(resolve("t5-a")), _run(resolve("t5-b"))

    _save("iso", "<p>1</p>", wa.id)
    r = _run(gitsync.store(wa, "dashboard", "iso"))
    assert r["committed"] is True
    assert "store dashboard iso" in _remote_log(ra)
    # B's remote has no commits at all (git log fails on an empty bare repo).
    p = subprocess.run(["git", "log", "--format=%H", "main"], cwd=rb, capture_output=True, text=True)
    assert p.returncode != 0

    # And B's history for the same entity name is empty, not A's history.
    _save("iso", "<p>2</p>", wb.id)
    h = _run(gitsync.history(wb, "dashboard", "iso"))
    assert h["revisions"] == []

    wn = _run(resolve("t5-none"))
    with pytest.raises(GitSyncError) as e:
        _run(gitsync.store(wn, "dashboard", "iso"))
    assert e.value.status == 409
    assert "no git remote" in str(e.value)


def test_git_missing_binary_is_gitsync_error(tmp_path, monkeypatch):
    # An empty PATH means no `git` executable: report it as a GitSyncError
    # (502, like any other git failure) rather than leaking FileNotFoundError.
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(GitSyncError) as e:
        _run(gitsync._git("--version"))
    assert e.value.status == 502
    assert "git is not installed" in str(e.value)


# --- Credentials and non-interactive behaviour -----------------------------


def test_split_credential_separates_http_userinfo():
    url = "https://x-access-token:ghp_tok@github.com/acme/repo.git"
    assert workspaces.split_credential(url) == (
        "https://github.com/acme/repo.git",
        ("x-access-token", "ghp_tok"),
    )


def test_split_credential_handles_a_bare_token_and_a_port():
    sanitized, cred = workspaces.split_credential("https://ghp_tok@git.example.internal:8443/a/b.git")
    assert sanitized == "https://git.example.internal:8443/a/b.git"
    assert cred == ("ghp_tok", "")


def test_split_credential_percent_decodes():
    _, cred = workspaces.split_credential("https://user:p%40ss%2Fword@example.internal/r.git")
    assert cred == ("user", "p@ss/word")


def test_split_credential_leaves_ssh_and_plain_urls_alone():
    """`git@host` is an SSH login, not a secret — stripping it breaks the URL."""
    for url in (
        "git@github.com:acme/repo.git",
        "ssh://git@github.com/acme/repo.git",
        "https://github.com/acme/repo.git",
        "/srv/mirrors/repo.git",
    ):
        assert workspaces.split_credential(url) == (url, None)


def test_credential_never_reaches_the_clone_config(monkeypatch, clone_base):
    """The URL git records must be the sanitized one, so a backup of the data
    dir carries no working credential."""
    calls: list[tuple[str, ...]] = []

    async def fake_git(*args, cwd=None, credential=None):
        calls.append(args)
        if args[0] == "clone":
            raise GitSyncError("branch not found")  # as on a not-yet-created branch
        return ""  # ls-remote: no heads -> empty remote -> init + `remote add`

    monkeypatch.setattr(gitsync, "_git", fake_git)
    ws = gitsync.WorkspaceRec(id=99, name="w", branch="main", remote="https://tok@example.internal/a/b.git")

    _run(gitsync._ensure_repo(ws))

    urls = [a[-1] for a in calls if a[:3] == ("remote", "add", "origin")]
    assert urls == ["https://example.internal/a/b.git"]
    assert not any("tok" in part for call in calls for part in call)


def test_credential_helper_answers_git_from_the_environment():
    """Wiring check against real git: the helper must return what we put in the
    child's environment, for a host it has never seen."""
    out = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=example.internal\n\n",
        env={
            **os.environ,
            "QV_GIT_USERNAME": "x-access-token",
            "QV_GIT_PASSWORD": "s3cr3t",
            "GIT_CONFIG_COUNT": "2",
            "GIT_CONFIG_KEY_0": "credential.helper",
            "GIT_CONFIG_VALUE_0": "",
            "GIT_CONFIG_KEY_1": "credential.helper",
            "GIT_CONFIG_VALUE_1": gitsync._CREDENTIAL_HELPER,
        },
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert "username=x-access-token" in out
    assert "password=s3cr3t" in out


def test_git_runs_with_a_closed_stdin():
    """Nothing git asks for can be answered, so stdin must be /dev/null rather
    than the server's — otherwise a prompt blocks the request."""
    empty_blob = "e69de29bb2d1d6434b8b29ae775ad8c2e48c5391"
    assert _run(gitsync._git("hash-object", "--stdin")).strip() == empty_blob


def test_git_times_out_instead_of_hanging(monkeypatch):
    monkeypatch.setattr(gitsync, "_GIT_TIMEOUT_S", 0.2)
    with pytest.raises(GitSyncError) as e:
        _run(gitsync._git("-c", "alias.zzz=!sleep 5", "zzz"))
    assert "timed out" in str(e.value)
    assert e.value.status == 502


# --- Merge-in --------------------------------------------------------------


@pytest.fixture
def other_instance(git_env, wipe_workspace_entities):
    """A second workspace on the same remote, standing in for another
    QueryView that commits to the repo."""
    from queryview.workspaces import create_workspace, delete_workspace, resolve

    _run(create_workspace("gs other", str(git_env), "main"))
    ws = _run(resolve("gs other"))
    yield ws
    wipe_workspace_entities(ws.id)
    _run(delete_workspace("gs other"))
    gitsync.forget(ws.id)


def test_store_retries_once_when_another_instance_pushes_first(other_instance, monkeypatch, git_env):
    _save("gs racer", "<p>1</p>", other_instance.id)
    _save("gs mine", "<p>2</p>")
    real_git, pushes = gitsync._git, []

    async def racing_git(*args, cwd=None, credential=None):
        if args[0] == "push":
            pushes.append(cwd)
            if len(pushes) == 1:  # between our fetch and push, the other instance lands a commit
                await gitsync.store(other_instance, "dashboard", "gs racer")
        return await real_git(*args, cwd=cwd, credential=credential)

    monkeypatch.setattr(gitsync, "_git", racing_git)
    r = _run(gitsync.store(_default_ws(), "dashboard", "gs mine"))

    assert r["committed"] is True
    assert {"kind": "dashboard", "name": "gs racer"} in r["imported"]
    assert len(pushes) == 3  # ours (rejected), theirs, ours again
    log = _remote_log(git_env)
    assert "store dashboard gs racer" in log and "store dashboard gs mine" in log


def test_sync_imports_what_the_repo_has(other_instance):
    from queryview.dashboards import get_dashboard, upsert_dashboard

    _run(upsert_dashboard("gs incoming", "<html>x</html>", {"q": "SELECT 1"}, workspace_id=other_instance.id))
    _run(gitsync.store(other_instance, "dashboard", "gs incoming"))

    r = _run(gitsync.sync(_default_ws()))

    assert {"kind": "dashboard", "name": "gs incoming"} in r["imported"]
    dash = _run(get_dashboard("gs incoming", _default_ws_id()))
    assert dash is not None and dash["html"] == "<html>x</html>" and dash["queries"] == {"q": "SELECT 1"}
    assert r["conflicts"] == []
    assert set(r) == {"imported", "conflicts"}


def test_sync_ignores_a_leftover_queries_dir(git_env, tmp_path):
    """Files from the removed saved-queries layout are neither imported nor an error."""

    def add_query_file(wd: Path) -> None:
        (wd / "queries" / "clickhouse").mkdir(parents=True)
        (wd / "queries" / "clickhouse" / "top errors.yaml").write_text("query_name: top errors\nquery: SELECT 1\n")

    _store_versions("gs beside queries", ["<p>1</p>"])
    _hand_edit(git_env, tmp_path, add_query_file)

    assert _run(gitsync.sync(_default_ws())) == {"imported": [], "conflicts": []}


def test_sync_never_overwrites_and_reports_the_conflict(other_instance):
    from queryview.dashboards import get_dashboard, upsert_dashboard

    _run(upsert_dashboard("gs clash", "<html>mine</html>", {}, workspace_id=_default_ws_id()))
    _run(upsert_dashboard("gs clash", "<html>theirs</html>", {}, workspace_id=other_instance.id))
    _run(gitsync.store(other_instance, "dashboard", "gs clash"))

    r = _run(gitsync.sync(_default_ws()))

    clash = {"kind": "dashboard", "name": "gs clash"}
    assert clash in r["conflicts"]
    assert clash in gitsync.conflicts(_default_ws())  # persists for the UI
    local = _run(get_dashboard("gs clash", _default_ws_id()))
    assert local is not None and local["html"] == "<html>mine</html>"

    # Committing the local copy settles it.
    _run(gitsync.store(_default_ws(), "dashboard", "gs clash"))
    assert clash not in gitsync.conflicts(_default_ws())


def test_restoring_settles_a_conflict(other_instance):
    from queryview.dashboards import get_dashboard, upsert_dashboard

    _run(upsert_dashboard("gs clash2", "<html>mine</html>", {}, workspace_id=_default_ws_id()))
    _run(upsert_dashboard("gs clash2", "<html>theirs</html>", {}, workspace_id=other_instance.id))
    _run(gitsync.store(other_instance, "dashboard", "gs clash2"))
    _run(gitsync.sync(_default_ws()))

    _run(gitsync.restore(_default_ws(), "dashboard", "gs clash2"))

    local = _run(get_dashboard("gs clash2", _default_ws_id()))
    assert local is not None and local["html"] == "<html>theirs</html>"
    assert all(c["name"] != "gs clash2" for c in gitsync.conflicts(_default_ws()))


def test_a_local_edit_on_an_unchanged_repo_copy_is_not_a_conflict(git_env):
    from queryview.dashboards import upsert_dashboard

    _run(upsert_dashboard("gs edited", "<html>v1</html>", {}, workspace_id=_default_ws_id()))
    _run(gitsync.store(_default_ws(), "dashboard", "gs edited"))
    _run(upsert_dashboard("gs edited", "<html>v2, not committed</html>", {}, workspace_id=_default_ws_id()))

    r = _run(gitsync.sync(_default_ws()))

    assert all(c["name"] != "gs edited" for c in r["conflicts"])


def test_an_older_meta_yaml_naming_a_connection_still_reads():
    """Repos written before dashboards dropped their connection keep working;
    the key is ignored."""
    d = dashboard_from_files(
        {"meta.yaml": "name: legacy\nconnection: reporting-db\n", "dashboard.html": "<p/>", "queries.yaml": "{}"}
    )
    assert d == {"name": "legacy", "html": "<p/>", "queries": {}, "params": []}
    assert "connection" not in dashboard_to_files(d)["meta.yaml"]


def test_dashboard_params_round_trip_through_meta_yaml():
    params = [
        {"name": "table", "kind": "identifier", "default": "none", "options_sql": "SELECT name FROM system.tables"},
        {"name": "by_region", "kind": "dimension"},
    ]
    d = {"name": "p", "html": "<p/>", "queries": {"q": "SELECT {by_region} FROM {table}"}, "params": params}
    files = dashboard_to_files(d)
    assert "params:" in files["meta.yaml"]
    assert dashboard_from_files(files) == d
    # A params-free dashboard keeps its meta.yaml to the name alone.
    assert dashboard_to_files({**d, "params": []})["meta.yaml"].strip() == "name: p"


def test_malformed_dashboard_params_are_rejected():
    files = {"meta.yaml": "name: p\nparams:\n- name: x\n  kind: nope\n", "dashboard.html": "", "queries.yaml": ""}
    with pytest.raises(GitSyncError):
        dashboard_from_files(files)


def test_a_dashboard_removed_here_is_not_imported_back(git_env):
    """Gone locally while the repo's copy is the one we last agreed on: a local
    change, so a sync leaves it gone."""
    from sqlalchemy import text

    import queryview.connect as c

    _store_versions("gs gone", ["<p>1</p>"])

    async def remove():
        async with c._engine_for_db().begin() as conn:
            await conn.execute(text("DELETE FROM dashboards WHERE name = 'gs gone'"))

    _run(remove())

    r = _run(gitsync.sync(_default_ws()))

    assert all(e["name"] != "gs gone" for e in r["imported"] + r["conflicts"])
    assert _html("gs gone") is None


def test_restore_by_branch_name_reads_remote_not_stale_local(git_env, tmp_path):
    """A branch *name* resolves against origin/: the local branch only moves
    on store, so after an outside push it is behind the fetched remote."""
    _store_versions("gs byname", ["<p>1</p>"])
    _hand_edit(
        git_env,
        tmp_path,
        lambda wd: (wd / dashboard_reldir("gs byname") / "dashboard.html").write_text("<p>2</p>", encoding="utf-8"),
    )
    _run(gitsync.restore(_default_ws(), "dashboard", "gs byname", ref="main"))
    assert _html("gs byname") == "<p>2</p>"


def _hand_edit(remote, tmp_path, edit: Callable[[Path], object]) -> None:
    """Apply `edit` to a fresh clone's workdir and push it to the remote's
    main, as a change made outside QueryView."""
    wd = Path(tempfile.mkdtemp(prefix="hand-edit-", dir=tmp_path))
    subprocess.run(["git", "clone", "-q", str(remote), str(wd)], check=True, capture_output=True)
    edit(wd)
    for cmd in (
        ["git", "add", "-A"],
        ["git", "-c", "user.name=t", "-c", "user.email=t@localhost", "commit", "-qm", "outside"],
        ["git", "push", "-q", "origin", "main"],
    ):
        subprocess.run(cmd, cwd=wd, check=True, capture_output=True)


def _remove_from_remote(remote, tmp_path, relpath: str) -> None:
    _hand_edit(remote, tmp_path, lambda wd: (wd / relpath).unlink())


def test_restore_of_a_dashboard_missing_a_file_is_404(git_env, tmp_path):
    """A dashboard dir is readable only with all three files: a hand-edited
    repo missing one must not restore the rest over the local dashboard."""
    from queryview.dashboards import get_dashboard, upsert_dashboard

    _run(upsert_dashboard("gs partial", "<html>v1</html>", {"q": "SELECT 1"}, workspace_id=_default_ws_id()))
    _run(gitsync.store(_default_ws(), "dashboard", "gs partial"))
    _remove_from_remote(git_env, tmp_path, f"{dashboard_reldir('gs partial')}/queries.yaml")
    _run(upsert_dashboard("gs partial", "<html>v2</html>", {"q": "SELECT 2"}, workspace_id=_default_ws_id()))

    with pytest.raises(GitSyncError) as e:
        _run(gitsync.restore(_default_ws(), "dashboard", "gs partial"))

    assert e.value.status == 404
    assert "queries.yaml" in str(e.value)
    d = _run(get_dashboard("gs partial", _default_ws_id()))
    assert d is not None and d["html"] == "<html>v2</html>" and d["queries"] == {"q": "SELECT 2"}


def test_sync_skips_a_dashboard_missing_a_file(git_env, other_instance, tmp_path):
    from queryview.dashboards import get_dashboard, upsert_dashboard

    _run(upsert_dashboard("gs halfdash", "<html>x</html>", {"q": "SELECT 1"}, workspace_id=other_instance.id))
    _run(gitsync.store(other_instance, "dashboard", "gs halfdash"))
    _remove_from_remote(git_env, tmp_path, f"{dashboard_reldir('gs halfdash')}/dashboard.html")

    r = _run(gitsync.sync(_default_ws()))

    assert r["imported"] == [] and r["conflicts"] == []
    assert _run(get_dashboard("gs halfdash", _default_ws_id())) is None


def test_restore_of_a_dashboard_missing_meta_names_the_file(git_env, tmp_path):
    from queryview.dashboards import upsert_dashboard

    _run(upsert_dashboard("gs nometa", "<html/>", {"q": "SELECT 1"}, workspace_id=_default_ws_id()))
    _run(gitsync.store(_default_ws(), "dashboard", "gs nometa"))
    _remove_from_remote(git_env, tmp_path, f"{dashboard_reldir('gs nometa')}/meta.yaml")

    with pytest.raises(GitSyncError) as e:
        _run(gitsync.restore(_default_ws(), "dashboard", "gs nometa"))

    assert e.value.status == 404 and "meta.yaml" in str(e.value)
    with pytest.raises(GitSyncError) as e:
        _run(gitsync.restore(_default_ws(), "dashboard", "gs never stored"))
    assert e.value.status == 404 and str(e.value) == "dashboard 'gs never stored' not found at origin/main"
    with pytest.raises(GitSyncError) as e:
        _run(gitsync.restore(_default_ws(), "dashboard", "gs nometa", ref="no-such-ref"))
    assert e.value.status == 404 and str(e.value) == "dashboard 'gs nometa' not found at no-such-ref"


def test_conflicts_of_a_kind_that_no_longer_exists_are_not_reported(git_env):
    """A state file from before only dashboards synced may list other kinds;
    nothing could settle those, so they must not show under the warning."""
    ws = _default_ws()
    gitsync._save_state(
        ws,
        {
            "agreed": {},
            "conflicts": [
                {"kind": "query", "name": "old report", "conn_type": "clickhouse"},
                {"kind": "dashboard", "name": "sales overview"},
            ],
        },
    )
    assert gitsync.conflicts(ws) == [{"kind": "dashboard", "name": "sales overview"}]
