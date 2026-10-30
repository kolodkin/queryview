"""DuckDB-specific behavior against a real temp-file database: the :memory:
default, the empty (no-picker) database list, paginated typed queries, CSV export,
describe, and error reporting. Registry conformance, config round-trip, and
validation are covered by test_driver_contract."""

from __future__ import annotations

import asyncio
import os

import duckdb
import pytest

from queryview.drivers.base import DatabasesResult, Err, FieldsResult, RowsResult, TablesResult, TextResult
from queryview.drivers.duckdb import DuckConfig, DuckDBDriver


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def duck_path(tmp_path):
    path = tmp_path / "qv.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE items (id INTEGER, name TEXT)")
    con.execute("INSERT INTO items VALUES (1,'alpha'),(2,'beta'),(3,'gamma')")
    con.close()
    return str(path)


def test_parse_config_defaults_blank_path_to_memory():
    d = DuckDBDriver()
    assert d.parse_config({"path": ""})[0] == DuckConfig(":memory:")
    assert d.parse_config({"path": "/tmp/x.duckdb"})[0] == DuckConfig("/tmp/x.duckdb")


def test_list_databases_is_empty(duck_path):
    d = DuckDBDriver()
    assert _run(d.list_databases(DuckConfig(duck_path))) == DatabasesResult([])


def test_list_tables_names_seeded_table_with_estimates(duck_path):
    d = DuckDBDriver()
    # rows is duckdb_tables()'s estimated_size; bytes is storage blocks × block
    # size (a small positive multiple of the 256KiB block for a tiny table).
    r = _run(d.list_tables(DuckConfig(duck_path), None))
    assert isinstance(r, TablesResult) and len(r.tables) == 1
    t = r.tables[0]
    assert t["name"] == "items" and t["rows"] == 3
    assert isinstance(t["bytes"], int) and t["bytes"] > 0


def test_run_query_paginates_and_returns_typed_rows(duck_path):
    d = DuckDBDriver()
    r = _run(
        d.run_query(
            DuckConfig(duck_path),
            "SELECT id, name FROM items ORDER BY id",
            None,
            2,
            0,
            [{"name": "name", "dir": "ASC"}],
        )
    )
    assert isinstance(r, RowsResult)
    assert [c.name for c in r.rows.meta] == ["id", "name"]
    assert all(isinstance(c.type, str) and c.type for c in r.rows.meta)
    assert r.rows.data == [[1, "alpha"], [2, "beta"]]


def test_export_csv_returns_csv_with_names(duck_path):
    d = DuckDBDriver()
    r = _run(d.export_csv(DuckConfig(duck_path), "SELECT id, name FROM items ORDER BY id", None, 2, 0, None))
    assert isinstance(r, TextResult) and r.text == "id,name\n1,alpha\n2,beta"


def test_describe_query_returns_columns(duck_path):
    d = DuckDBDriver()
    r = _run(d.describe_query(DuckConfig(duck_path), "SELECT id, name FROM items", None))
    assert isinstance(r, FieldsResult)
    names = [f["name"] for f in r.fields]
    assert names == ["id", "name"]


def test_run_query_error_is_reported(duck_path):
    d = DuckDBDriver()
    r = _run(d.run_query(DuckConfig(duck_path), "SELECT * FROM no_such", None, 10, 0, None))
    assert isinstance(r, Err) and "no_such" in r.message


def test_execute_script_runs_statements_in_order_on_one_connection(duck_path):
    d = DuckDBDriver()
    results = _run(
        d.execute_script(
            DuckConfig(duck_path),
            "CREATE TABLE extra (id INTEGER); INSERT INTO extra VALUES (7); SELECT id FROM extra",
            None,
        )
    )
    assert [r.ok for r in results] == [True, True, True]
    assert [r.sql for r in results] == [
        "CREATE TABLE extra (id INTEGER)",
        "INSERT INTO extra VALUES (7)",
        "SELECT id FROM extra",
    ]
    # Statements without a result set report a status; row-returning ones carry rows.
    assert results[0].rows is None and results[0].status == "OK"
    assert results[2].rows is not None and results[2].rows.data == [[7]]
    assert [c.name for c in results[2].rows.meta] == ["id"]
    assert all(r.elapsed_ms >= 0 for r in results)
    # The write landed in the file.
    assert duckdb.connect(duck_path, read_only=True).execute("SELECT count(*) FROM extra").fetchone() == (1,)


