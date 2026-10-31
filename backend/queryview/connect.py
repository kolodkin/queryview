"""Connection domain: the SQLModel/SQLite connection store (configs encrypted
at rest) and per-session active connections. No HTTP concerns here — operations
return plain results that main.py maps to responses. Per-backend execution is
delegated to the driver registry; nothing here is ClickHouse-specific."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from collections import OrderedDict
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Literal

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Field, SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from alembic.config import Config

from .drivers import DRIVERS
from .drivers.base import (
    DEFAULT_LIST_LIMIT,
    MAX_LIST_LIMIT,
    DatabasesResult,
    DriverConfig,
    Err,
    RowsResult,
    error_message,
    select_all_sql,
)

# --- Storage (SQLite, lazily opened) --------------------------------------


class Connection(SQLModel, table=True):
    __tablename__: ClassVar[str] = "connections"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    type: str = Field(default="clickhouse", index=True)
    config: str  # base64(AES-GCM(json.dumps(driver config))) — never plaintext
    database: str | None = Field(default=None)
    last_active_at: int  # unix ms; the max is the "latest active"
    lock_hash: str | None = Field(default=None)  # salt$scrypt of the passphrase; null when unlocked


def _data_dir() -> Path:
    """Every piece of state lives here: DATA_DIR, else `~/.queryview` — the same
    path on every OS, and the image's mount point, so a local run and a container
    share state. Deliberately not package-relative: that put the DB in
    site-packages, which is uv's disposable cache under `uvx`."""
    env = os.environ.get("DATA_DIR")
    return Path(env) if env else Path.home() / ".queryview"


def _db_path() -> Path:
    """The SQLite store: a fixed name in the data dir — move the dir, not it."""
    return _data_dir() / "db.sqlite"


_engine = None
_schema_ready = False


