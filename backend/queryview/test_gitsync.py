"""Git sync: serializer round-trips (queries/dashboards <-> repo files) and,
in later tests, store/history/restore against a local bare repo (no network)."""

from __future__ import annotations

import asyncio
import os
import subprocess

import pytest

from queryview import gitsync
from queryview.gitsync import (
    GitSyncError,
    dashboard_from_files,
    dashboard_reldir,
    dashboard_to_files,
    query_from_yaml,
    query_relpath,
    query_to_yaml,
)


def _run(coro):
    return asyncio.run(coro)


def test_relpaths():
    assert query_relpath("clickhouse", "top errors") == "queries/clickhouse/top errors.yaml"
    assert dashboard_reldir("sales/eu") == "dashboards/sales%2Feu"


def test_query_yaml_round_trip():
    row = {
        "query_name": "top errors",
        "query": "SELECT *\nFROM errors\nORDER BY n DESC",
        "cell_view": "cve_id:\n  type: link\n  value: https://x/{cell}\n",
        "order_by": '[{"name": "n", "dir": "DESC"}]',
        "fields": '["cve_id", "n"]',
    }
    text = query_to_yaml(row)
    assert "SELECT *" in text  # multiline SQL is a readable block, not \n escapes
    assert query_from_yaml(text) == row


def test_query_yaml_omits_and_restores_none_fields():
    row = {
        "query_name": "plain",
        "query": "SELECT 1",
        "cell_view": None,
        "order_by": None,
        "fields": None,
    }
    text = query_to_yaml(row)
    assert "cell_view" not in text
    assert query_from_yaml(text) == row


def test_query_from_yaml_rejects_malformed():
    with pytest.raises(GitSyncError):
        query_from_yaml("just a scalar")
    with pytest.raises(GitSyncError):
        query_from_yaml("query_name: x\n")  # no query


def test_dashboard_files_round_trip():
    d = {
        "name": "sales",
        "connection": "prod",
        "html": "<html>\n<body>hi — ünicode</body>\n</html>",
        "queries": {"revenue": "SELECT 1", "multi": "SELECT a\nFROM b"},
    }
    files = dashboard_to_files(d)
    assert set(files) == {"meta.yaml", "dashboard.html", "queries.yaml"}
    assert files["dashboard.html"] == d["html"]  # verbatim
    assert dashboard_from_files(files) == d


def test_dashboard_from_files_rejects_malformed_meta():
    with pytest.raises(GitSyncError):
        dashboard_from_files({"meta.yaml": "connection: x", "dashboard.html": "", "queries.yaml": ""})


# The git_env fixture (bare repo + GIT_SYNC_* env vars) lives in conftest.py.


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


def test_store_unconfigured_is_409():
    # Outside git_env the default workspace has no remote configured.
    with pytest.raises(GitSyncError) as e:
        _run(gitsync.store(_default_ws(), "query", "anything", "clickhouse"))
    assert e.value.status == 409
    assert "no git remote" in str(e.value)


def test_unknown_kind_is_400():
    with pytest.raises(GitSyncError) as e:
        _run(gitsync.store(_default_ws(), "quert", "x", "clickhouse"))
    assert e.value.status == 400
    assert "kind" in str(e.value)


def test_query_without_conn_type_is_400():
    with pytest.raises(GitSyncError) as e:
        _run(gitsync.history(_default_ws(), "query", "x"))
    assert e.value.status == 400
    assert "conn_type" in str(e.value)


def test_store_missing_entity_is_404(git_env):
    with pytest.raises(GitSyncError) as e:
        _run(gitsync.store(_default_ws(), "query", "no such query xyz", "clickhouse"))
    assert e.value.status == 404


def test_store_query_commits_and_pushes(git_env):
    from queryview.queries import save_predefined_query

    _run(save_predefined_query("gs top", "clickhouse", "SELECT 1", workspace_id=_default_ws_id()))
    r = _run(gitsync.store(_default_ws(), "query", "gs top", "clickhouse"))
    assert r["committed"] is True and r["sha"]
    log = _remote_log(git_env)
    assert r["sha"] in log
    assert "store query clickhouse/gs top" in log


def test_store_no_change_makes_no_commit(git_env):
    from queryview.queries import save_predefined_query

    _run(save_predefined_query("gs same", "clickhouse", "SELECT 2", workspace_id=_default_ws_id()))
    r1 = _run(gitsync.store(_default_ws(), "query", "gs same", "clickhouse"))
    r2 = _run(gitsync.store(_default_ws(), "query", "gs same", "clickhouse"))
    assert r1["committed"] is True
    assert r2 == {"committed": False, "sha": None, "message": "no changes"}
    assert _remote_log(git_env).count("\n") == 1  # exactly one commit


def test_store_dashboard_touches_only_its_dir(git_env):
    from queryview.dashboards import upsert_dashboard

    _run(upsert_dashboard("gs dash", "prod", "<html>v1</html>", {"q": "SELECT 1"}, workspace_id=_default_ws_id()))
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
    from queryview.queries import save_predefined_query

    _run(save_predefined_query("gs msg", "clickhouse", "SELECT 3", workspace_id=_default_ws_id()))
    _run(gitsync.store(_default_ws(), "query", "gs msg", "clickhouse", message="before migration"))
    assert "before migration" in _remote_log(git_env)


