"""Session store: rows persist UI state, labels derive from connection state,
and a held session refuses deletion."""

from __future__ import annotations

import asyncio

from queryview import sessions


def _run(coro):
    return asyncio.run(coro)


def test_create_assigns_increasing_seq():
    a = _run(sessions.create_session())
    b = _run(sessions.create_session())
    assert b.seq == a.seq + 1
    assert a.id != b.id


def test_new_session_defaults():
    rec = _run(sessions.create_session())
    assert rec.connection_name is None
    assert rec.database is None
    assert rec.workspace == "default"
    assert rec.url == "/queries"
    assert rec.ui == {}
    assert rec.held is False


def test_patch_round_trips_url_and_workspace():
    rec = _run(sessions.create_session())
    assert _run(sessions.patch_session(rec.id, url="/explorer?table=events", workspace="reporting"))
    again = _run(sessions.get_session_rec(rec.id))
    assert again is not None
    assert again.url == "/explorer?table=events"
    assert again.workspace == "reporting"


def test_patch_ui_merges_per_view_and_keeps_unknown_keys():
    rec = _run(sessions.create_session())
    _run(sessions.patch_session(rec.id, ui={"query": {"sql": "SELECT 1", "limit": 100}}))
    _run(sessions.patch_session(rec.id, ui={"query": {"limit": 50}, "explorer": {"sidebarWidth": 412}}))
    again = _run(sessions.get_session_rec(rec.id))
    assert again is not None
    # The view namespace merges; the untouched sibling key survives.
    assert again.ui["query"] == {"sql": "SELECT 1", "limit": 50}
    assert again.ui["explorer"] == {"sidebarWidth": 412}


def test_patch_unknown_session_returns_false():
    assert _run(sessions.patch_session("nope", url="/queries")) is False


def test_delete_removes_the_row():
    rec = _run(sessions.create_session())
    ok, _ = _run(sessions.delete_session(rec.id))
    assert ok
    assert _run(sessions.get_session_rec(rec.id)) is None


def test_label_prefers_connection_and_database():
    rec = _run(sessions.create_session())
    rec.connection_name, rec.database = "reporting", "events"
    assert sessions.display_label(rec) == "reporting · events"


def test_label_falls_back_to_connection_then_seq():
    rec = _run(sessions.create_session())
    rec.connection_name, rec.database = "reporting", None
    assert sessions.display_label(rec) == "reporting"
    rec.connection_name = None
    assert sessions.display_label(rec) == f"Session {rec.seq}"


def test_explicit_label_wins():
    rec = _run(sessions.create_session())
    rec.label, rec.connection_name, rec.database = "nightly audit", "reporting", "events"
    assert sessions.display_label(rec) == "nightly audit"


def test_list_returns_display_label_and_held_flag():
    rec = _run(sessions.create_session())
    rows = _run(sessions.list_sessions())
    row = next(r for r in rows if r["id"] == rec.id)
    assert row["label"] == f"Session {rec.seq}"
    assert row["held"] is False