def test_execute_script_stops_at_the_first_failing_statement(duck_path):
    d = DuckDBDriver()
    results = _run(d.execute_script(DuckConfig(duck_path), "SELECT 1; SELECT * FROM no_such; SELECT 2", None))
    assert len(results) == 2
    assert results[0].ok
    assert results[1].ok is False and "no_such" in results[1].message and results[1].sql == "SELECT * FROM no_such"


def test_execute_script_caps_rows_and_flags_truncation(duck_path):
    d = DuckDBDriver()
    results = _run(d.execute_script(DuckConfig(duck_path), "SELECT * FROM range(1500)", None))
    assert results[0].ok and results[0].rows is not None
    assert len(results[0].rows.data) == 100 and results[0].truncated is True
    results = _run(d.execute_script(DuckConfig(duck_path), "SELECT * FROM range(3)", None))
    assert results[0].truncated is False


def test_execute_script_reports_a_runtime_error_as_a_failed_statement(duck_path):
    # A relation binds lazily: the cast only fails when the rows are fetched.
    d = DuckDBDriver()
    results = _run(d.execute_script(DuckConfig(duck_path), "SELECT 1 AS a; SELECT 'abc'::INTEGER AS b; SELECT 2", None))
    assert [r.ok for r in results] == [True, False]
    assert "abc" in results[1].message


def test_describe_and_export_errors_become_err(duck_path):
    d = DuckDBDriver()
    r = _run(d.describe_query(DuckConfig(duck_path), "SELECT * FROM no_such", None))
    assert isinstance(r, Err) and "no_such" in r.message
    r = _run(d.export_csv(DuckConfig(duck_path), "SELECT * FROM no_such", None, 10, 0, None))
    assert isinstance(r, Err) and "no_such" in r.message


# --- folder mode -------------------------------------------------------------


@pytest.fixture
def folder(tmp_path):
    """A root with data files, a compressed file in a subfolder, a folder past
    FOLDER_DEPTH, a hidden folder and a symlink — the last three never listed."""
    import gzip

    (tmp_path / "items.csv").write_text("id,name\n1,alpha\n2,beta\n3,gamma\n")
    (tmp_path / "extra.csv").write_text("id,name\n4,delta\n")
    (tmp_path / "o'neil.csv").write_text("id,name\n5,epsilon\n")
    sub = tmp_path / "sub"
    sub.mkdir()
    with gzip.open(sub / "nested.csv.gz", "wt") as f:
        f.write("id,name\n1,alpha\n2,beta\n3,gamma\n")
    deep = sub / "deep1" / "deep2" / "deep3" / "deep4"
    deep.mkdir(parents=True)
    (deep / "x.csv").write_text("id\n1\n")
    hidden = tmp_path / ".hidden"
    hidden.mkdir()
    (hidden / "h.csv").write_text("id\n1\n")
    (tmp_path / "link").symlink_to(sub, target_is_directory=True)
    return str(tmp_path)


def test_list_databases_in_folder_mode_lists_root_and_subfolders(folder):
    r = _run(DuckDBDriver().list_databases(DuckConfig(folder)))
    assert r.root == folder
    # .hidden and the symlink are absent; deep4 is past FOLDER_DEPTH
    assert r.databases == [".", "sub", "sub/deep1", "sub/deep1/deep2", "sub/deep1/deep2/deep3"]


def test_test_connection_succeeds_on_a_folder(folder):
    assert _run(DuckDBDriver().test(DuckConfig(folder)))["ok"] is True


def test_list_tables_in_folder_mode_lists_files_and_globs(folder):
    r = _run(DuckDBDriver().list_tables(DuckConfig(folder), "."))
    names = [t["name"] for t in r.tables]
    assert names == ["extra.csv", "items.csv", "o'neil.csv", "*.csv"]
    items = next(t for t in r.tables if t["name"] == "items.csv")
    assert items["rows"] is None and items["bytes"] == os.path.getsize(os.path.join(folder, "items.csv"))
    assert items["query"] == "SELECT * FROM read_csv('items.csv')"
    glob = r.tables[-1]
    assert glob["query"] == "SELECT * FROM read_csv(['extra.csv', 'items.csv', 'o''neil.csv'])"
    assert glob["bytes"] == sum(t["bytes"] for t in r.tables[:-1])
    quoted = next(t for t in r.tables if t["name"] == "o'neil.csv")
    assert quoted["query"] == "SELECT * FROM read_csv('o''neil.csv')"
    rows = _run(DuckDBDriver().run_query(DuckConfig(folder), quoted["query"], ".", 10, 0, None))
    assert rows.rows.data == [[5, "epsilon"]]