def test_store_unreachable_remote_raises_without_init(tmp_path, monkeypatch):
    from queryview.queries import save_predefined_query
    from queryview.workspaces import DEFAULT_WORKSPACE, update_workspace

    monkeypatch.setattr(gitsync, "_clone_base", lambda: tmp_path / "clones")
    _run(update_workspace(DEFAULT_WORKSPACE, remote=str(tmp_path / "does-not-exist.git")))
    try:
        _run(save_predefined_query("gs unreachable", "clickhouse", "SELECT 1", workspace_id=_default_ws_id()))
        ws = _default_ws()
        with pytest.raises(GitSyncError) as e:
            _run(gitsync.store(ws, "query", "gs unreachable", "clickhouse"))
        assert e.value.status == 502
        # No spurious local repo in this workspace's clone dir.
        assert not (tmp_path / "clones" / str(ws.id) / ".git").exists()
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


def _store_query_versions(name: str, sqls: list[str]) -> list[str]:
    """Save+store the query once per SQL; returns the commit shas in order."""
    from queryview.queries import save_predefined_query

    shas = []
    for sql in sqls:
        _run(save_predefined_query(name, "clickhouse", sql, workspace_id=_default_ws_id()))
        shas.append(_run(gitsync.store(_default_ws(), "query", name, "clickhouse"))["sha"])
    return shas


def test_history_pages_newest_first(git_env):
    shas = _store_query_versions("gs hist", ["SELECT 1", "SELECT 2", "SELECT 3"])
    page1 = _run(gitsync.history(_default_ws(), "query", "gs hist", "clickhouse", limit=2))
    assert [r["sha"] for r in page1["revisions"]] == [shas[2], shas[1]]
    assert page1["has_more"] is True
    assert all(isinstance(r["date"], int) and r["message"] for r in page1["revisions"])
    page2 = _run(gitsync.history(_default_ws(), "query", "gs hist", "clickhouse", before=shas[1], limit=2))
    assert [r["sha"] for r in page2["revisions"]] == [shas[0]]
    assert page2["has_more"] is False
    # Paging past the oldest commit yields an empty page, not an error.
    page3 = _run(gitsync.history(_default_ws(), "query", "gs hist", "clickhouse", before=shas[0], limit=2))
    assert page3 == {"revisions": [], "has_more": False}


def test_history_garbage_before_is_404(git_env):
    _store_query_versions("gs badbefore", ["SELECT 1"])
    with pytest.raises(GitSyncError) as e:
        _run(gitsync.history(_default_ws(), "query", "gs badbefore", "clickhouse", before="not-a-sha"))
    assert e.value.status == 404


def test_history_only_sees_own_entity(git_env):
    _store_query_versions("gs mine", ["SELECT 1"])
    _store_query_versions("gs other", ["SELECT 9"])
    h = _run(gitsync.history(_default_ws(), "query", "gs mine", "clickhouse"))
    assert len(h["revisions"]) == 1


def test_restore_old_version_overwrites_db_without_moving_head(git_env):
    from queryview.queries import list_predefined_queries

    shas = _store_query_versions("gs restore", ["SELECT 1", "SELECT 2"])
    head_before = _clone_head()
    r = _run(gitsync.restore(_default_ws(), "query", "gs restore", "clickhouse", ref=shas[0]))
    assert r["restored"] is True
    rows = _run(list_predefined_queries("clickhouse", _default_ws_id()))
    row = next(x for x in rows if x["query_name"] == "gs restore")
    assert row["query"] == "SELECT 1"
    assert _clone_head() == head_before  # HEAD never moves


def test_restore_default_ref_is_remote_head(git_env):
    from queryview.queries import list_predefined_queries, save_predefined_query

    _store_query_versions("gs latest", ["SELECT 1", "SELECT 2"])
    _run(save_predefined_query("gs latest", "clickhouse", "SELECT 999", workspace_id=_default_ws_id()))  # local drift
    _run(gitsync.restore(_default_ws(), "query", "gs latest", "clickhouse"))
    rows = _run(list_predefined_queries("clickhouse", _default_ws_id()))
    row = next(x for x in rows if x["query_name"] == "gs latest")
    assert row["query"] == "SELECT 2"


def test_restore_dashboard_round_trip(git_env):
    from queryview.dashboards import get_dashboard, upsert_dashboard

    _run(upsert_dashboard("gs rdash", "prod", "<html>v1</html>", {"q": "SELECT 1"}, workspace_id=_default_ws_id()))
    _run(gitsync.store(_default_ws(), "dashboard", "gs rdash"))
    _run(upsert_dashboard("gs rdash", "other", "<html>v2</html>", {"q": "SELECT 2"}, workspace_id=_default_ws_id()))
    _run(gitsync.restore(_default_ws(), "dashboard", "gs rdash"))
    d = _run(get_dashboard("gs rdash", _default_ws_id()))
    assert d == {
        "name": "gs rdash",
        "connection": "prod",
        "html": "<html>v1</html>",
        "queries": {"q": "SELECT 1"},
    }


