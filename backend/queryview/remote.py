"""In-memory push hub for remote control: one message queue per armed browser
channel, keyed by the session id the channel belongs to. SSE framing and disconnect handling live
in main.py."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

from .validation import cell_view_error, presentation_error

LOCK_TTL_SECONDS = 30.0
# How long a tab's channel waits for its browser tab to open and arm.
PENDING_TTL_SECONDS = 60.0


@dataclass
class _Channel:
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)
    # Advisory edit lock: "human" | "agent" | None. lock_touched is a monotonic
    # timestamp refreshed on acquire; a human lock older than LOCK_TTL_SECONDS is
    # treated as released (heartbeat lapsed / tab froze).
    lock_owner: str | None = None
    lock_touched: float = 0.0
    # A tab's channel opened before its browser tab armed (docs/remote.md#tabs):
    # pushes queue up and answer "queued for the tab" until `register` takes
    # it over.
    pending_since: float | None = None


# session id -> channel. Module-level, like connect.py's _sessions.
_channels: dict[str, _Channel] = {}


def _live(remote_id: str) -> _Channel | None:
    """The channel, unless it is a pending one whose tab never came: dropped."""
    channel = _channels.get(remote_id)
    if (
        channel is not None
        and channel.pending_since is not None
        and time.monotonic() - channel.pending_since >= PENDING_TTL_SECONDS
    ):
        del _channels[remote_id]
        return None
    return channel


def _human_holds(channel: _Channel) -> bool:
    return channel.lock_owner == "human" and (time.monotonic() - channel.lock_touched) < LOCK_TTL_SECONDS


def acquire(remote_id: str, owner: str) -> tuple[bool, str]:
    """Take (or refresh) the edit lock for `owner`. Succeeds if free, already
    yours, or the current holder's TTL has lapsed. Otherwise returns the
    owner-named block reason."""
    channel = _live(remote_id)
    if channel is None:
        return False, "unknown or inactive session"
    now = time.monotonic()
    expired = (now - channel.lock_touched) >= LOCK_TTL_SECONDS
    if channel.lock_owner in (None, owner) or expired:
        channel.lock_owner = owner
        channel.lock_touched = now
        return True, "acquired"
    who = "user" if channel.lock_owner == "human" else "agent"
    return False, f"blocked, {who} editing"


def release(remote_id: str, owner: str) -> tuple[bool, str]:
    """Release the lock only if `owner` holds it (idempotent)."""
    channel = _live(remote_id)
    if channel is None:
        return False, "unknown or inactive session"
    if channel.lock_owner == owner:
        channel.lock_owner = None
    return True, "released"


def is_armed(session_id: str) -> bool:
    channel = _live(session_id)
    return channel is not None and channel.pending_since is None


def open_pending(session_id: str) -> None:
    """A channel for a tab whose browser tab is not open yet, unless one is
    already open or pending: pushes queue for it meanwhile."""
    if _live(session_id) is None:
        _channels[session_id] = _Channel(pending_since=time.monotonic())


def register(session_id: str) -> str:
    """Open a channel for a newly-armed session, keyed by the session's own id;
    a pending one is taken over, its queued pushes first in line. Arming is the
    gate: `unregister` on disarm makes every later push fail, so a shared id
    grants nothing once the session is disarmed."""
    channel = _live(session_id)
    if channel is not None and channel.pending_since is not None:
        channel.pending_since = None
    else:
        _channels[session_id] = _Channel()
    return session_id


def unregister(remote_id: str) -> None:
    """Drop a channel (idempotent)."""
    _channels.pop(remote_id, None)


def push(remote_id: str, payload: dict[str, Any]) -> tuple[bool, str]:
    """Validate + lock-check + enqueue a payload for a channel. Ordered:
    unknown session -> invalid presentation -> human holds lock -> deliver."""
    channel = _live(remote_id)
    if channel is None:
        return False, "unknown or inactive session"
    err = presentation_error(payload.get("order_by"), payload.get("fields")) or cell_view_error(
        payload.get("cell_view")
    )
    if err is not None:
        return False, err
    if _human_holds(channel):
        return False, "blocked, user editing"
    channel.queue.put_nowait(payload)
    return True, "delivered" if channel.pending_since is None else "queued for the tab"


def notify(remote_id: str, payload: dict[str, Any]) -> None:
    """Best-effort UI refresh hint: no validation or lock, a no-op when unarmed."""
    channel = _live(remote_id)
    if channel is not None:
        channel.queue.put_nowait(payload)


async def next_message(remote_id: str, timeout: float) -> dict[str, Any] | None:
    """Wait up to `timeout` seconds for the next payload on a channel. Returns
    None on timeout or if the channel is gone."""
    channel = _live(remote_id)
    if channel is None:
        return None
    try:
        return await asyncio.wait_for(channel.queue.get(), timeout)
    except TimeoutError:
        return None
