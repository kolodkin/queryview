import asyncio
import time
import uuid

from fastapi.testclient import TestClient

from queryview import remote, sessions
from queryview.main import app

# Any typed payload: the hub delivers it as is.
_PUSH = {"type": "script", "sql": "SELECT 1", "run": False}


def test_register_returns_the_session_id_it_was_given():
    rid = uuid.uuid4().hex
    assert remote.register(rid) == rid
    remote.unregister(rid)


def test_push_to_registered_session_delivers():
    rid = remote.register(uuid.uuid4().hex)
    try:
        ok, msg = remote.push(rid, _PUSH)
        assert ok is True
        msg_in = asyncio.run(remote.next_message(rid, 1.0))
        assert msg_in == _PUSH
    finally:
        remote.unregister(rid)


def test_push_to_unknown_session_fails():
    ok, msg = remote.push("deadbeef", _PUSH)
    assert ok is False
    assert "unknown" in msg.lower()


def test_unregister_makes_push_fail():
    rid = remote.register(uuid.uuid4().hex)
    remote.unregister(rid)
    ok, _ = remote.push(rid, _PUSH)
    assert ok is False


def test_next_message_times_out_to_none():
    rid = remote.register(uuid.uuid4().hex)
    try:
        assert asyncio.run(remote.next_message(rid, 0.05)) is None
    finally:
        remote.unregister(rid)


def test_lock_endpoint_acquire_blocks_push():

    rid = remote.register(uuid.uuid4().hex)
    try:
        client = TestClient(app)
        r = client.post("/api/remote/lock", json={"session_id": rid, "action": "acquire"})
        assert r.json()["ok"] is True
        ok, msg = remote.push(rid, _PUSH)
        assert ok is False and msg == "blocked, user editing"
        r = client.post("/api/remote/lock", json={"session_id": rid, "action": "release"})
        assert r.json()["ok"] is True
        ok, _ = remote.push(rid, _PUSH)
        assert ok is True
    finally:
        remote.unregister(rid)


def test_lock_endpoint_bad_action_400():

    rid = remote.register(uuid.uuid4().hex)
    try:
        client = TestClient(app)
        r = client.post("/api/remote/lock", json={"session_id": rid, "action": "nope"})
        assert r.status_code == 400
    finally:
        remote.unregister(rid)


def test_acquire_blocks_push_then_release_allows():
    rid = remote.register(uuid.uuid4().hex)
    try:
        ok, _ = remote.acquire(rid, "human")
        assert ok is True
        ok, msg = remote.push(rid, _PUSH)
        assert ok is False and msg == "blocked, user editing"
        remote.release(rid, "human")
        ok, msg = remote.push(rid, _PUSH)
        assert ok is True and msg == "delivered"
    finally:
        remote.unregister(rid)


def test_lock_ttl_expiry_allows_push():
    rid = remote.register(uuid.uuid4().hex)
    try:
        remote.acquire(rid, "human")
        # Simulate the heartbeat lapsing: age the lock past its TTL.
        remote._channels[rid].lock_touched = time.monotonic() - (remote.LOCK_TTL_SECONDS + 1)
        ok, msg = remote.push(rid, _PUSH)
        assert ok is True and msg == "delivered"
    finally:
        remote.unregister(rid)


def test_release_by_nonowner_is_noop():
    rid = remote.register(uuid.uuid4().hex)
    try:
        remote.acquire(rid, "human")
        remote.release(rid, "agent")  # wrong owner: must not clear
        ok, msg = remote.push(rid, _PUSH)
        assert ok is False and msg == "blocked, user editing"
    finally:
        remote.unregister(rid)


# --- the channel is the session ------------------------------------------


def test_register_keys_the_channel_by_the_session_id():
    rec = asyncio.run(sessions.create_session())
    remote.register(rec.id)
    try:
        ok, message = remote.push(rec.id, _PUSH)
        assert ok, message
    finally:
        remote.unregister(rec.id)


def test_push_to_an_unarmed_session_is_refused():
    """Disarming still revokes: the id alone is not access."""
    rec = asyncio.run(sessions.create_session())
    remote.unregister(rec.id)
    ok, message = remote.push(rec.id, _PUSH)
    assert ok is False
    assert message == "unknown or inactive session"


def test_push_dashboard_reads_the_database_from_the_session_row():
    """The browser no longer mirrors its database into the channel; the agent
    reads the session the channel is named after."""
    from queryview.mcp_server import push_dashboard

    rec = asyncio.run(sessions.create_session())
    asyncio.run(sessions.set_connection(rec.id, "reporting"))
    asyncio.run(sessions.set_database(rec.id, "sales_reporting"))
    remote.register(rec.id)
    try:
        out = asyncio.run(push_dashboard(rec.id, "<p/>", {"q": "SELECT 1"}))
        assert out["ok"] is True
        assert out["database"] == "sales_reporting"
    finally:
        remote.unregister(rec.id)


def test_a_pending_channel_queues_pushes_until_the_tab_arms():
    sid = uuid.uuid4().hex
    try:
        remote.open_pending(sid)
        assert remote.is_armed(sid) is False
        first = {"type": "script", "sql": "SELECT 1", "run": False}
        second = {"type": "script", "sql": "SELECT 2", "run": False}
        assert remote.push(sid, first) == (True, "queued for the tab")
        assert remote.push(sid, second) == (True, "queued for the tab")
        # Arming takes the pending channel over, queued pushes first in line.
        remote.register(sid)
        assert remote.is_armed(sid)
        assert asyncio.run(remote.next_message(sid, 1.0)) == first
        assert asyncio.run(remote.next_message(sid, 1.0)) == second
        assert remote.push(sid, first) == (True, "delivered")
    finally:
        remote.unregister(sid)


def test_a_pending_channel_whose_tab_never_came_is_dropped(monkeypatch):
    sid = uuid.uuid4().hex
    remote.open_pending(sid)
    monkeypatch.setattr(remote, "PENDING_TTL_SECONDS", 0.0)
    assert remote.push(sid, {"type": "script", "sql": "SELECT 1", "run": False}) == (
        False,
        "unknown or inactive session",
    )
    assert sid not in remote._channels