def test_list_tables_union_flag_only_changes_globs(folder):
    r = _run(DuckDBDriver().list_tables(DuckConfig(folder), ".", union=True))
    assert (
        r.tables[-1]["query"]
        == "SELECT * FROM read_csv(['extra.csv', 'items.csv', 'o''neil.csv'], union_by_name = true)"
    )
    assert r.tables[0]["query"] == "SELECT * FROM read_csv('extra.csv')"


def test_list_tables_recognizes_compressed_files_in_a_subfolder(folder):
    r = _run(DuckDBDriver().list_tables(DuckConfig(folder), "sub"))
    assert [t["name"] for t in r.tables] == ["nested.csv.gz"]
    assert r.tables[0]["query"] == "SELECT * FROM read_csv('nested.csv.gz', compression = 'gzip')"


def test_folder_queries_resolve_relative_to_the_selected_folder(folder):
    d = DuckDBDriver()
    cfg = DuckConfig(folder)
    r = _run(d.run_query(cfg, "SELECT * FROM read_csv('items.csv')", ".", 10, 0, [{"name": "id", "dir": "ASC"}]))
    assert r.rows.data == [[1, "alpha"], [2, "beta"], [3, "gamma"]]
    r = _run(d.run_query(cfg, "SELECT count(*) AS n FROM read_csv('nested.csv.gz')", "sub", 10, 0, None))
    assert isinstance(r, RowsResult) and r.rows.data == [[3]]
    r = _run(d.run_query(cfg, "SELECT count(*) AS n FROM read_csv('*.csv', union_by_name = true)", ".", 10, 0, None))
    assert r.rows.data == [[5]]


def test_glob_entries_read_only_the_listed_files(tmp_path):
    """Hidden, symlinked and glob-named files are skipped by the listing, so the
    glob entry names its files explicitly rather than letting DuckDB expand a
    pattern that would follow the symlink out of the root; upper-case
    extensions still read, with the compression spelled out."""
    import gzip

    outside = tmp_path / "secret.csv"
    outside.write_text("id,name\n9,outside\n")
    root = tmp_path / "root"
    root.mkdir()
    (root / "A.CSV").write_text("id,name\n1,alpha\n")
    (root / "b.csv").write_text("id,name\n2,beta\n")
    (root / ".hid.csv").write_text("id,name\n8,hidden\n")
    (root / "evil.csv").symlink_to(outside)
    (root / "r[1].csv").write_text("id,name\n7,bracket\n")
    (root / "r1.csv").write_text("id,name\n3,gamma\n")
    with gzip.open(root / "C.CSV.GZ", "wt") as f:
        f.write("id,name\n4,delta\n")
    d = DuckDBDriver()
    r = _run(d.list_tables(DuckConfig(str(root)), "."))
    assert [t["name"] for t in r.tables] == ["A.CSV", "C.CSV.GZ", "b.csv", "r1.csv", "*.csv"]
    glob = r.tables[-1]
    assert glob["query"] == "SELECT * FROM read_csv(['A.CSV', 'b.csv', 'r1.csv'])"
    assert glob["bytes"] == sum(t["bytes"] for t in r.tables if t["name"] in ("A.CSV", "b.csv", "r1.csv"))
    assert r.tables[1]["query"] == "SELECT * FROM read_csv('C.CSV.GZ', compression = 'gzip')"
    for t in r.tables:
        rows = _run(d.run_query(DuckConfig(str(root)), t["query"], ".", 10, 0, [{"name": "id", "dir": "ASC"}]))
        assert isinstance(rows, RowsResult), (t["name"], rows)
    rows = _run(d.run_query(DuckConfig(str(root)), glob["query"], ".", 10, 0, [{"name": "id", "dir": "ASC"}]))
    assert rows.rows.data == [[1, "alpha"], [2, "beta"], [3, "gamma"]]


def test_folders_with_a_comma_are_not_browsable(tmp_path):
    # file_search_path is a comma-separated list, so such a path cannot be set.
    (tmp_path / "a,b").mkdir()
    (tmp_path / "ok").mkdir()
    r = _run(DuckDBDriver().list_databases(DuckConfig(str(tmp_path))))
    assert r.databases == [".", "ok"]
    comma_root = tmp_path / "x,y"
    comma_root.mkdir()
    r = _run(DuckDBDriver().list_databases(DuckConfig(str(comma_root))))
    assert isinstance(r, Err) and "comma" in r.message