def _engine_for_db():
    """The async SQLAlchemy engine (aiosqlite), memoized and lazy — no file is
    touched until the first query, so importing this module is side-effect-free."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(f"sqlite+aiosqlite:///{_db_path()}")
    return _engine


def _alembic_config() -> Config:
    """Alembic Config built in code (not a cwd alembic.ini) so migrations run from
    any directory and from the packaged wheel. Points at the package's migrations
    dir and injects a *sync* SQLite URL for the current data dir."""
    from alembic.config import Config

    cfg = Config()
    cfg.set_main_option("script_location", str(Path(__file__).resolve().parent / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{_db_path()}")
    return cfg


async def _ensure_schema() -> None:
    """Migrate the DB to head on first use (idempotent). Single-process by design
    (SQLite is single-writer), so no cross-process lock is needed. Runs the sync
    Alembic upgrade inline — blocking is intended for this startup step."""
    global _schema_ready
    if _schema_ready:
        return
    from alembic import command

    # SQLite won't create a missing parent, and the data dir doesn't exist on a
    # fresh install; the key file and git-sync clones land here too.
    _data_dir().mkdir(parents=True, exist_ok=True)
    command.upgrade(_alembic_config(), "head")
    _schema_ready = True


# --- Config encryption at rest (AES-256-GCM) ------------------------------
# Key from DB_ENCRYPTION_KEY (base64, 32 bytes) or a generated local key file
# next to the DB (gitignored). Stored value is base64(iv ‖ ciphertext); AES-GCM
# appends its 16-byte tag to the ciphertext.


def _key_path() -> Path:
    return _data_dir() / "encryption.key"


_key: bytes | None = None


def _load_or_create_key() -> bytes:
    env_key = os.environ.get("DB_ENCRYPTION_KEY")
    if env_key:
        return base64.b64decode(env_key)
    path = _key_path()
    try:
        return path.read_bytes()
    except FileNotFoundError:
        raw = os.urandom(32)
        path.write_bytes(raw)
        os.chmod(path, 0o600)
        return raw


def _key_bytes() -> bytes:
    global _key
    if _key is None:
        _key = _load_or_create_key()
    return _key


def _encrypt_str(plain: str) -> str:
    iv = os.urandom(12)
    ct = AESGCM(_key_bytes()).encrypt(iv, plain.encode("utf-8"), None)
    return base64.b64encode(iv + ct).decode("ascii")


def _decrypt_str(stored: str) -> str:
    combined = base64.b64decode(stored)
    iv, ct = combined[:12], combined[12:]
    return AESGCM(_key_bytes()).decrypt(iv, ct, None).decode("utf-8")


@dataclass
class StoredConnection:
    name: str
    type: str
    config: DriverConfig
    database: str | None


async def _save_active_connection(name: str, config: DriverConfig, conn_type: str) -> None:
    blob = _encrypt_str(json.dumps(DRIVERS[conn_type].config_to_dict(config)))
    now = _now_ms()
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        row = (await s.exec(select(Connection).where(Connection.name == name))).first()
        if row is None:
            row = Connection(name=name, type=conn_type, config=blob, last_active_at=now)
        else:
            # Upsert by name; the selected database is intentionally left as-is.
            row.type = conn_type
            row.config = blob
            row.last_active_at = now
        s.add(row)
        await s.commit()


async def _save_selected_database(name: str, database: str) -> None:
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        row = (await s.exec(select(Connection).where(Connection.name == name))).first()
        if row is not None:
            row.database = database
            s.add(row)
            await s.commit()


def _row_to_stored(row: Connection | None) -> StoredConnection | None:
    if row is None:
        return None
    try:
        data = json.loads(_decrypt_str(row.config))
        config = DRIVERS[row.type].config_from_dict(data)
    except Exception:
        # Unreadable (key changed / legacy) or unknown type — treat as unavailable.
        return None
    return StoredConnection(
        name=row.name,
        type=row.type,
        config=config,
        database=row.database,
    )


async def list_connections() -> list[dict[str, Any]]:
    """Saved connections for the Connect page's cards, most-recently-active
    first. Metadata only: the encrypted config is never decrypted."""
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        rows = await s.exec(select(Connection).order_by(col(Connection.last_active_at).desc()))
        return [
            {
                "name": r.name,
                "type": r.type,
                "database": r.database,
                "last_active_at": r.last_active_at,
                "locked": r.lock_hash is not None,
            }
            for r in rows.all()
        ]


async def list_connection_names() -> list[str]:
    """All saved connection names, most-recently-active first."""
    return [c["name"] for c in await list_connections()]


async def unknown_connection_message(name: str, sid: str = "") -> str:
    """The error for an unresolvable connection name, listing the valid ones (the
    session's own first) so a caller (typically an agent) can retry without guessing."""
    names = [*_session_conns.get(sid, {}), *await list_connection_names()]
    return f'no connection named "{name}"; available: {", ".join(names) if names else "(none)"}'


async def _connection_by_name(name: str) -> StoredConnection | None:
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        row = (await s.exec(select(Connection).where(Connection.name == name))).first()
        return _row_to_stored(row)


async def _touch_connection(name: str) -> None:
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        row = (await s.exec(select(Connection).where(Connection.name == name))).first()
        if row is not None:
            row.last_active_at = _now_ms()
            s.add(row)
            await s.commit()


def _now_ms() -> int:
    return int(time.time() * 1000)


# --- Locked connections (docs/connect.md#locked-connections) ---------------
#
# A locked saved connection serves only requests carrying the unlock token its
# tab got for the passphrase. MCP tool calls have no browser behind them and
# never carry one, so the agent is refused on a locked connection whichever way
# it comes in; the agent's own session connections are never locked.

# The X-QV-Token of the request being served (main.py's middleware sets it);
# None inside an MCP tool call.
request_token: ContextVar[str | None] = ContextVar("request_token", default=None)

# A session's one token and the connection names it opens. Memory only: a
# restart means typing the passphrase again.
_tokens: dict[str, str] = {}
_unlocked: dict[str, set[str]] = {}
# connection name -> consecutive wrong passphrases, for the unlock back-off.
_unlock_failures: dict[str, int] = {}
_backoff = asyncio.sleep  # a name tests can replace without touching asyncio itself

LOCKED = {"ok": False, "message": "connection is locked", "reason": "locked"}


def _hash_passphrase(passphrase: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    key = hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=2**14, r=8, p=1)
    return f"{base64.b64encode(salt).decode('ascii')}${base64.b64encode(key).decode('ascii')}"


def _passphrase_matches(stored: str, passphrase: str) -> bool:
    salt = base64.b64decode(stored.split("$", 1)[0])
    return hmac.compare_digest(_hash_passphrase(passphrase, salt), stored)


async def _lock_hash_of(name: str) -> str | None:
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        return (await s.exec(select(Connection.lock_hash).where(Connection.name == name))).first()


def _is_unlocked(sid: str, name: str) -> bool:
    """Whether the request being served carries `sid`'s token and `sid` unlocked `name`."""
    sent = request_token.get()
    return name in _unlocked.get(sid, ()) and sent is not None and hmac.compare_digest(_tokens[sid], sent)


def _issue_token(sid: str, name: str) -> str:
    """The session's token, now good for `name` too: a tab holds one token."""
    _unlocked.setdefault(sid, set()).add(name)
    return _tokens.setdefault(sid, secrets.token_urlsafe(32))


async def _verify_passphrase(name: str, passphrase: str) -> dict[str, Any] | None:
    """None when `passphrase` opens `name`, else the error. Attempts on a
    connection back off exponentially (up to 30s), whoever sends them; the
    attempt is counted before the wait so a burst queues instead of racing."""
    stored = await _lock_hash_of(name)
    if stored is None:
        return {"ok": False, "message": f'"{name}" is not a locked connection'}
    attempts = _unlock_failures[name] = _unlock_failures.get(name, 0) + 1
    if attempts > 1:
        await _backoff(min(2 ** (attempts - 1), 30))
    if not await asyncio.to_thread(_passphrase_matches, stored, passphrase):
        return {"ok": False, "message": "wrong passphrase", "reason": "locked"}
    _unlock_failures.pop(name, None)
    return None


async def lock_connection(sid: str, name: str, passphrase: str) -> dict[str, Any]:
    """Lock a saved connection behind `passphrase`, storing only its salted
    hash. The locking session's tab gets the unlock token right away, so the
    connection it is on keeps working."""
    if not passphrase:
        return {"ok": False, "message": "passphrase required"}
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        row = (await s.exec(select(Connection).where(Connection.name == name))).first()
        if row is None:
            return {"ok": False, "message": await unknown_connection_message(name, sid)}
        if row.lock_hash is not None:
            return {"ok": False, "message": f'"{name}" is already locked'}
        row.lock_hash = await asyncio.to_thread(_hash_passphrase, passphrase)
        s.add(row)
        await s.commit()
    for state in _sessions.values():
        if state.name == name:
            state.locked = True
    return {"ok": True, "token": _issue_token(sid, name)}


async def unlock_connection(sid: str, name: str, passphrase: str) -> dict[str, Any]:
    """Exchange the passphrase for this session's unlock token on `name`."""
    if not sid:
        return {"ok": False, "message": "no session"}
    if (err := await _verify_passphrase(name, passphrase)) is not None:
        return err
    return {"ok": True, "token": _issue_token(sid, name)}


async def remove_lock(name: str, passphrase: str) -> dict[str, Any]:
    """Unlock `name` for good; takes the passphrase, like unlocking does."""
    if (err := await _verify_passphrase(name, passphrase)) is not None:
        return err
    async with AsyncSession(_engine_for_db()) as s:
        row = (await s.exec(select(Connection).where(Connection.name == name))).first()
        if row is not None:
            row.lock_hash = None
            s.add(row)
            await s.commit()
    for names in _unlocked.values():
        names.discard(name)
    for state in _sessions.values():
        if state.name == name:
            state.locked = False
    return {"ok": True}


async def push(sid: str, payload: dict[str, Any]) -> tuple[bool, str]:
    """remote.push behind the lock: a push reaches the browser, which would run
    it with the tab's token, so a locked session refuses it like a query."""
    s, err = await _unlocked_session(sid)
    if s is None and err is LOCKED:
        return False, LOCKED["message"]
    return remote.push(sid, payload)


# --- Sessions (one active connection per session, keyed by a cookie) ------


@dataclass
class _SessionState:
    name: str
    type: str
    config: DriverConfig
    databases: list[str]
    database: str | None
    locked: bool = False  # a locked saved connection: data calls need the tab's token
    root: str | None = None  # the folder a DuckDB folder-mode connection browses
    truncated: bool = False  # the folder list was cut at the session's list limit


@dataclass
class _SessionConn:
    type: str
    config: DriverConfig
    created_by: str
    added_at: int


# Session connections: sid -> name -> connection. Memory only — never written to
# the connections table, invisible to other sessions, gone on restart or when
# the session is deleted. See docs/connect.md#session-connections.
_session_conns: dict[str, dict[str, _SessionConn]] = {}


def _session_conn(sid: str, name: str) -> _SessionConn | None:
    return _session_conns.get(sid, {}).get(name)


async def _resolve(sid: str, name: str) -> tuple[str, DriverConfig] | None:
    """A connection's (type, config) by name: this session's own, else saved."""
    sc = _session_conn(sid, name)
    if sc is not None:
        return sc.type, sc.config
    stored = await _connection_by_name(name)
    return (stored.type, stored.config) if stored is not None else None


def parse_driver_config(body: dict[str, Any]) -> tuple[str, DriverConfig | None, str | None]:
    """(type, config, error) from a body's `type` and driver fields."""
    raw_type = body.get("type")
    conn_type = raw_type if isinstance(raw_type, str) else ""
    driver = DRIVERS.get(conn_type)
    if driver is None:
        return conn_type, None, f"unknown connection type: {conn_type or '(none)'}"
    config, error = driver.parse_config(body)
    return conn_type, config, error if error or config is None else None


# LRU-capped so the map can't grow unbounded (every fresh cookie adds one). An
# evicted session transparently rebuilds on its next request via _ensure_session;
# OrderedDict + move_to_end tracks recency.
_sessions: OrderedDict[str, _SessionState] = OrderedDict()
MAX_SESSIONS = int(os.environ.get("MAX_SESSIONS", "1000"))


def _get_session_entry(sid: str) -> _SessionState | None:
    s = _sessions.get(sid)
    if s is not None:
        _sessions.move_to_end(sid)
    return s


def _set_session_entry(sid: str, state: _SessionState) -> None:
    _sessions[sid] = state
    _sessions.move_to_end(sid)
    while len(_sessions) > MAX_SESSIONS:
        _sessions.popitem(last=False)


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _in_container() -> bool:
    return Path("/.dockerenv").exists()


def _with_localhost_hint(message: str, config: DriverConfig) -> str:
    """Inside a container `localhost` is the container itself, so a failed
    connect to it most likely meant the host machine's database."""
    host = getattr(config, "host", None)
    if host in _LOCAL_HOSTS and _in_container():
        return (
            f"{message} — QueryView runs in a container, where {host} is the container "
            "itself; for a database on your machine use host.docker.internal"
        )
    return message


async def _list_limit(sid: str) -> int:
    """The Explorer's **Max entries** for this session (docs/explorer.md), from
    the session's `ui` blob; the tab writes it, so anything else is the default."""
    rec = await sessions.get_session_rec(sid) if sid else None
    view = rec.ui.get("explorer") if rec else None
    raw = view.get("maxEntries") if isinstance(view, dict) else None
    if isinstance(raw, int) and not isinstance(raw, bool) and 1 <= raw <= MAX_LIST_LIMIT:
        return raw
    return DEFAULT_LIST_LIMIT


async def _list_databases(
    conn_type: str, config: DriverConfig, limit: int = DEFAULT_LIST_LIMIT, current: str | None = None
) -> tuple[DatabasesResult | None, str | None]:
    """The driver's database list, or (None, message) with the localhost hint.
    `current` is the folder a DuckDB folder-mode list is centred on."""
    r = await DRIVERS[conn_type].list_databases(config, limit, current)
    if isinstance(r, Err):
        return None, _with_localhost_hint(r.message, config)
    return r, None


async def _build_session(
    name: str,
    config: DriverConfig,
    database: str | None,
    conn_type: str = "clickhouse",
    limit: int = DEFAULT_LIST_LIMIT,
) -> tuple[_SessionState | None, str | None]:
    """List a connection's databases and build a session object. A session
    connection's name is never in the table, so it reads as unlocked."""
    listed, message = await _list_databases(conn_type, config, limit, database)
    if listed is None:
        return None, message
    databases = listed.databases
    if listed.current is not None:
        # DuckDB folder mode: the stored folder, or its nearest existing parent
        # (the root "." at worst), so a folder connection never lands on a picker.
        database = listed.current
    elif not (database and database in databases):
        database = None
    return (
        _SessionState(
            name=name,
            type=conn_type,
            config=config,
            databases=databases,
            database=database,
            locked=await _lock_hash_of(name) is not None,
            root=listed.root,
            truncated=listed.truncated,
        ),
        None,
    )


async def _ensure_session(sid: str) -> None:
    """Rebuild this session's live driver state from its row. The row is the
    durable truth; `_sessions` is only a cache of the decrypted config and the
    database list, so a backend restart costs one reconnect, not the session."""
    if not sid or _get_session_entry(sid):
        return
    rec = await sessions.get_session_rec(sid)
    if rec is None or rec.connection_name is None:
        return
    found = await _resolve(sid, rec.connection_name)
    if found is None:
        # The connection was deleted, its config no longer decrypts, or it was a
        # session connection lost to a restart. The session reads as
        # disconnected; the user reconnects.
        return
    conn_type, config = found
    state, _ = await _build_session(rec.connection_name, config, rec.database, conn_type, await _list_limit(sid))
    if state is None or (rec.database and state.type == "duckdb" and state.root is None):
        # Unreachable, or a DuckDB folder session whose folder is gone: file
        # mode would create a database file at that path. Reads disconnected.
        return
    _set_session_entry(sid, state)
    if state.root is not None and state.database != rec.database:  # a vanished folder: its nearest parent
        await sessions.set_database(sid, state.database)


async def get_session(sid: str) -> dict[str, Any]:
    """This session's connection state, rebuilt from its row if not cached."""
    await _ensure_session(sid)
    s = _get_session_entry(sid)
    if s is None:
        return {"connected": False}
    sc = _session_conn(sid, s.name)
    return {
        **_last_table(await sessions.get_session_rec(sid), s.name, s.database),
        "connected": True,
        "name": s.name,
        "type": s.type,
        "databases": s.databases,
        "database": s.database,
        **({"root": s.root} if s.root else {}),
        **({"databases_truncated": True} if s.truncated else {}),
        # How this dialect quotes a table/column (dashboard `identifier` params).
        "ident_quote": DRIVERS[s.type].ident_quote,
        "scope": "session" if sc else "saved",
        "created_by": sc.created_by if sc else "user",
        "locked": s.locked,
        # Whether this request's token opens it: the tab prompts when not.
        "unlocked": _is_unlocked(sid, s.name) if s.locked else True,
    }


async def connect_new(
    sid: str, name: str, config: DriverConfig, conn_type: str, session_only: bool = False
) -> dict[str, Any]:
    """Create: open a config, save + activate it for this session. With
    `session_only` it becomes a session connection instead of being saved."""
    if session_only:
        state, message = await add_session_connection(sid, name, config, conn_type, "user")
    elif _session_name_taken(name):
        state, message = None, f'a connection named "{name}" already exists'
    else:
        config = await _with_stored_password(name, config, conn_type)
        state, message = await _build_session(name, config, None, conn_type, await _list_limit(sid))
    if state is None:
        return {"ok": False, "message": message}
    if not session_only:
        # Re-saving keeps a lock, and needs its token: the config is behind it too.
        if state.locked and not _is_unlocked(sid, name):
            return LOCKED
        await _save_active_connection(name, config, conn_type)
    _set_session_entry(sid, state)
    await sessions.set_connection(sid, name)
    if state.database:  # folder mode's "." default: the tab reads it back from the row
        await sessions.set_database(sid, state.database)
    return _opened(state)


def _last_table(rec: sessions.SessionRec | None, name: str, database: str | None) -> dict[str, Any]:
    """`{"table": ...}` when the session last had a table open on this
    connection and database, so the tab can open it again; else nothing."""
    entry = rec.last_visited.get(name) if rec else None
    if not isinstance(entry, dict) or entry.get("database") != database or not entry.get("table"):
        return {}
    return {"table": entry["table"]}


def _opened(state: _SessionState) -> dict[str, Any]:
    """The connect/open response: the session state the tab builds its connection from."""
    return {
        "ok": True,
        "name": state.name,
        "type": state.type,
        "databases": state.databases,
        "database": state.database,
        **({"root": state.root} if state.root else {}),
        **({"databases_truncated": True} if state.truncated else {}),
    }


async def open_saved(
    sid: str, name: str, database: str | None = None, by: Literal["agent", "user"] = "user"
) -> dict[str, Any]:
    """Open a connection by name for this session: one of its session
    connections, else a saved one. A `database` not on it fails before the
    session switches."""
    found = await _resolve(sid, name)
    if found is None:
        return {
            "ok": False,
            "message": await unknown_connection_message(name, sid),
            "not_found": True,
        }
    conn_type, config = found
    # Without a `database` opening goes back to the one this session last
    # visited on the connection, else the picker (a folder connection's root).
    # Building on it checks it: listed, or in folder mode reachable by path.
    rec = await sessions.get_session_rec(sid)
    visited = rec.last_visited.get(name) if rec else None
    start = database
    if start is None and isinstance(visited, dict):
        start = visited.get("database")
    state, message = await _build_session(name, config, start, conn_type, await _list_limit(sid))
    if state is None:
        return {"ok": False, "message": message}
    if database is not None and state.database != database:
        return {"ok": False, "message": "unknown database"}
    _set_session_entry(sid, state)
    if _session_conn(sid, name) is None:
        await _touch_connection(name)
    await sessions.set_connection(sid, name, by)
    if database is not None:
        await select_database(sid, database)
    elif state.database:  # the last visited database, or folder mode's root
        await sessions.set_database(sid, state.database)
    return {**_opened(state), **_last_table(rec, name, state.database)}


async def disconnect(sid: str, by: Literal["agent", "user"] = "user") -> dict[str, Any]:
    """Drop this session's active connection. Saved connections are left intact
    — the Connect page still reopens them."""
    _sessions.pop(sid, None)
    await sessions.set_connection(sid, None, by)
    return {"ok": True}


async def _with_stored_password(name: str, config: DriverConfig, conn_type: str) -> DriverConfig:
    """An edit that leaves the password blank keeps the saved one."""
    driver = DRIVERS[conn_type]
    data = driver.config_to_dict(config)
    if not isinstance(data, dict) or data.get("password", True):
        return config
    stored = await _connection_by_name(name)
    if stored is None or stored.type != conn_type:
        return config
    saved = driver.config_to_dict(stored.config).get("password")
    return driver.config_from_dict({**data, "password": saved}) if saved else config


async def saved_config(sid: str, name: str) -> dict[str, Any]:
    """A saved connection's config for the edit form, password blanked. The
    config is behind the lock: a locked one needs the tab's token."""
    stored = await _connection_by_name(name)
    if stored is None:
        return {"ok": False, "message": await unknown_connection_message(name, sid), "not_found": True}
    if await _lock_hash_of(name) is not None and not _is_unlocked(sid, name):
        return LOCKED
    data = DRIVERS[stored.type].config_to_dict(stored.config)
    config = {k: "" if k == "password" else v for k, v in data.items()}
    return {"ok": True, "name": name, "type": stored.type, "config": config}


async def delete_connection(sid: str, name: str, passphrase: str) -> dict[str, Any]:
    """Delete a connection: this session's own, else a saved one, which when
    locked takes the passphrase. Every session on it is disconnected."""
    if _session_conn(sid, name) is not None:
        return await remove_session_connection(sid, name)
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        row = (await s.exec(select(Connection).where(Connection.name == name))).first()
        if row is None:
            return {"ok": False, "message": await unknown_connection_message(name, sid), "not_found": True}
        if row.lock_hash is not None:
            if not passphrase:
                return LOCKED
            if (err := await _verify_passphrase(name, passphrase)) is not None:
                return err
        await s.delete(row)
        await s.commit()
    for names in _unlocked.values():
        names.discard(name)
    for other in [k for k, state in _sessions.items() if state.name == name]:
        _sessions.pop(other)
    await sessions.clear_connection(name)
    return {"ok": True}


async def list_connections_for(sid: str) -> list[dict[str, Any]]:
    """This session's connections, then the saved ones, each tagged with its
    scope and creator."""
    own = [
        {
            "name": n,
            "type": c.type,
            "database": None,
            "last_active_at": c.added_at,
            "scope": "session",
            "created_by": c.created_by,
            "locked": False,
        }
        for n, c in _session_conns.get(sid, {}).items()
    ]
    return own + [{**c, "scope": "saved", "created_by": "user"} for c in await list_connections()]


async def agent_connections_for(sid: str) -> list[dict[str, Any]]:
    """list_connections_for minus locked ones: the agent never sees those, even
    while a tab has one unlocked (the lock is the connection's stored state)."""
    return [c for c in await list_connections_for(sid) if not c["locked"]]


async def list_databases_of(sid: str, name: str) -> tuple[list[str] | None, str | None]:
    """A connection's live database list, or (None, message); never raises, so
    one bad server can't fail a listing of many."""
    found = await _resolve(sid, name)
    if found is None:  # deleted meanwhile, or its config no longer decrypts
        return None, "connection unavailable"
    try:
        listed, message = await _list_databases(*found, await _list_limit(sid))
        return (listed.databases if listed else None), message
    except Exception as e:
        return None, error_message(e)


def _session_name_taken(name: str) -> bool:
    """Any session's: a session row keeps naming its connection after a restart
    empties memory, and must not then resolve to someone's saved namesake."""
    return any(name in conns for conns in _session_conns.values())


async def _name_taken(name: str) -> str | None:
    """Names are unique across saved and every session's connections."""
    if _session_name_taken(name) or name in await list_connection_names():
        return f'a connection named "{name}" already exists'
    return None


async def add_session_connection(
    sid: str, name: str, config: DriverConfig, conn_type: str, created_by: str
) -> tuple[_SessionState | None, str | None]:
    """Add a session connection after checking it connects; its built state, or
    the error. A name already used by a saved or session connection is refused,
    so a name means one thing."""
    if not sid:
        return None, "no session"
    if (taken := await _name_taken(name)) is not None:
        return None, taken
    state, message = await _build_session(name, config, None, conn_type, await _list_limit(sid))
    if state is not None:
        _session_conns.setdefault(sid, {})[name] = _SessionConn(conn_type, config, created_by, _now_ms())
        remote.notify(sid, {"type": "connections"})
    return state, message


async def remove_session_connection(sid: str, name: str, by: Literal["agent", "user"] = "user") -> dict[str, Any]:
    """Drop a session connection, disconnecting the session if it is active."""
    if _session_conns.get(sid, {}).pop(name, None) is None:
        return {"ok": False, "message": f'no session connection named "{name}"'}
    remote.notify(sid, {"type": "connections"})
    # The row, not the LRU cache: an evicted session must not keep pointing here.
    rec = await sessions.get_session_rec(sid)
    if rec is not None and rec.connection_name == name:
        await disconnect(sid, by)
    return {"ok": True}


def forget_session(sid: str) -> None:
    """Drop a deleted session's in-memory state, its session connections too."""
    _session_conns.pop(sid, None)
    _sessions.pop(sid, None)
    _unlocked.pop(sid, None)
    _tokens.pop(sid, None)


async def _relist(sid: str, s: _SessionState, current: str | None = None) -> DatabasesResult | dict[str, Any]:
    """A fresh database list (centred on `current`, else the selected folder, in
    DuckDB folder mode); the error result on failure."""
    listed, message = await _list_databases(s.type, s.config, await _list_limit(sid), current or s.database)
    return listed if listed is not None else {"ok": False, "message": message}


def _keep(s: _SessionState, listed: DatabasesResult) -> None:
    s.databases, s.truncated = listed.databases, listed.truncated


async def refresh_databases(sid: str) -> dict[str, Any]:
    """Re-list this session's connection's databases; the cached list dates
    from the connect. The selected database is kept even if no longer listed:
    the session is still on it, and the next select tells the user."""
    s, err = await _unlocked_session(sid)
    if s is None:
        return err  # type: ignore[return-value]
    listed = await _relist(sid, s)
    if not isinstance(listed, DatabasesResult):
        return listed
    _keep(s, listed)
    if listed.current is not None and listed.current != s.database:  # the folder vanished: its parent
        s.database = listed.current
        await sessions.set_database(sid, s.database)
    return {
        "ok": True,
        "name": s.name,
        "databases": s.databases,
        **({"database": s.database} if s.root else {}),
        **({"databases_truncated": True} if s.truncated else {}),
    }


async def select_database(sid: str, database: str) -> dict[str, Any]:
    """Select this session's active connection's database. A name not in the
    cached list is checked against a fresh one first, so a database created
    since the connect can be selected."""
    s, err = await _unlocked_session(sid)
    if s is None:
        return err  # type: ignore[return-value]
    unknown = {"ok": False, "message": "unknown database", "reason": "unknown"}
    if not database:
        return unknown
    if s.root is not None:
        # DuckDB folder mode: any folder the path check reaches, past the list
        # limit too; the list then moves to that folder's level.
        listed = await _relist(sid, s, database)
        if not isinstance(listed, DatabasesResult):
            return listed
        if listed.current != database:
            return unknown
        _keep(s, listed)
    elif database not in s.databases:
        listed = await _relist(sid, s)
        if not isinstance(listed, DatabasesResult):
            return listed
        _keep(s, listed)
        if database not in s.databases:
            return unknown
    s.database = database
    if _session_conn(sid, s.name) is None:
        await _save_selected_database(s.name, database)
    await sessions.set_database(sid, database)
    if s.root is None:
        return {"ok": True}
    return {"ok": True, "databases": s.databases, **({"databases_truncated": True} if s.truncated else {})}


async def _unlocked_session(sid: str) -> tuple[_SessionState | None, dict[str, Any] | None]:
    """This session's state, or why the request may not use its connection:
    not connected, or locked without the tab's token (docs/connect.md#locked-connections)."""
    await _ensure_session(sid)
    s = _get_session_entry(sid)
    if s is None:
        return None, {"ok": False, "message": "not connected", "reason": "no-session"}
    if s.locked and not _is_unlocked(sid, s.name):
        return None, LOCKED
    return s, None


async def _gated_session(sid: str) -> tuple[_SessionState | None, dict[str, Any] | None]:
    """`_unlocked_session`, plus — for drivers with a picker — a database
    selected: the gate every query-shaped operation (query/describe/tables) shares."""
    s, err = await _unlocked_session(sid)
    if s is None:
        return None, err
    if DRIVERS[s.type].requires_database and not s.database:
        return None, {
            "ok": False,
            "message": "select a database first",
            "reason": "no-database",
        }
    return s, None


async def describe_query(sid: str, sql: str) -> dict[str, Any]:
    """Describe a query's output columns against this session's selected database."""
    s, err = await _gated_session(sid)
    if s is None:
        return err  # type: ignore[return-value]
    r = await DRIVERS[s.type].describe_query(s.config, sql, s.database)
    if isinstance(r, Err):
        return {"ok": False, "message": r.message}
    return {"ok": True, "fields": r.fields}


async def list_tables(sid: str, union: bool = False) -> dict[str, Any]:
    """List the tables of this session's selected database (the Explorer page's
    sidebar), each with the ready-to-run browse SELECT — the driver's own when
    it supplies one (DuckDB folder mode), else built here with the driver's
    identifier quote, so the frontend never guesses dialect quoting."""
    s, err = await _gated_session(sid)
    if s is None:
        return err  # type: ignore[return-value]
    driver = DRIVERS[s.type]
    r = await driver.list_tables(s.config, s.database, union, await _list_limit(sid))
    if isinstance(r, Err):
        return {"ok": False, "message": r.message}
    tables = [{**t, "query": t.get("query") or select_all_sql(t["name"], driver.ident_quote)} for t in r.tables]
    return {"ok": True, "tables": tables, **({"truncated": True} if r.truncated else {})}


async def run_query(
    sid: str,
    sql: str,
    limit: int,
    offset: int,
    order_by: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run a paginated SQL query against this session's selected database and
    return `{ok, database, meta: [{name, type}], data: [[…]]}`. The driver owns
    pagination/quoting."""
    s, err = await _gated_session(sid)
    if s is None:
        return err  # type: ignore[return-value]
    r = await DRIVERS[s.type].run_query(s.config, sql, s.database, limit, offset, order_by)
    return _rows_reply(s, r)


async def run_sql(sid: str, sql: str, max_rows: int) -> dict[str, Any]:
    """Run one read-only statement as written (the agent's MCP run_sql) on this
    session's selected database: `{ok, database, meta, data}`, at most
    `max_rows` rows."""
    s, err = await _gated_session(sid)
    if s is None:
        return err  # type: ignore[return-value]
    r = await DRIVERS[s.type].run_sql(s.config, sql.rstrip().rstrip(";"), s.database, max_rows)
    return _rows_reply(s, r)


def _rows_reply(s: _SessionState, r: RowsResult | Err) -> dict[str, Any]:
    if isinstance(r, Err):
        return {"ok": False, "message": r.message}
    return {"ok": True, "database": s.database, "meta": [c._asdict() for c in r.rows.meta], "data": r.rows.data}


async def execute_script(sid: str, sql: str) -> dict[str, Any]:
    """Run a script as written on this session's selected database (the Scripts
    page): `{ok, results}`, one entry per statement run — see docs/api.md."""
    s, err = await _gated_session(sid)
    if s is None:
        return err  # type: ignore[return-value]
    results = await DRIVERS[s.type].execute_script(s.config, sql, s.database)
    return {
        "ok": True,
        "database": s.database,
        "results": [
            {
                "sql": r.sql,
                "ok": r.ok,
                "meta": [c._asdict() for c in r.rows.meta] if r.rows is not None else None,
                "data": r.rows.data if r.rows is not None else None,
                "truncated": r.truncated,
                "status": r.status,
                "message": r.message,
                "elapsed_ms": r.elapsed_ms,
            }
            for r in results
        ],
    }


async def export_csv(
    sid: str,
    sql: str,
    limit: int,
    offset: int,
    order_by: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """The same page as `run_query`, as CSVWithNames text in `output`."""
    s, err = await _gated_session(sid)
    if s is None:
        return err  # type: ignore[return-value]
    r = await DRIVERS[s.type].export_csv(s.config, sql, s.database, limit, offset, order_by)
    if isinstance(r, Err):
        return {"ok": False, "message": r.message}
    return {"ok": True, "output": r.text}


# Imported last, not at the top: sessions.py builds on this module's engine and
# schema helpers, so a top-level import here would be a cycle. connect.py calls
# into it only to write a session's connection through.
from . import remote, sessions  # noqa: E402
