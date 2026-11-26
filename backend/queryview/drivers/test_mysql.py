"""MySQL-specific behavior against a fake aiomysql connection (no server):
backtick-quoted `_qv` pagination, the table list, scripts and read-only
run_sql. Registry conformance and config validation are in test_contract."""

from __future__ import annotations

import asyncio

from pymysql.constants import COMMAND, FIELD_TYPE
from pymysql.err import OperationalError

from queryview.drivers.base import SCRIPT_ROW_CAP, Column, DatabasesResult, Err, RowsResult, TablesResult, TextResult
from queryview.drivers.mysql import _CONV, MySqlConfig, MySqlDriver, _raw_connect

CFG = MySqlConfig("h", 3306, "u", "")


def _fake(monkeypatch, results):
    """A fake connection: each executed SQL is recorded; `results(sql)` gives
    (description, rows) for a SELECT, None for a command, or raises."""
    log = {"sql": [], "drained": 0}

    class _Cursor:
        async def execute(self, sql):
            log["sql"].append(sql)
            out = results(sql)
            self.description, self._rows = out if out else (None, [])
            self.rowcount = -1 if out else 2

        async def fetchall(self):
            return self._rows

        async def fetchmany(self, n):
            log["fetchmany"] = n
            return self._rows[:n]

        async def close(self):
            log["drained"] += 1

    class _Conn:
        async def cursor(self, cls):
            log.setdefault("cursors", []).append(cls.__name__)
            return _Cursor()

        def close(self):
            log["closed"] = True

    async def fake_connect(c, database):
        log["database"] = database
        return _Conn()

    monkeypatch.setattr("queryview.drivers.mysql._raw_connect", fake_connect)
    return log


ID = (("id", FIELD_TYPE.LONGLONG),)


def test_run_query_builds_aliased_backtick_sql_and_decodes_json(monkeypatch):
    desc = (("id", FIELD_TYPE.LONGLONG), ("doc", FIELD_TYPE.JSON))
    log = _fake(monkeypatch, lambda sql: (desc, [(2**60, '{"a": 1.5}')]))
    r = asyncio.run(MySqlDriver().run_query(CFG, "SELECT * FROM t;", "shop", 50, 10, [{"name": "a b", "dir": "desc"}]))
    assert isinstance(r, RowsResult)
    assert r.rows.meta == [Column("id", "bigint"), Column("doc", "json")]
    assert r.rows.data == [[str(2**60), {"a": "1.5"}]]
    assert log["database"] == "shop" and log.get("closed")
    assert log["cursors"][-1] == "Cursor"  # a LIMIT-bounded page is buffered
    assert log["sql"] == [
        "SET SESSION TRANSACTION READ ONLY",  # a SELECT calling a function that writes is refused
        "SELECT * FROM (\nSELECT * FROM t\n) AS _qv ORDER BY `a b` DESC LIMIT 50 OFFSET 10",
    ]

    csv = asyncio.run(MySqlDriver().export_csv(CFG, "SELECT 1", "shop", 50, 0, None))
    assert isinstance(csv, TextResult) and csv.text == 'id,doc\n1152921504606846976,"{""a"": 1.5}"'


def test_list_tables_reads_information_schema(monkeypatch):
    log = _fake(monkeypatch, lambda sql: (ID, [("items", 3, 16384, 0), ("v", None, None, 1)]))
    r = asyncio.run(MySqlDriver().list_tables(CFG, "shop"))
    assert isinstance(r, TablesResult)
    assert r.tables == [
        {"name": "items", "rows": 3, "bytes": 16384, "view": False},
        {"name": "v", "rows": None, "bytes": None, "view": True},
    ]
    assert "TABLE_SCHEMA = DATABASE()" in log["sql"][0]


def test_run_sql_is_read_only_and_capped(monkeypatch):
    log = _fake(monkeypatch, lambda sql: None if sql.startswith("SET") else (ID, [(1,), (2,), (3,)]))
    r = asyncio.run(MySqlDriver().run_sql(CFG, "SHOW TABLES", "shop", 2))
    assert isinstance(r, RowsResult) and r.rows.data == [[1], [2]]
    assert log["sql"] == ["SET SESSION TRANSACTION READ ONLY", "SHOW TABLES"]


