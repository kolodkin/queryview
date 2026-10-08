import os
import re
import socket
import subprocess
import sys
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from playwright.sync_api import Page, expect

# Mirror playwright.config.ts: 15s default assertion timeout.
expect.set_options(timeout=15_000)


def open_connect(page: Page) -> None:
    """Open the app on the Connect page.

    A live connection lands on the explorer, and the backend session is shared
    across tests, so a previous test's connection can resume here. Connect
    flows navigate there explicitly rather than assuming it."""
    page.goto("/", wait_until="networkidle")
    page.get_by_test_id("nav-connect").click()
    expect(page.get_by_test_id("connect-page")).to_be_visible()


def start_new_connection(page: Page, driver: str) -> None:
    """Open a driver's connection form through the Connect page's "+ New" menu,
    present however many connections are saved, and point it at the suite's
    server: the form defaults are a passwordless localhost login."""
    page.get_by_test_id("new-menu-toggle").click()
    page.get_by_test_id("new-menu").get_by_test_id(f"new-conn-{driver}").click()
    servers = {
        "clickhouse": ("ch", CH_HOST, CH_PORT, CH_USER, CH_PASSWORD),
        "postgres": ("pg", PG_HOST, str(PG_PORT), PG_USER, PG_PASSWORD),
    }
    if driver in servers:
        prefix, *values = servers[driver]
        for field, value in zip(("host", "port", "username", "password"), values, strict=True):
            page.get_by_test_id(f"{prefix}-{field}").fill(value)


def connect_clickhouse_test_db(page: Page) -> None:
    """Connect to ClickHouse and select the seeded `qvtest` database. Ends on
    the explorer, where picking a database lands."""
    open_connect(page)
    start_new_connection(page, "clickhouse")
    expect(page.get_by_test_id("clickhouse-form")).to_be_visible()
    page.get_by_test_id("ch-connect").click()
    expect(page.get_by_test_id("db-picker")).to_be_visible()
    page.locator(f'[data-db="{CH_DB}"]').click()
    expect(page.get_by_test_id("connection-status")).to_contain_text(f"connected - {CH_DB}")


def author_params_yaml(page: Page, name: str, sql: str, params_yaml: str) -> None:
    """Fill the SQL, name the query, and author a `params:` block via the
    cell-view modal, then Save. Shared by the query-param tests."""
    page.get_by_test_id("query-input").fill(sql)
    page.once("dialog", lambda d: d.accept(name))
    page.get_by_test_id("query-predefined-select").select_option("::new::")
    page.get_by_test_id("cell-view-toggle").click()
    expect(page.get_by_test_id("cell-view-modal")).to_be_visible()
    page.get_by_test_id("cell-view-input").fill(params_yaml)
    page.get_by_test_id("cell-view-save").click()
    expect(page.get_by_test_id("cell-view-modal")).not_to_be_visible()


def open_query_panel(page: Page) -> None:
    """Open the query panel from wherever the test is, via the Queries page."""
    page.get_by_test_id("nav-queries").click()
    expect(page.get_by_test_id("query-panel")).to_be_visible()


@pytest.fixture
def context(context, base_url: str):
    """Give every test its own session.

    Session state lives on the server, so a fresh browser context is no longer
    fresh state: without this a test would resume the previous one's session and
    inherit its remembered SQL, sidebar width and workspace.

    Seeds `qv_session` but never `qv_tab`, so each page still mints its own tab
    token and a second tab opened inside a test correctly starts its own
    session.
    """
    tab = f"e2e-{uuid.uuid4().hex}"
    # `select` with no id always creates a session. `attach` would resume the
    # most recent unheld one — the previous test's, once its tab has released.
    created = httpx.post(f"{base_url}/api/sessions/select", json={"tab": tab})
    session = created.json()["session"]
    assert session["ui"] == {}, "the context fixture resumed a used session"
    sid = session["id"]
    # Release it so the page's own tab token can claim it on load.
    httpx.post(f"{base_url}/api/sessions/release", json={"tab": tab})
    context.add_init_script(f"sessionStorage.setItem('qv_session', {sid!r});")
    return context


