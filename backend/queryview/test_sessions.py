"""Session store: rows persist UI state, labels are pinned or ordinal, and a
held session refuses deletion."""

from __future__ import annotations

import asyncio

from queryview import sessions
from queryview.connect import _now_ms as _now_ms_for_test


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
    assert _run(sessions.patch_session(rec.id, url="/explorer?table=events", workspace="reporting")) is not None
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


def test_patch_unknown_session_returns_none():
    assert _run(sessions.patch_session("nope", url="/queries")) is None


def test_patch_returns_the_updated_record():
    """Callers read server-derived values off the result — an empty label unpins,
    and the derived label is what the switcher then shows."""
    rec = _run(sessions.create_session())
    _run(sessions.set_connection(rec.id, "reporting"))
    _run(sessions.set_database(rec.id, "events"))
    pinned = _run(sessions.patch_session(rec.id, label="nightly audit"))
    assert pinned is not None
    assert sessions.display_label(pinned) == "nightly audit"

    unpinned = _run(sessions.patch_session(rec.id, label=""))
    assert unpinned is not None
    assert unpinned.label is None
    assert sessions.display_label(unpinned) == f"Session {rec.seq}"


def test_delete_removes_the_row():
    rec = _run(sessions.create_session())
    ok, _ = _run(sessions.delete_session(rec.id))
    assert ok
    assert _run(sessions.get_session_rec(rec.id)) is None


def test_label_is_the_ordinal_whatever_the_connection():
    rec = _run(sessions.create_session())
    rec.connection_name, rec.database = "reporting", "events"
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


# --- claim protocol ---------------------------------------------------------


def _free_everything():
    """Delete every session so a test starts from a known, unheld world."""

    async def go():
        from sqlmodel import select as _select
        from sqlmodel.ext.asyncio.session import AsyncSession as _S

        from queryview.connect import _engine_for_db, _ensure_schema

        await _ensure_schema()
        async with _S(_engine_for_db()) as s:
            for row in (await s.exec(_select(sessions.Session))).all():
                await s.delete(row)
            await s.commit()

    _run(go())


def test_attach_without_an_id_creates_when_there_is_nothing():
    _free_everything()
    rec, created = _run(sessions.attach("tab-a", None))
    assert created is True
    assert rec.held is True


def test_attach_with_own_id_reclaims_the_same_session():
    _free_everything()
    first, _ = _run(sessions.attach("tab-a", None))
    again, created = _run(sessions.attach("tab-a", first.id))
    assert created is False
    assert again.id == first.id


def test_a_released_session_is_resumed_by_the_next_tab():
    """Close the tab, open a new one: the session comes back."""
    _free_everything()
    first, _ = _run(sessions.attach("tab-a", None))
    _run(sessions.release("tab-a"))
    resumed, created = _run(sessions.attach("tab-b", None))
    assert created is False
    assert resumed.id == first.id


def test_attach_resumes_the_most_recent_unheld_session():
    _free_everything()
    older = _run(sessions.create_session())
    newer = _run(sessions.create_session())
    now = _now_ms_for_test()
    # Two creates can land in the same millisecond, so order them explicitly.
    _run(sessions.touch_for_test(older.id, last_active_at=now - 60_000))
    _run(sessions.touch_for_test(newer.id, last_active_at=now))

    resumed, created = _run(sessions.attach("tab-c", None))

    assert created is False
    assert resumed.id == newer.id
    assert resumed.id != older.id


def test_attach_creates_a_new_session_when_the_last_one_is_held():
    _free_everything()
    held, _ = _run(sessions.attach("tab-a", None))
    fresh, created = _run(sessions.attach("tab-b", None))
    assert created is True
    assert fresh.id != held.id


def test_attach_with_an_id_held_by_another_tab_does_not_hijack():
    """A duplicated tab copies sessionStorage, so it arrives with someone
    else's id; it must get its own session instead of stealing one."""
    _free_everything()
    held, _ = _run(sessions.attach("tab-a", None))
    dup, created = _run(sessions.attach("tab-b", held.id))
    assert created is True
    assert dup.id != held.id


def test_a_stale_claim_is_reclaimable():
    _free_everything()
    stale, _ = _run(sessions.attach("tab-a", None))
    _run(sessions.touch_for_test(stale.id, claim_seen_at=_now_ms_for_test() - sessions.SESSION_CLAIM_TTL_MS - 1))
    taken, created = _run(sessions.attach("tab-b", None))
    assert created is False
    assert taken.id == stale.id


def test_release_frees_the_tab_claim():
    _free_everything()
    rec, _ = _run(sessions.attach("tab-a", None))
    _run(sessions.release("tab-a"))
    after = _run(sessions.get_session_rec(rec.id))
    assert after is not None
    assert after.held is False


def test_select_switches_and_frees_the_previous_one():
    _free_everything()
    first, _ = _run(sessions.attach("tab-a", None))
    second = _run(sessions.create_session())
    got, _ = _run(sessions.select_session("tab-a", second.id))
    assert got is not None
    assert got.id == second.id
    previous = _run(sessions.get_session_rec(first.id))
    assert previous is not None
    assert previous.held is False


def test_select_none_creates_a_new_session():
    _free_everything()
    first, _ = _run(sessions.attach("tab-a", None))
    got, _ = _run(sessions.select_session("tab-a", None))
    assert got is not None
    assert got.id != first.id
    assert got.held is True


def test_select_none_does_not_resume_a_released_session():
    """Unlike attach, which hands a new tab the last released session with its
    saved state. The e2e fixture relies on this for per-test isolation."""
    _free_everything()
    left, _ = _run(sessions.attach("tab-a", None))
    _run(sessions.patch_session(left.id, ui={"query": {"sql": "SELECT 1"}}))
    _run(sessions.release("tab-a"))
    got, _ = _run(sessions.select_session("tab-b", None))
    assert got is not None
    assert got.id != left.id
    assert got.ui == {}


def test_select_refuses_a_session_held_by_another_tab():
    _free_everything()
    held, _ = _run(sessions.attach("tab-a", None))
    _run(sessions.attach("tab-b", None))
    got, reason = _run(sessions.select_session("tab-b", held.id))
    assert got is None
    assert reason == "held"


def test_delete_refuses_while_held():
    _free_everything()
    held, _ = _run(sessions.attach("tab-a", None))
    ok, reason = _run(sessions.delete_session(held.id))
    assert ok is False
    assert reason == "held"
