"""The viewer server's repo reader: the dashboards at the branch head, kept
in memory and refreshed by polling (docs/system/viewer_server.md)."""

from __future__ import annotations

import asyncio
import shutil

import pytest

from queryview.gitsync import GitSyncError, dashboard_to_files
from queryview.server.repo import Repo

SALES = {"name": "sales", "html": "<p>hi</p>", "queries": {"q": "SELECT 1 AS n"}, "params": []}
OPS = {"name": "ops/eu", "html": "<p>ops</p>", "queries": {}, "params": [{"name": "r", "options": ["eu"]}]}


def _run(coro):
    return asyncio.run(coro)


def _repo(dash_repo) -> Repo:
    return Repo(str(dash_repo.remote), "main")


def test_reads_the_dashboards_at_the_head(dash_repo):
    dash_repo.commit([SALES, OPS])
    repo = _repo(dash_repo)
    assert _run(repo.refresh()) is True
    assert repo.names() == ["ops/eu", "sales"]
    assert repo.get("sales") == SALES and repo.get("ops/eu") == OPS
    assert repo.get("nope") is None


def test_refresh_is_false_when_nothing_moved(dash_repo):
    dash_repo.commit([SALES])
    repo = _repo(dash_repo)
    assert _run(repo.refresh()) is True
    assert _run(repo.refresh()) is False


def test_picks_up_a_new_commit(dash_repo):
    dash_repo.commit([SALES])
    repo = _repo(dash_repo)
    _run(repo.refresh())
    dash_repo.commit([OPS], remove=["sales"])
    assert _run(repo.refresh()) is True
    assert repo.names() == ["ops/eu"]


def test_an_edit_replaces_the_dashboard(dash_repo):
    dash_repo.commit([SALES])
    repo = _repo(dash_repo)
    _run(repo.refresh())
    dash_repo.commit([{**SALES, "html": "<p>new</p>"}])
    _run(repo.refresh())
    assert (repo.get("sales") or {}).get("html") == "<p>new</p>"


def test_an_empty_remote_lists_nothing(dash_repo):
    repo = _repo(dash_repo)
    _run(repo.refresh())
    assert repo.names() == []
    dash_repo.commit([SALES])  # the first commit then shows up
    assert _run(repo.refresh()) is True and repo.names() == ["sales"]


def test_a_dashboard_without_meta_yaml_is_named_by_its_folder(dash_repo):
    plain = {"dashboards/plain%2Feu/dashboard.html": "<p>p</p>", "dashboards/plain%2Feu/queries.yaml": "{}\n"}
    dash_repo.commit(raw=plain)
    repo = _repo(dash_repo)
    _run(repo.refresh())
    assert repo.get("plain/eu") == {"name": "plain/eu", "html": "<p>p</p>", "queries": {}, "params": []}


def test_a_malformed_dashboard_is_skipped(dash_repo):
    bad = {
        "dashboards/bad/meta.yaml": "params: [",
        "dashboards/bad/dashboard.html": "",
        "dashboards/bad/queries.yaml": "",
    }
    dash_repo.commit([SALES], raw=bad)
    repo = _repo(dash_repo)
    _run(repo.refresh())
    assert repo.names() == ["sales"]


def test_a_failed_fetch_keeps_the_last_copy(dash_repo):
    dash_repo.commit([SALES])
    repo = _repo(dash_repo)
    _run(repo.refresh())
    shutil.rmtree(dash_repo.remote)
    with pytest.raises(GitSyncError):
        _run(repo.refresh())
    assert repo.names() == ["sales"]


def test_a_start_re_clones_over_a_clone_left_by_another_remote(dash_repo, tmp_path):
    dash_repo.commit([SALES])
    _run(_repo(dash_repo).refresh())
    shutil.copytree(dash_repo.remote, tmp_path / "other.git")
    dash_repo.commit([OPS], remove=["sales"])  # the first remote moves on; the copy still holds sales
    fresh = Repo(str(tmp_path / "other.git"), "main")
    _run(fresh.refresh())
    assert fresh.names() == ["sales"]


def test_fetch_errors_hide_the_token(clone_base):
    repo = Repo("https://user:tok-example@127.0.0.1:1/dashboards.git", "main")
    with pytest.raises(GitSyncError) as e:
        _run(repo.refresh())
    assert "tok-example" not in str(e.value)


def test_a_copied_folder_is_its_own_dashboard(dash_repo):
    """The folder is the name, so a copy can't share one with its source."""
    files = dashboard_to_files({**SALES, "html": "<p>copy</p>"})
    dash_repo.commit([SALES], raw={f"dashboards/sales_copy/{f}": text for f, text in files.items()})
    repo = _repo(dash_repo)
    _run(repo.refresh())
    assert repo.names() == ["sales", "sales_copy"] and repo.get("sales") == SALES
    assert repo.get("sales_copy") == {**SALES, "name": "sales_copy", "html": "<p>copy</p>"}