def test_execute_script_drains_rows_and_stops_at_the_first_error(monkeypatch):
    def results(sql):
        if "missing" in sql:
            raise RuntimeError("Table 'shop.missing' doesn't exist")
        return (ID, [(i,) for i in range(SCRIPT_ROW_CAP + 5)]) if sql.startswith("SELECT") else None

    log = _fake(monkeypatch, results)
    out = asyncio.run(
        MySqlDriver().execute_script(
            CFG, "INSERT INTO t VALUES (1),(2); SELECT id FROM t; SELECT * FROM missing; SELECT 1", "shop"
        )
    )
    assert [(r.ok, r.status) for r in out] == [(True, "OK, 2 rows affected"), (True, ""), (False, "")]
    rows = out[1].rows
    assert out[1].truncated and rows is not None and len(rows.data) == SCRIPT_ROW_CAP
    assert log["fetchmany"] == SCRIPT_ROW_CAP + 1 and log["drained"] == 1
    assert set(log["cursors"]) == {"SSCursor"}  # capped: unbuffered
    assert "missing" in out[2].message and len(log["sql"]) == 3


def test_errors_become_err(monkeypatch):
    async def boom(c, database):
        raise OSError("Can't connect to MySQL server")

    monkeypatch.setattr("queryview.drivers.mysql._raw_connect", boom)
    assert isinstance(asyncio.run(MySqlDriver().list_databases(CFG)), Err)
    assert asyncio.run(MySqlDriver().test(CFG))["ok"] is False
    assert not asyncio.run(MySqlDriver().execute_script(CFG, "SELECT 1", "shop"))[0].ok


def test_connections_turn_multi_statements_off(monkeypatch):
    # aiomysql always negotiates multi-statements; without this a single run_sql
    # call could switch its session back to READ WRITE and then write.
    sent = []

    class _Conn:
        async def _execute_command(self, command, arg):
            sent.append((command, arg))

        async def _read_packet(self):
            pass

    async def fake_connect(**kwargs):
        return _Conn()

    monkeypatch.setattr("queryview.drivers.mysql.aiomysql.connect", fake_connect)
    asyncio.run(_raw_connect(CFG, "shop"))
    assert sent == [(COMMAND.COM_SET_OPTION, b"\x01\x00")]  # MYSQL_OPTION_MULTI_STATEMENTS_OFF


def test_duplicate_column_names_run_unwrapped(monkeypatch):
    # A derived table needs unique names: `a.id, b.id` falls back to the SQL as
    # written, skipping the rows before the page.
    def results(sql):
        if "_qv" in sql:
            raise OperationalError(1060, "Duplicate column name 'id'")
        return ((("id", FIELD_TYPE.LONG), ("id", FIELD_TYPE.LONG)), [(1, 10), (2, 20), (3, 30)])

    log = _fake(monkeypatch, results)
    r = asyncio.run(MySqlDriver().run_query(CFG, "SELECT a.id, b.id FROM a JOIN b;", "shop", 1, 1, None))
    assert isinstance(r, RowsResult) and r.rows.data == [[2, 20]]
    assert log["sql"][2] == "SELECT a.id, b.id FROM a JOIN b" and log["fetchmany"] == 2
    # A column sort needs the wrapper, so the error stands.
    assert isinstance(asyncio.run(MySqlDriver().run_query(CFG, "SELECT 1", "shop", 1, 0, [{"name": "id"}])), Err)


def test_time_and_bit_keep_their_values():
    assert _CONV[FIELD_TYPE.TIME]("25:00:00") == "25:00:00"  # not a timedelta's "1 day, 1:00:00"
    assert _CONV[FIELD_TYPE.BIT](b"\x05") == 5


def test_a_named_database_is_the_only_one_tested_and_listed(monkeypatch):
    log = _fake(monkeypatch, lambda sql: (ID, [(1,)]))
    cfg = MySqlConfig("h", 3306, "u", "", "sales_reporting")
    assert asyncio.run(MySqlDriver().test(cfg))["ok"] is True
    assert log["database"] == "sales_reporting"
    r = asyncio.run(MySqlDriver().list_databases(cfg))
    assert r == DatabasesResult(["sales_reporting"], current="sales_reporting")
    assert log["sql"] == ["SELECT 1"]  # no SHOW DATABASES


def test_a_saved_config_with_a_dropped_key_still_loads():
    data = {"host": "h", "port": 3306, "username": "u", "password": "", "show_all_databases": True}
    assert MySqlDriver().config_from_dict(data) == MySqlConfig("h", 3306, "u", "")
