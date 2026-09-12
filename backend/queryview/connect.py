"""Connection domain: the SQLModel/SQLite connection store (configs encrypted
at rest) and per-session active connections. No HTTP concerns here — operations
return plain results that main.py maps to responses. Per-backend execution is
delegated to the driver registry; nothing here is ClickHouse-specific."""

from __future__ import annotations

import base64
import json
import os
import time
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar

import platformdirs
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import Field, SQLModel, col, select
from sqlmodel.ext.asyncio.session import AsyncSession

if TYPE_CHECKING:
    from alembic.config import Config

from .drivers import DRIVERS
from .drivers.base import DriverConfig, select_all_sql

# --- Storage (SQLite, lazily opened) --------------------------------------


class Connection(SQLModel, table=True):
    __tablename__: ClassVar[str] = "connections"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True, index=True)
    type: str = Field(default="clickhouse", index=True)
    config: str  # base64(AES-GCM(json.dumps(driver config))) — never plaintext
    database: str | None = Field(default=None)
    last_active_at: int  # unix ms; the max is the "latest active"


def _data_dir() -> Path:
    """Every piece of state lives here: DATA_DIR, else the platform's user-data
    dir (`$XDG_DATA_HOME/queryview` on Linux, `Application Support` on macOS,
    `%LOCALAPPDATA%` on Windows). Deliberately not package-relative — that put
    the DB in site-packages, which is uv's disposable cache under `uvx`."""
    env = os.environ.get("DATA_DIR")
    return Path(env) if env else Path(platformdirs.user_data_dir("queryview"))


def _db_path() -> Path:
    """The SQLite store. One fixed name inside the data dir — move the
    directory, not the file."""
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


async def _latest_active_connection() -> StoredConnection | None:
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        row = (await s.exec(select(Connection).order_by(col(Connection.last_active_at).desc()).limit(1))).first()
        return _row_to_stored(row)


async def list_connection_names() -> list[str]:
    """All saved connection names, most-recently-active first (for `connect`
    autocomplete)."""
    await _ensure_schema()
    async with AsyncSession(_engine_for_db()) as s:
        rows = await s.exec(select(Connection.name).order_by(col(Connection.last_active_at).desc()))
        return list(rows.all())


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


# --- Sessions (one active connection per session, keyed by a cookie) ------


@dataclass
class _SessionState:
    name: str
    type: str
    config: DriverConfig
    databases: list[str]
    database: str | None


# LRU-capped so the map can't grow unbounded (every fresh cookie adds one). An
# evicted session transparently rebuilds on its next request via _ensure_session;
# OrderedDict + move_to_end tracks recency.
_sessions: OrderedDict[str, _SessionState] = OrderedDict()
MAX_SESSIONS = int(os.environ.get("MAX_SESSIONS", "1000"))


# Cookies that explicitly disconnected. Kept distinct from "never seen" so
# _ensure_session can suppress auto-reconnect for them; bounded like _sessions.
_disconnected: OrderedDict[str, None] = OrderedDict()


def _mark_disconnected(sid: str) -> None:
    _disconnected[sid] = None
    _disconnected.move_to_end(sid)
    while len(_disconnected) > MAX_SESSIONS:
        _disconnected.popitem(last=False)


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


async def _build_session(
    name: str, config: DriverConfig, database: str | None, conn_type: str = "clickhouse"
) -> tuple[_SessionState | None, str | None]:
    """List a connection's databases and build a session object."""
    ok, result = await DRIVERS[conn_type].list_databases(config)
    if not ok:
        return None, result  # type: ignore[return-value]
    databases: list[str] = result  # type: ignore[assignment]
    return (
        _SessionState(
            name=name,
            type=conn_type,
            config=config,
            databases=databases,
            database=database if database and database in databases else None,
        ),
        None,
    )


async def _ensure_session(sid: str) -> None:
    """At session start (a cookie we haven't seen), reconnect the latest active
    connection so a fresh session resumes where the last one left off."""
    if _get_session_entry(sid):
        return
    if sid in _disconnected:
        return
    stored = await _latest_active_connection()
    if stored is None:
        return
    state, _ = await _build_session(stored.name, stored.config, stored.database, stored.type)
    if state is not None:
        _set_session_entry(sid, state)


