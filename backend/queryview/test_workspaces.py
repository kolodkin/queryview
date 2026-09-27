"""Workspace store: CRUD, name rules, encrypted-remote round trip, and the
delete-refuses-on-non-empty rule. The 'default' workspace is seeded by the
migration and is an ordinary row."""

from __future__ import annotations

import asyncio
import sqlite3

import pytest

from queryview.connect import _db_path
from queryview.workspaces import (
    DEFAULT_WORKSPACE,
    WorkspaceError,
    create_workspace,
    delete_workspace,
    list_workspaces,
    resolve,
    update_workspace,
)


def _run(coro):
    return asyncio.run(coro)


def test_default_workspace_is_seeded():
    rec = _run(resolve(DEFAULT_WORKSPACE))
    assert rec.name == "default"
    assert isinstance(rec.id, int)


def test_resolve_unknown_is_404():
    with pytest.raises(WorkspaceError) as e:
        _run(resolve("no-such-ws"))
    assert e.value.status == 404


def test_create_list_and_encrypted_remote_round_trip():
    _run(create_workspace("t2-crt", remote="https://u:tok@example.test/r.git", branch="dev"))
    rec = _run(resolve("t2-crt"))
    assert rec.remote == "https://u:tok@example.test/r.git"  # decrypted for gitsync
    assert rec.branch == "dev"

    listed = {w["name"]: w for w in _run(list_workspaces())}
    assert listed["t2-crt"] == {
        "name": "t2-crt",
        "branch": "dev",
        "configured": True,
        # Shown without the credential, which never leaves the server.
        "remote": "https://example.test/r.git",
    }
    assert "tok" not in str(listed["t2-crt"])  # the credential never leaves the store

    # At rest the remote is ciphertext, not the URL.
    con = sqlite3.connect(_db_path())
    try:
        stored = con.execute("SELECT remote FROM workspaces WHERE name='t2-crt'").fetchone()[0]
    finally:
        con.close()
    assert "example.test" not in stored


def test_create_duplicate_is_409_and_bad_names_400():
    _run(create_workspace("t2-dup"))
    with pytest.raises(WorkspaceError) as e:
        _run(create_workspace("t2-dup"))
    assert e.value.status == 409
    with pytest.raises(WorkspaceError) as e:
        _run(create_workspace("   "))
    assert e.value.status == 400
    with pytest.raises(WorkspaceError) as e:
        _run(create_workspace("a/b"))  # names travel in URL paths
    assert e.value.status == 400


def test_update_rename_set_and_clear_remote():
    _run(create_workspace("t2-upd", remote="https://example.test/a.git"))
    _run(update_workspace("t2-upd", new_name="t2-upd2", branch="rel"))
    rec = _run(resolve("t2-upd2"))
    assert rec.branch == "rel" and rec.remote == "https://example.test/a.git"  # remote untouched
    _run(update_workspace("t2-upd2", remote=None))
    assert _run(resolve("t2-upd2")).remote is None
    with pytest.raises(WorkspaceError) as e:
        _run(update_workspace("t2-upd2", new_name=DEFAULT_WORKSPACE))
    assert e.value.status == 409


def test_delete_refuses_non_empty_then_deletes_empty():
    _run(create_workspace("t2-del"))
    rec = _run(resolve("t2-del"))
    con = sqlite3.connect(_db_path())
    try:
        con.execute(
            "INSERT INTO predefined_queries (query_name, type, query, workspace_id) "
            "VALUES ('held', 'clickhouse', 'SELECT 1', ?)",
            (rec.id,),
        )
        con.commit()
    finally:
        con.close()
    with pytest.raises(WorkspaceError) as e:
        _run(delete_workspace("t2-del"))
    assert e.value.status == 409

    con = sqlite3.connect(_db_path())
    try:
        con.execute("DELETE FROM predefined_queries WHERE workspace_id=?", (rec.id,))
        con.commit()
    finally:
        con.close()
    _run(delete_workspace("t2-del"))
    with pytest.raises(WorkspaceError):
        _run(resolve("t2-del"))
