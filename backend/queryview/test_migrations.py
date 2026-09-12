"""Alembic owns the schema: a fresh DB must be migrated to head (all three
tables present and stamped in alembic_version), not built by create_all."""

from __future__ import annotations

import asyncio
import sqlite3

from queryview.connect import _db_path, _ensure_schema


def _run(coro):
    return asyncio.run(coro)


def test_fresh_db_is_migrated_to_head():
    _run(_ensure_schema())

    con = sqlite3.connect(_db_path())
    try:
        names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        # Alembic ran (not create_all): the version table exists alongside the
        # three application tables.
        assert {
            "connections",
            "predefined_queries",
            "dashboards",
            "workspaces",
            "alembic_version",
        } <= names, f"missing tables, got {sorted(names)}"

        versions = [r[0] for r in con.execute("SELECT version_num FROM alembic_version")]
    finally:
        con.close()

    assert len(versions) == 1 and versions[0], versions

    # The stamped revision is the latest in the migration tree.
    from alembic.script import ScriptDirectory

    from queryview.connect import _alembic_config

    head = ScriptDirectory.from_config(_alembic_config()).get_current_head()
    assert versions[0] == head, f"stamped {versions[0]} != head {head}"


def test_config_blob_migration_backfills_existing_clickhouse_row(tmp_path, monkeypatch):
    """A row written at the pre-blob revision is rewrapped into an encrypted
    JSON config that decrypts back to the original host/port/user/password.
    Runs on a private DB: downgrading the shared session DB below the
    workspaces revision would collide on the restored global-unique names."""
    import json
    import sqlite3

    from alembic import command

    import queryview.connect as _c
    from queryview.connect import _alembic_config, _decrypt_str, _encrypt_str

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setattr(_c, "_engine", None)
    monkeypatch.setattr(_c, "_schema_ready", False)
    monkeypatch.setattr(_c, "_key", None)

    cfg = _alembic_config()
    command.upgrade(cfg, "9a536b7c0328")  # the per-column schema, built fresh

    con = sqlite3.connect(_db_path())
    try:
        con.execute(
            "INSERT INTO connections (name, type, host, port, username, password, "
            "database, last_active_at) VALUES (?,?,?,?,?,?,?,?)",
            ("legacy", "clickhouse", "h", 8123, "u", _encrypt_str("pw"), "db", 1),
        )
        con.commit()
    finally:
        con.close()

    command.upgrade(cfg, "head")

    con = sqlite3.connect(_db_path())
    try:
        blob = con.execute("SELECT config FROM connections WHERE name='legacy'").fetchone()[0]
    finally:
        con.close()
    data = json.loads(_decrypt_str(blob))
    assert data == {"host": "h", "port": 8123, "username": "u", "password": "pw"}


def test_predefined_queries_has_presentation_columns():
    _run(_ensure_schema())
    con = sqlite3.connect(_db_path())
    try:
        cols = {r[1] for r in con.execute("PRAGMA table_info(predefined_queries)")}
    finally:
        con.close()
    assert {"order_by", "fields"} <= cols, f"missing columns, got {sorted(cols)}"