async def get_session(sid: str) -> dict[str, Any]:
    """This session's state; auto-connects the latest active for an unseen cookie."""
    await _ensure_session(sid)
    s = _get_session_entry(sid)
    if s is None:
        return {"connected": False}
    return {
        "connected": True,
        "name": s.name,
        "type": s.type,
        "databases": s.databases,
        "database": s.database,
    }


async def connect_new(sid: str, name: str, config: DriverConfig, conn_type: str) -> dict[str, Any]:
    """Create: open a config, save + activate it for this session."""
    state, message = await _build_session(name, config, None, conn_type)
    if state is None:
        return {"ok": False, "message": message}
    _disconnected.pop(sid, None)
    _set_session_entry(sid, state)
    await _save_active_connection(name, config, conn_type)
    return {"ok": True, "name": name, "type": state.type, "databases": state.databases}


async def open_saved(sid: str, name: str) -> dict[str, Any]:
    """Open a saved connection by name for this session."""
    stored = await _connection_by_name(name)
    if stored is None:
        return {
            "ok": False,
            "message": f'no connection named "{name}"',
            "not_found": True,
        }
    # Reset the database so `connect <name>` always lands on the picker.
    state, message = await _build_session(stored.name, stored.config, None, stored.type)
    if state is None:
        return {"ok": False, "message": message}
    _disconnected.pop(sid, None)
    _set_session_entry(sid, state)
    await _touch_connection(name)
    return {"ok": True, "name": name, "type": state.type, "databases": state.databases}


async def disconnect(sid: str) -> dict[str, Any]:
    """Drop this session's active connection and suppress auto-reconnect until
    it connects again. Saved connections are left intact — `connect <name>`
    still reopens them."""
    _sessions.pop(sid, None)
    _mark_disconnected(sid)
    return {"ok": True}


async def select_database(sid: str, database: str) -> dict[str, Any]:
    """Select this session's active connection's database."""
    s = _get_session_entry(sid)
    if s is None:
        return {"ok": False, "message": "not connected", "reason": "no-session"}
    if not database or database not in s.databases:
        return {"ok": False, "message": "unknown database", "reason": "unknown"}
    s.database = database
    await _save_selected_database(s.name, database)
    return {"ok": True}


async def _gated_session(sid: str) -> tuple[_SessionState | None, dict[str, Any] | None]:
    """This session's state, or the error dict shared by every query-shaped
    operation (query/describe/tables): not connected, or — for drivers with a
    picker — no database selected yet."""
    await _ensure_session(sid)
    s = _get_session_entry(sid)
    if s is None:
        return None, {"ok": False, "message": "not connected", "reason": "no-session"}
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
    ok, result = await DRIVERS[s.type].describe_query(s.config, sql, s.database)
    if not ok:
        return {"ok": False, "message": result}
    return {"ok": True, "fields": result}


async def list_tables(sid: str) -> dict[str, Any]:
    """List the tables of this session's selected database (the Explorer page's
    sidebar), each with the ready-to-run browse SELECT — built here with the
    driver's identifier quote, so the frontend never guesses dialect quoting."""
    s, err = await _gated_session(sid)
    if s is None:
        return err  # type: ignore[return-value]
    driver = DRIVERS[s.type]
    _ok, result = await driver.list_tables(s.config, s.database)
    if isinstance(result, str):
        return {"ok": False, "message": result}
    tables = [{**t, "query": select_all_sql(t["name"], driver.ident_quote)} for t in result]
    return {"ok": True, "tables": tables}


async def run_query(
    sid: str,
    sql: str,
    limit: int,
    offset: int,
    order_by: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run a paginated SQL query against this session's selected database and
    return `{ok, meta: [{name, type}], data: [[…]]}`. The driver owns
    pagination/quoting."""
    s, err = await _gated_session(sid)
    if s is None:
        return err  # type: ignore[return-value]
    r = await DRIVERS[s.type].run_query(s.config, sql, s.database, limit, offset, order_by)
    if not r.ok or r.rows is None:
        return {"ok": False, "message": r.message}
    return {"ok": True, "meta": [c._asdict() for c in r.rows.meta], "data": r.rows.data}


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
    if not r.ok:
        return {"ok": False, "message": r.value}
    return {"ok": True, "output": r.value}
