import os
import re
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Page, expect

# Mirror playwright.config.ts: 15s default assertion timeout.
expect.set_options(timeout=15_000)


def open_queries(page: Page) -> None:
    """Open the app on the Queries page.

    A live connection lands on the explorer — both on load (the landing
    redirect) and the moment a database is picked — and the backend session is
    shared across tests, so a previous test's connection can resume here. Query
    flows therefore navigate to Queries explicitly instead of assuming it."""
    page.goto("/", wait_until="networkidle")
    page.get_by_test_id("nav-queries").click()
    expect(page.get_by_test_id("prompt-input")).to_be_visible()


def connect_clickhouse_test_db(page: Page) -> None:
    """Connect with the ClickHouse form defaults and select the seeded `test`
    database. Ends on the explorer — picking a database lands there."""
    open_queries(page)
    page.get_by_test_id("prompt-input").fill("new clickhouse")
    page.keyboard.press("Enter")
    expect(page.get_by_test_id("clickhouse-form")).to_be_visible()
    page.get_by_test_id("ch-connect").click()
    expect(page.get_by_test_id("db-picker")).to_be_visible()
    page.locator('[data-db="test"]').click()
    expect(page.get_by_test_id("connection-status")).to_contain_text("connected - test")


def open_query_panel(page: Page) -> None:
    """Open the query panel from wherever the test is, via the Queries page."""
    page.get_by_test_id("nav-queries").click()
    page.get_by_test_id("prompt-input").fill("query")
    page.keyboard.press("Enter")
    expect(page.get_by_test_id("query-panel")).to_be_visible()


@pytest.fixture(scope="session")
def base_url() -> str:
    # The app under test is started separately (Vite dev server, or the FastAPI
    # backend serving the built SPA); point at it with BASE_URL.
    return os.environ.get("BASE_URL", "http://localhost:5173")


@pytest.fixture(scope="session", autouse=True)
def _git_sync_remote(base_url: str) -> None:
    """Point the default workspace at the remote CI stood up, through the same
    API a user would: the app has no env-var path to it. Unset locally, leaving
    git sync disabled and its round-trip test skipped."""
    remote = os.environ.get("E2E_GIT_REMOTE")
    if remote:
        r = httpx.patch(f"{base_url}/api/workspaces/default", json={"remote": remote})
        r.raise_for_status()


@pytest.fixture(scope="session")
def browser_type_launch_args(browser_type_launch_args: dict) -> dict:
    args = {**browser_type_launch_args, "args": ["--no-sandbox"]}
    # Environments with a pre-installed browser (no network to download the
    # pinned revision) can point the launch at it instead.
    exe = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    if exe:
        args["executable_path"] = exe
    return args


@pytest.fixture
def browser_context_args(browser_context_args: dict) -> dict:
    return {**browser_context_args, "viewport": {"width": 1280, "height": 900}}


@pytest.fixture
def shot(page: Page, output_path: str):
    """Save labeled, ordered screenshots into pytest-playwright's per-test
    output directory; files are numbered so an e2e screenshot report can
    preserve call order when bundling them into a self-contained HTML.
    """
    out = Path(output_path)
    counter = {"n": 0}

    def _shot(label: str) -> None:
        counter["n"] += 1
        safe = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-") or "shot"
        out.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out / f"{counter['n']:02d}-{safe}.png"), full_page=True)

    return _shot


# --- ClickHouse seeding for query tests -----------------------------------
# Coordinates default to the connection-form defaults the suite uses.
CH_HOST = os.environ.get("CLICKHOUSE_HOST", "localhost")
CH_PORT = os.environ.get("CLICKHOUSE_PORT", "8123")
CH_USER = os.environ.get("CLICKHOUSE_USER", "default")
CH_PASSWORD = os.environ.get("CLICKHOUSE_PASSWORD", "")


def _ch_exec(sql: str) -> None:
    """Run a statement against ClickHouse over HTTP. POST allows writes (the GET
    interface is read-only by default), so seeding/teardown go through here."""
    res = httpx.post(
        f"http://{CH_HOST}:{CH_PORT}/",
        content=sql.encode("utf-8"),
        auth=(CH_USER, CH_PASSWORD),
        timeout=10.0,
    )
    res.raise_for_status()


