"""MySQL-specific behavior against a fake aiomysql connection (no server):
backtick-quoted `_qv` pagination, the table list, scripts and read-only
run_sql. Registry conformance and config validation are in test_contract."""

from __future__ import annotations

import asyncio

from pymysql.constants import COMMAND, FIELD_TYPE
from pymysql.err import OperationalError

from queryview.drivers.base import (
    RUN_SQL_TIMEOUT_SECONDS,
    SCRIPT_ROW_CAP,
    SCRIPT_TIMEOUT_SECONDS,
    Column,
    DatabasesResult,
    Err,
    RowsResult,
    TablesResult,
    TextResult,
)
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
            if "close_error" in log:
                raise log["close_error"]

    class _Conn:
        def thread_id(self):
            return 7

        async def cursor(self, cls):
            log.setdefault("cursors", []).append(cls.__name__)
            return _Cursor()

        def close(self):
            log["closed"] = True

    async def fake_connect(c, database, timeout=None):
        log["database"] = database
        log.setdefault("timeouts", []).append(timeout)
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


def test_execute_script_kills_a_capped_select_and_stops_at_the_first_error(monkeypatch):
    def results(sql):
        if "missing" in sql:
            raise RuntimeError("Table 'shop.missing' doesn't exist")
        if sql == "SELECT 'x'":
            return (ID, [("x",)])
        return (ID, [(i,) for i in range(SCRIPT_ROW_CAP + 5)]) if sql.startswith("SELECT") else None

    log = _fake(monkeypatch, results)
    out = asyncio.run(
        MySqlDriver().execute_script(
            CFG, "INSERT INTO t VALUES (1),(2); SELECT id FROM t; SELECT 'x'; SELECT * FROM missing; SELECT 1", "shop"
        )
    )
    assert [(r.ok, r.status) for r in out] == [(True, "OK, 2 rows affected"), (True, ""), (True, ""), (False, "")]
    rows = out[1].rows
    assert out[1].truncated and rows is not None and len(rows.data) == SCRIPT_ROW_CAP
    assert log["fetchmany"] == SCRIPT_ROW_CAP + 1 and log["drained"] == 2
    assert log["cursors"].count("Cursor") == 1  # only the KILL; the capped statements are unbuffered
    # Only the capped SELECT is killed, from a second connection, before its rest is read.
    assert log["sql"][:4] == ["INSERT INTO t VALUES (1),(2)", "SELECT id FROM t", "KILL QUERY 7", "SELECT 'x'"]
    assert "missing" in out[3].message and len(log["sql"]) == 5


def test_a_killed_select_is_not_an_error(monkeypatch):
    log = _fake(monkeypatch, lambda sql: (ID, [(1,)] * (SCRIPT_ROW_CAP + 1)))
    log["close_error"] = OperationalError(1317, "Query execution was interrupted")
    out = asyncio.run(MySqlDriver().execute_script(CFG, "SELECT id FROM t; SELECT id FROM t", "shop"))
    assert [r.ok for r in out] == [True, True]
    # Any other error while reading the rest stands.
    log["close_error"] = OperationalError(2013, "Lost connection to MySQL server during query")
    out = asyncio.run(MySqlDriver().execute_script(CFG, "SELECT id FROM t", "shop"))
    assert not out[0].ok and "Lost connection" in out[0].message


def test_a_capped_call_is_read_to_its_end(monkeypatch):
    # The procedure may still write after its first result, so it is not killed.
    log = _fake(monkeypatch, lambda sql: (ID, [(1,)] * (SCRIPT_ROW_CAP + 1)))
    out = asyncio.run(MySqlDriver().execute_script(CFG, "call refresh_report()", "shop"))
    assert out[0].truncated and log["sql"] == ["call refresh_report()"] and log["drained"] == 1


def test_scripts_skip_hash_comments(monkeypatch):
    log = _fake(monkeypatch, lambda sql: (ID, [(1,)]))
    asyncio.run(MySqlDriver().execute_script(CFG, "# don't split here; nor here\nSELECT 1; SELECT 2", "shop"))
    assert log["sql"] == ["# don't split here; nor here\nSELECT 1", "SELECT 2"]


def test_run_sql_refuses_file_writes_before_connecting(monkeypatch):
    log = _fake(monkeypatch, lambda sql: (ID, [(1,)]))
    for sql in (
        "SELECT * FROM t INTO OUTFILE '/tmp/t.csv'",
        "select 1 into /* x */ dumpfile '/tmp/t.bin'",
        "SELECT 1 /*! INTO OUTFILE '/tmp/t.csv' */",
    ):
        r = asyncio.run(MySqlDriver().run_sql(CFG, sql, "shop", 10))
        assert isinstance(r, Err) and "INTO OUTFILE" in r.message
    assert "sql" not in log or log["sql"] == []
    # Quoted or commented out, the words are not code.
    for sql in ("SELECT 'into outfile'", "SELECT 1 # INTO OUTFILE '/tmp/t'", "SELECT 1 AS `into dumpfile`"):
        assert isinstance(asyncio.run(MySqlDriver().run_sql(CFG, sql, "shop", 10)), RowsResult)


def test_each_connection_gets_its_timeout_server_side(monkeypatch):
    log = _fake(monkeypatch, lambda sql: None if sql.startswith("SET") else (ID, [(1,)]))
    asyncio.run(MySqlDriver().run_sql(CFG, "SELECT 1", "shop", 10))
    asyncio.run(MySqlDriver().execute_script(CFG, "SELECT 1", "shop"))
    asyncio.run(MySqlDriver().run_query(CFG, "SELECT 1", "shop", 10, 0, None))
    assert log["timeouts"] == [RUN_SQL_TIMEOUT_SECONDS, SCRIPT_TIMEOUT_SECONDS, None]


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

    kwargs_seen = {}

    async def fake_connect(**kwargs):
        kwargs_seen.update(kwargs)
        return _Conn()

    monkeypatch.setattr("queryview.drivers.mysql.aiomysql.connect", fake_connect)
    asyncio.run(_raw_connect(CFG, "shop", 60))
    assert sent == [(COMMAND.COM_SET_OPTION, b"\x01\x00")]  # MYSQL_OPTION_MULTI_STATEMENTS_OFF
    # The server ends a SELECT at the same timeout the client gives up at.
    assert kwargs_seen["init_command"] == "SET SESSION max_execution_time = 60000"


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
