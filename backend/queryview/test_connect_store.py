"""The connection store round-trips a driver config through the encrypted JSON
blob, keyed by type, and never persists secrets in plaintext."""

from __future__ import annotations

import asyncio
import sqlite3

from queryview.connect import _connection_by_name, _db_path, _save_active_connection
from queryview.drivers.clickhouse import ChConfig


def _run(coro):
    return asyncio.run(coro)


def test_save_then_load_round_trips_config_and_type():
    cfg = ChConfig("h", 8123, "u", "s3cret")
    _run(_save_active_connection("ch1", cfg, "clickhouse"))
    stored = _run(_connection_by_name("ch1"))
    assert stored is not None
    assert stored.type == "clickhouse"
    assert stored.config == cfg


def test_password_is_not_stored_in_plaintext():
    _run(_save_active_connection("ch2", ChConfig("h", 8123, "u", "TOPSECRET"), "clickhouse"))
    con = sqlite3.connect(_db_path())
    try:
        blob = con.execute("SELECT config FROM connections WHERE name='ch2'").fetchone()[0]
    finally:
        con.close()
    assert "TOPSECRET" not in blob
