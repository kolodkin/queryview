"""DuckDB-specific behavior against a real temp file: the :memory: default,
lazy runtime errors, and folder mode. Shared file-driver behavior is in
test_file_drivers; registry conformance and config round-trip in test_contract."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Coroutine
from typing import Any, TypeVar

import duckdb
import pytest

from queryview.drivers.base import Err, RowsResult, TablesResult
from queryview.drivers.duckdb import DuckConfig, DuckDBDriver

T = TypeVar("T")


def _run(coro):
    return asyncio.run(coro)


def _ok(coro: Coroutine[Any, Any, T | Err]) -> T:
    """Run a driver call that must succeed, narrowed to its result type."""
    r = asyncio.run(coro)
    assert not isinstance(r, Err), r
    return r


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


def test_list_tables_names_seeded_table_with_estimates(duck_path):
    d = DuckDBDriver()
    # rows is duckdb_tables()'s estimated_size; bytes is storage blocks × block
    # size (a small positive multiple of the 256KiB block for a tiny table).
    r = _run(d.list_tables(DuckConfig(duck_path), None))
    assert isinstance(r, TablesResult) and len(r.tables) == 1
    t = r.tables[0]
    assert t["name"] == "items" and t["rows"] == 3
    assert isinstance(t["bytes"], int) and t["bytes"] > 0


def test_execute_script_reports_a_runtime_error_as_a_failed_statement(duck_path):
    # A relation binds lazily: the cast only fails when the rows are fetched.
    d = DuckDBDriver()
    results = _run(d.execute_script(DuckConfig(duck_path), "SELECT 1 AS a; SELECT 'abc'::INTEGER AS b; SELECT 2", None))
    assert [r.ok for r in results] == [True, False]
    assert "abc" in results[1].message


# --- folder mode -------------------------------------------------------------


@pytest.fixture
def folder(tmp_path):
    """A root with data files, a compressed file in a subfolder, a folder past
    a hidden folder and a symlink — the last two never listed."""
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


def test_list_databases_in_folder_mode_lists_one_level(folder):
    d = DuckDBDriver()
    r = _ok(d.list_databases(DuckConfig(folder)))
    assert r.root == folder and r.current == "." and r.truncated is False
    # Only the root's own subfolders; .hidden and the symlink are skipped.
    assert r.databases == [".", "sub"]
    # A deep current folder: its parent chain, itself, and its own subfolders.
    r = _ok(d.list_databases(DuckConfig(folder), current="sub/deep1"))
    assert r.current == "sub/deep1"
    assert r.databases == [".", "sub", "sub/deep1", "sub/deep1/deep2"]


def test_a_current_folder_that_is_gone_resolves_to_its_nearest_parent(folder):
    r = _ok(DuckDBDriver().list_databases(DuckConfig(folder), current="sub/deep1/missing/x"))
    assert r.current == "sub/deep1"


@pytest.mark.parametrize("bad", ["../x", "/etc", ".hidden", "link", "sub/../..", "sub//deep1", ""])
def test_a_current_folder_outside_the_rules_resolves_to_the_root(folder, bad):
    assert _ok(DuckDBDriver().list_databases(DuckConfig(folder), current=bad)).current == "."


def test_test_connection_succeeds_on_a_folder(folder):
    assert _run(DuckDBDriver().test(DuckConfig(folder)))["ok"] is True


def test_list_tables_in_folder_mode_lists_files_and_globs(folder):
    r = _ok(DuckDBDriver().list_tables(DuckConfig(folder), "."))
    names = [t["name"] for t in r.tables]
    assert names == ["extra.csv", "items.csv", "o'neil.csv", "*.csv"]
    items = next(t for t in r.tables if t["name"] == "items.csv")
    assert items["rows"] is None and items["bytes"] == os.path.getsize(os.path.join(folder, "items.csv"))
    assert items["query"] == "SELECT * FROM read_csv('items.csv')"
    glob = r.tables[-1]
    assert glob["path"] is None  # a glob has no single file to name
    assert glob["query"] == "SELECT * FROM read_csv(['extra.csv', 'items.csv', 'o''neil.csv'])"
    assert glob["bytes"] == sum(t["bytes"] for t in r.tables[:-1])
    quoted = next(t for t in r.tables if t["name"] == "o'neil.csv")
    assert quoted["query"] == "SELECT * FROM read_csv('o''neil.csv')"
    rows = _ok(DuckDBDriver().run_query(DuckConfig(folder), quoted["query"], ".", 10, 0, None))
    assert rows.rows.data == [[5, "epsilon"]]


def test_list_tables_union_flag_only_changes_globs(folder):
    r = _ok(DuckDBDriver().list_tables(DuckConfig(folder), ".", union=True))
    assert (
        r.tables[-1]["query"]
        == "SELECT * FROM read_csv(['extra.csv', 'items.csv', 'o''neil.csv'], union_by_name = true)"
    )
    assert r.tables[0]["query"] == "SELECT * FROM read_csv('extra.csv')"


def test_list_tables_recognizes_compressed_files_in_a_subfolder(folder):
    r = _ok(DuckDBDriver().list_tables(DuckConfig(folder), "sub"))
    assert [t["name"] for t in r.tables] == ["nested.csv.gz"]
    assert r.tables[0]["path"] == "sub/nested.csv.gz"  # shown and copied by the Explorer
    # Paths are from the root, so the same SQL works whichever folder is selected.
    assert r.tables[0]["query"] == "SELECT * FROM read_csv('sub/nested.csv.gz', compression = 'gzip')"


def test_folder_queries_resolve_relative_to_the_root(folder):
    d = DuckDBDriver()
    cfg = DuckConfig(folder)
    r = _ok(d.run_query(cfg, "SELECT * FROM read_csv('items.csv')", ".", 10, 0, [{"name": "id", "dir": "ASC"}]))
    assert r.rows.data == [[1, "alpha"], [2, "beta"], [3, "gamma"]]
    for selected in ("sub", "."):
        r = _ok(d.run_query(cfg, "SELECT count(*) AS n FROM read_csv('sub/nested.csv.gz')", selected, 10, 0, None))
        assert isinstance(r, RowsResult) and r.rows.data == [[3]]
    r = _ok(d.run_query(cfg, "SELECT count(*) AS n FROM read_csv('*.csv', union_by_name = true)", ".", 10, 0, None))
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
    r = _ok(d.list_tables(DuckConfig(str(root)), "."))
    assert [t["name"] for t in r.tables] == ["A.CSV", "C.CSV.GZ", "b.csv", "r1.csv", "*.csv"]
    glob = r.tables[-1]
    assert glob["query"] == "SELECT * FROM read_csv(['A.CSV', 'b.csv', 'r1.csv'])"
    assert glob["bytes"] == sum(t["bytes"] for t in r.tables if t["name"] in ("A.CSV", "b.csv", "r1.csv"))
    assert r.tables[1]["query"] == "SELECT * FROM read_csv('C.CSV.GZ', compression = 'gzip')"
    for t in r.tables:
        rows = _ok(d.run_query(DuckConfig(str(root)), t["query"], ".", 10, 0, [{"name": "id", "dir": "ASC"}]))
        assert isinstance(rows, RowsResult), (t["name"], rows)
    rows = _ok(d.run_query(DuckConfig(str(root)), glob["query"], ".", 10, 0, [{"name": "id", "dir": "ASC"}]))
    assert rows.rows.data == [[1, "alpha"], [2, "beta"], [3, "gamma"]]


def test_a_comma_is_refused_only_in_the_root(tmp_path):
    # file_search_path (the root) is a comma-separated list; subfolders only
    # appear inside string literals, where a comma is fine.
    (tmp_path / "a,b").mkdir()
    (tmp_path / "a,b" / "x.csv").write_text("id\n1\n")
    d = DuckDBDriver()
    r = _ok(d.list_databases(DuckConfig(str(tmp_path))))
    assert r.databases == [".", "a,b"]
    q = _ok(d.list_tables(DuckConfig(str(tmp_path)), "a,b")).tables[0]["query"]
    assert _ok(d.run_query(DuckConfig(str(tmp_path)), q, "a,b", 10, 0, None)).rows.data == [[1]]
    comma_root = tmp_path / "x,y"
    comma_root.mkdir()
    r = _run(DuckDBDriver().list_databases(DuckConfig(str(comma_root))))
    assert isinstance(r, Err) and "comma" in r.message


def test_a_vanished_folder_root_is_an_error_not_a_new_database_file(tmp_path):
    # A folder session passes its selected folder; if the root is gone, opening
    # it as a file would create a .duckdb file where the folder was.
    root = tmp_path / "gone"
    out = _run(DuckDBDriver().execute_script(DuckConfig(str(root)), "SELECT 1", "."))
    assert out[0].ok is False
    assert not root.exists()


def test_folder_listing_cuts_one_level_at_the_limit(tmp_path):
    for d in ("a/x", "b", "c"):
        (tmp_path / d).mkdir(parents=True)
    d = DuckDBDriver()
    r = _ok(d.list_databases(DuckConfig(str(tmp_path)), limit=2))
    assert r.databases == [".", "a", "b"] and r.truncated is True
    # The limit cuts the shown level, never the path to the current folder.
    r = _ok(d.list_databases(DuckConfig(str(tmp_path)), limit=1, current="c"))
    assert r.databases == [".", "c"] and r.current == "c" and r.truncated is False


def test_file_listing_stops_at_the_limit(tmp_path):
    for n in ("a.csv", "b.csv", "c.csv"):
        (tmp_path / n).write_text("id\n1\n")
    r = _ok(DuckDBDriver().list_tables(DuckConfig(str(tmp_path)), ".", limit=2))
    assert [t["name"] for t in r.tables] == ["a.csv", "b.csv", "*.csv"] and r.truncated is True
    assert r.tables[-1]["query"] == "SELECT * FROM read_csv(['a.csv', 'b.csv'])"
    r = _ok(DuckDBDriver().list_tables(DuckConfig(str(tmp_path)), ".", limit=3))
    assert r.truncated is False


def test_test_and_connect_agree_on_a_comma_root(tmp_path):
    # Test used to pass a root that connecting then refused.
    comma = tmp_path / "a,b"
    comma.mkdir()
    d = DuckDBDriver()
    assert _run(d.test(DuckConfig(str(comma))))["ok"] is False
    assert isinstance(_run(d.list_databases(DuckConfig(str(comma)))), Err)