def test_restore_missing_at_ref_is_404(git_env):
    _store_query_versions("gs exists", ["SELECT 1"])
    with pytest.raises(GitSyncError) as e:
        _run(gitsync.restore(_default_ws(), "query", "never stored", "clickhouse"))
    assert e.value.status == 404


def _bare(tmp_path, name):
    remote = tmp_path / name
    subprocess.run(
        ["git", "init", "--bare", "-b", "main", str(remote)],
        check=True,
        capture_output=True,
    )
    return remote


def test_store_is_isolated_per_workspace(tmp_path, monkeypatch):
    """A commit in workspace A lands only in A's remote; B's stays empty; a
    workspace without a remote is 409."""
    from queryview.queries import save_predefined_query
    from queryview.workspaces import create_workspace, resolve

    monkeypatch.setattr(gitsync, "_clone_base", lambda: tmp_path / "clones")
    ra, rb = _bare(tmp_path, "a.git"), _bare(tmp_path, "b.git")
    _run(create_workspace("t5-a", remote=str(ra)))
    _run(create_workspace("t5-b", remote=str(rb)))
    _run(create_workspace("t5-none"))
    wa, wb = _run(resolve("t5-a")), _run(resolve("t5-b"))

    _run(save_predefined_query("iso", "clickhouse", "SELECT 1", workspace_id=wa.id))
    r = _run(gitsync.store(wa, "query", "iso", "clickhouse"))
    assert r["committed"] is True
    assert "store query clickhouse/iso" in _remote_log(ra)
    # B's remote has no commits at all (git log fails on an empty bare repo).
    p = subprocess.run(["git", "log", "--format=%H", "main"], cwd=rb, capture_output=True, text=True)
    assert p.returncode != 0

    # And B's history for the same entity name is empty, not A's history.
    _run(save_predefined_query("iso", "clickhouse", "SELECT 2", workspace_id=wb.id))
    h = _run(gitsync.history(wb, "query", "iso", "clickhouse"))
    assert h["revisions"] == []

    wn = _run(resolve("t5-none"))
    with pytest.raises(GitSyncError) as e:
        _run(gitsync.store(wn, "query", "iso", "clickhouse"))
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
    assert gitsync._split_credential(url) == (
        "https://github.com/acme/repo.git",
        ("x-access-token", "ghp_tok"),
    )


def test_split_credential_handles_a_bare_token_and_a_port():
    sanitized, cred = gitsync._split_credential("https://ghp_tok@git.example.internal:8443/a/b.git")
    assert sanitized == "https://git.example.internal:8443/a/b.git"
    assert cred == ("ghp_tok", "")


def test_split_credential_percent_decodes():
    _, cred = gitsync._split_credential("https://user:p%40ss%2Fword@example.internal/r.git")
    assert cred == ("user", "p@ss/word")


def test_split_credential_leaves_ssh_and_plain_urls_alone():
    """`git@host` is an SSH login, not a secret — stripping it breaks the URL."""
    for url in (
        "git@github.com:acme/repo.git",
        "ssh://git@github.com/acme/repo.git",
        "https://github.com/acme/repo.git",
        "/srv/mirrors/repo.git",
    ):
        assert gitsync._split_credential(url) == (url, None)


def test_credential_never_reaches_the_clone_config(tmp_path, monkeypatch):
    """The URL git records must be the sanitized one, so a backup of the data
    dir carries no working credential."""
    calls: list[tuple[str, ...]] = []

    async def fake_git(*args, cwd=None, credential=None):
        calls.append(args)
        if args[0] == "clone":
            raise GitSyncError("branch not found")  # as on a not-yet-created branch
        return ""  # ls-remote: no heads -> empty remote -> init + `remote add`

    monkeypatch.setattr(gitsync, "_git", fake_git)
    monkeypatch.setattr(gitsync, "_clone_base", lambda: tmp_path / "clones")
    ws = gitsync.WorkspaceRec(id=99, name="w", branch="main", remote="https://tok@example.internal/a/b.git")

    _run(gitsync._ensure_repo(ws))

    urls = [a[-1] for a in calls if a[:3] == ("remote", "add", "origin")]
    assert urls == ["https://example.internal/a/b.git"]
    assert not any("tok" in part for call in calls for part in call)


def test_credential_helper_answers_git_from_the_environment():
    """Wiring check against real git: the helper must return what we put in the
    child's environment, for a host it has never seen."""
    out = subprocess.run(
        [
            "git",
            "-c",
            "credential.helper=",
            "-c",
            f"credential.helper={gitsync._CREDENTIAL_HELPER}",
            "credential",
            "fill",
        ],
        input="protocol=https\nhost=example.internal\n\n",
        env={**os.environ, "QV_GIT_USERNAME": "x-access-token", "QV_GIT_PASSWORD": "s3cr3t"},
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