@pytest.fixture(scope="session")
def base_url(tmp_path_factory) -> Iterator[str]:
    """The app under test. BASE_URL points at one started separately (a Vite
    dev server, or a backend serving the built SPA). Unset, each pytest process
    starts its own backend on a free port and a throwaway DATA_DIR, so under
    pytest-xdist every worker has private connections, workspaces and sessions
    and no test can see another's — only the database servers are shared.
    The backend is the one installed in this interpreter's environment, so the
    release gate's installed wheel is what runs when it is the thing in .venv."""
    env_url = os.environ.get("BASE_URL")
    if env_url:
        yield env_url
        return
    with socket.socket() as s:
        s.bind(("", 0))
        port = s.getsockname()[1]
    data_dir = tmp_path_factory.mktemp("data")
    log = (data_dir / "backend.log").open("w")
    proc = subprocess.Popen(
        [str(Path(sys.executable).parent / "queryview-backend")],
        env={**os.environ, "SERVE_STATIC": "1", "PORT": str(port), "DATA_DIR": str(data_dir)},
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    url = f"http://localhost:{port}"
    try:
        deadline = time.monotonic() + 60
        while True:
            try:
                if httpx.get(f"{url}/api/health", timeout=1.0).is_success:
                    break
            except httpx.HTTPError:
                pass
            if proc.poll() is not None or time.monotonic() > deadline:
                log.close()
                raise RuntimeError(f"backend did not come up:\n{(data_dir / 'backend.log').read_text()}")
            time.sleep(0.1)
        yield url
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


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
# Not `test`: a name that generic may already hold someone's data, and the
# fixture drops it. Under pytest-xdist each worker seeds (and drops) its own
# database, so one worker's module-scoped teardown can't pull the table out
# from under another's running test.
_WORKER_SUFFIX = os.environ.get("PYTEST_XDIST_WORKER", "")
CH_DB = f"qvtest_{_WORKER_SUFFIX}" if _WORKER_SUFFIX else "qvtest"


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
    """Module-level: create a ClickHouse database named `qvtest` with a small
    `items` table of known rows, then drop the whole database on teardown.

    Drops it up front too, so seeding is idempotent and never accumulates rows
    from an earlier run that left the database behind."""
    _ch_exec(f"DROP DATABASE IF EXISTS {CH_DB}")
    _ch_exec(f"CREATE DATABASE {CH_DB}")
    _ch_exec(f"CREATE TABLE {CH_DB}.items (id UInt32, name String) ENGINE = MergeTree ORDER BY id")
    _ch_exec(f"INSERT INTO {CH_DB}.items (id, name) VALUES (1, 'alpha'), (2, 'beta'), (3, 'gamma')")
    yield
    _ch_exec(f"DROP DATABASE IF EXISTS {CH_DB}")


# --- Postgres seeding for query tests -------------------------------------
PG_HOST = os.environ.get("PG_HOST", "localhost")
PG_PORT = int(os.environ.get("PG_PORT", "5432"))
PG_USER = os.environ.get("PG_USER", "postgres")
PG_PASSWORD = os.environ.get("PG_PASSWORD", "")
PG_DB = CH_DB  # same per-worker name, for the same reason


@pytest.fixture(scope="module")
def seeded_pg_db():
    """Create a `PG_DB` database with a small `items` table; drop it after.
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
        await sys.execute(f"DROP DATABASE IF EXISTS {PG_DB} WITH (FORCE)")
        await sys.execute(f"CREATE DATABASE {PG_DB}")
        await sys.close()
        db = await asyncpg.connect(
            host=PG_HOST,
            port=PG_PORT,
            user=PG_USER,
            password=PG_PASSWORD or None,
            database=PG_DB,
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
        await sys.execute(f"DROP DATABASE IF EXISTS {PG_DB} WITH (FORCE)")
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
    """As above plus invented names too long for the sidebar's default width,
    so the resize test exercises the truncation it exists to fix."""
    return _seed_duckdb(
        tmp_path_factory.mktemp("duck_long") / "qv.duckdb",
        "items",
        "sales_reporting_monthly_rollup",
        "warehouse_shipment_reconciliation_log",
    )