@pytest.fixture(scope="module")
def seeded_test_db():
    """Module-level: create a ClickHouse database named `test` with a small
    `items` table of known rows, then drop the whole database on teardown.

    Drops `test` up front too, so seeding is idempotent and never accumulates
    rows from an earlier run that left the database behind."""
    _ch_exec("DROP DATABASE IF EXISTS test")
    _ch_exec("CREATE DATABASE test")
    _ch_exec("CREATE TABLE test.items (id UInt32, name String) ENGINE = MergeTree ORDER BY id")
    _ch_exec("INSERT INTO test.items (id, name) VALUES (1, 'alpha'), (2, 'beta'), (3, 'gamma')")
    yield
    _ch_exec("DROP DATABASE IF EXISTS test")


# --- Postgres seeding for query tests -------------------------------------
PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = int(os.environ.get("PG_PORT", "5432"))
PG_USER = os.environ.get("PG_USER", "postgres")
PG_PASSWORD = os.environ.get("PG_PASSWORD", "")


@pytest.fixture(scope="module")
def seeded_pg_db():
    """Create a `qvtest` database with a small `items` table; drop it after.
    Uses asyncpg (a project dependency). The async work runs in a worker thread
    because pytest-playwright's sync API keeps an event loop on the main thread,
    so asyncio.run() can't be called there directly."""
    import asyncio
    import concurrent.futures

    import asyncpg

    async def _seed():
        sys = await asyncpg.connect(
            host=PG_HOST,
            port=PG_PORT,
            user=PG_USER,
            password=PG_PASSWORD or None,
            database="postgres",
        )
        await sys.execute("DROP DATABASE IF EXISTS qvtest WITH (FORCE)")
        await sys.execute("CREATE DATABASE qvtest")
        await sys.close()
        db = await asyncpg.connect(
            host=PG_HOST,
            port=PG_PORT,
            user=PG_USER,
            password=PG_PASSWORD or None,
            database="qvtest",
        )
        await db.execute("CREATE TABLE items (id int, name text)")
        await db.execute("INSERT INTO items (id, name) VALUES (1,'alpha'),(2,'beta'),(3,'gamma')")
        await db.close()

    async def _teardown():
        sys = await asyncpg.connect(
            host=PG_HOST,
            port=PG_PORT,
            user=PG_USER,
            password=PG_PASSWORD or None,
            database="postgres",
        )
        await sys.execute("DROP DATABASE IF EXISTS qvtest WITH (FORCE)")
        await sys.close()

    def _in_thread(make_coro):
        # A fresh thread has no running loop, so asyncio.run works there.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(lambda: asyncio.run(make_coro())).result()

    _in_thread(_seed)
    yield
    _in_thread(_teardown)


# --- DuckDB seeding for query tests ---------------------------------------
def _seed_duckdb(path, *names: str) -> str:
    """Create each named table with the suite's shared alpha/beta/gamma rows."""
    import duckdb

    con = duckdb.connect(str(path))
    for name in names:
        con.execute(f"CREATE TABLE {name} (id INTEGER, name TEXT)")
        con.execute(f"INSERT INTO {name} VALUES (1,'alpha'),(2,'beta'),(3,'gamma')")
    con.close()
    return str(path)


@pytest.fixture(scope="module")
def seeded_duckdb(tmp_path_factory) -> str:
    """A temp DuckDB file with a small `items` table; returns its path for the
    connection form to point at."""
    return _seed_duckdb(tmp_path_factory.mktemp("duck") / "qv.duckdb", "items")


@pytest.fixture(scope="module")
def seeded_duckdb_long_names(tmp_path_factory) -> str:
    """As above plus table names too long for the sidebar's default width, so
    the resize test exercises the truncation it exists to fix. Names are
    invented and generic."""
    return _seed_duckdb(
        tmp_path_factory.mktemp("duck_long") / "qv.duckdb",
        "items",
        "sales_reporting_monthly_rollup",
        "warehouse_shipment_reconciliation_log",
    )
