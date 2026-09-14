from conftest import open_queries
from playwright.sync_api import Page, expect

# The generic connect -> query -> paginate -> CSV -> describe flow (including
# ClickHouse) is parameterized in test_drivers.py. This module covers the
# ClickHouse-specific query features: cell views, query params, and the
# default views for Array/Map/Tuple types.


def _open_query_panel(page: Page) -> None:
    """Connect with form defaults, select the seeded `test` db, open the panel."""
    open_queries(page)
    page.get_by_test_id("prompt-input").fill("new clickhouse")
    page.keyboard.press("Enter")
    expect(page.get_by_test_id("clickhouse-form")).to_be_visible()
    page.get_by_test_id("ch-connect").click()
    expect(page.get_by_test_id("db-picker")).to_be_visible()
    page.locator('[data-db="test"]').click()
    expect(page.get_by_test_id("connection-status")).to_contain_text("connected - test")
    # Selecting a database lands on the explorer; the prompt is back on Queries.
    page.get_by_test_id("nav-queries").click()
    page.get_by_test_id("prompt-input").fill("query")
    page.keyboard.press("Enter")
    expect(page.get_by_test_id("query-panel")).to_be_visible()


def test_cell_view_renders_link_and_custom_html(seeded_test_db, page: Page, shot) -> None:
    """Saving a predefined query with a cell_view YAML map renders cells per
    the map: `link` becomes an <a href> using {cell}, `custom` injects the
    template with {cell} HTML-escaped. Both wrappers carry an automatic
    data-testid="cell-<col>" so tests can target them without baking testids
    into the YAML. The YAML is authored in a modal opened from the toolbar."""
    _open_query_panel(page)

    page.get_by_test_id("query-input").fill("SELECT id, name FROM items ORDER BY id LIMIT 2")
    shot("cell view toggle in toolbar")

    # Name the query first — the modal Save is disabled without a name.
    page.once("dialog", lambda d: d.accept("with-views"))
    page.get_by_test_id("query-predefined-select").select_option("::new::")

    # Open the cell-view modal and author the YAML.
    page.get_by_test_id("cell-view-toggle").click()
    expect(page.get_by_test_id("cell-view-modal")).to_be_visible()
    page.get_by_test_id("cell-view-input").fill(
        "name:\n"
        "  type: link\n"
        "  value: https://example.com/{cell}\n"
        "id:\n"
        "  type: custom\n"
        '  value: <strong style="color:#a5b4fc">{cell}</strong>\n'
    )
    shot("cell view modal - YAML authored")

    # Save persists cell_view + sql under the selected name and closes the modal.
    page.get_by_test_id("cell-view-save").click()
    expect(page.get_by_test_id("cell-view-modal")).not_to_be_visible()
    expect(page.get_by_test_id("query-predefined-select").locator('option[value="with-views"]')).to_have_count(1)
    shot("saved - modal closed")

    page.get_by_test_id("query-run").click()
    output = page.get_by_test_id("query-output")
    expect(output).to_be_visible()

    # The `name` column renders as an <a href> built from the template and
    # carries an auto data-testid="cell-name" on the link itself.
    link = output.get_by_test_id("cell-name").first
    expect(link).to_be_visible()
    expect(link).to_have_text("alpha")
    expect(link).to_have_attribute("href", "https://example.com/alpha")
    expect(link).to_have_attribute("target", "_blank")
    expect(link).to_have_attribute("rel", "noopener noreferrer")

    # The `id` column renders the custom template wrapped in a span whose
    # auto data-testid="cell-id" exposes it without test markup in the YAML.
    custom = output.get_by_test_id("cell-id").first
    expect(custom).to_be_visible()
    expect(custom).to_have_text("1")
    expect(custom.locator("strong")).to_have_text("1")
    shot("results: name as link, id as custom HTML")


def test_cell_view_row_placeholder_references_other_columns(seeded_test_db, page: Page, shot) -> None:
    """A cell_view template can reference other columns of the same row via
    `{row.<col>}`. Here the `name` column renders as a link whose href is built
    from a sibling column (`{row.id}`), and a `custom` cell combines `{cell}`
    with `{row.name}` — each row resolves against its own values."""
    _open_query_panel(page)

    page.get_by_test_id("query-input").fill("SELECT id, name FROM items ORDER BY id LIMIT 2")
    page.once("dialog", lambda d: d.accept("with-row-refs"))
    page.get_by_test_id("query-predefined-select").select_option("::new::")

    page.get_by_test_id("cell-view-toggle").click()
    expect(page.get_by_test_id("cell-view-modal")).to_be_visible()
    page.get_by_test_id("cell-view-input").fill(
        "name:\n"
        "  type: link\n"
        "  value: https://example.com/items/{row.id}\n"
        "id:\n"
        "  type: custom\n"
        "  value: <em>{cell}:{row.name}</em>\n"
    )
    shot("cell view modal - row.* placeholders authored")
    page.get_by_test_id("cell-view-save").click()
    expect(page.get_by_test_id("cell-view-modal")).not_to_be_visible()

    page.get_by_test_id("query-run").click()
    output = page.get_by_test_id("query-output")
    expect(output).to_be_visible()

    # First row (id=1, name=alpha): the `name` link's href uses {row.id}.
    link = output.get_by_test_id("cell-name").first
    expect(link).to_have_text("alpha")
    expect(link).to_have_attribute("href", "https://example.com/items/1")

    # The `id` custom cell combines {cell} (=1) with {row.name} (=alpha).
    custom = output.get_by_test_id("cell-id").first
    expect(custom.locator("em")).to_have_text("1:alpha")
    shot("results: row.* placeholders resolved per row")


def test_cell_view_cancel_discards_edits(seeded_test_db, page: Page, shot) -> None:
    """Cancel in the cell-view modal closes without saving, so rendering still
    uses the saved cell_view (or none) — author-time edits never leak through."""
    _open_query_panel(page)

    page.get_by_test_id("query-input").fill("SELECT name FROM items ORDER BY id LIMIT 1")
    page.get_by_test_id("cell-view-toggle").click()
    expect(page.get_by_test_id("cell-view-modal")).to_be_visible()
    page.get_by_test_id("cell-view-input").fill("name:\n  type: link\n  value: https://example.com/{cell}\n")
    shot("cell view modal - draft YAML before Cancel")
    page.get_by_test_id("cell-view-cancel").click()
    expect(page.get_by_test_id("cell-view-modal")).not_to_be_visible()

    page.get_by_test_id("query-run").click()
    output = page.get_by_test_id("query-output")
    expect(output).to_be_visible()
    # Nothing saved => no cell_view applied => plain text, no <a>.
    expect(output.locator("a")).to_have_count(0)
    expect(output).to_contain_text("alpha")

    # Re-opening the modal shows the saved value (empty) — Cancel reverted the edit.
    page.get_by_test_id("cell-view-toggle").click()
    expect(page.get_by_test_id("cell-view-input")).to_have_value("")


def test_default_views_for_array_map_tuple(seeded_test_db, page: Page, shot) -> None:
    """Array/Map/Tuple columns get a built-in default view with no cell_view
    authored: a plain vertical list, collapsed to the first 3 items with an
    expander. Types come from an auto-DESCRIBE fired alongside the query, so a
    named tuple renders `name: value` and Array(Tuple)/Array(Map) render each
    element by its inner view."""
    _open_query_panel(page)

    page.get_by_test_id("query-input").fill(
        "SELECT "
        "['apple','banana','cherry','date','elderberry'] AS arr, "
        "map('x',1,'y',2) AS m, "
        "CAST((1,'alpha'), 'Tuple(id Int32, name String)') AS tup, "
        "CAST([(1,'a'),(2,'b'),(3,'c'),(4,'d')], "
        "'Array(Tuple(id Int32, name String))') AS arr_tup"
    )
    page.get_by_test_id("query-run").click()
    output = page.get_by_test_id("query-output")
    expect(output).to_be_visible()

    # Array(String): collapsed shows the first 3 elements, hides the rest behind
    # an expander.
    arr = output.get_by_test_id("cell-arr")
    expect(arr).to_contain_text("apple")
    expect(arr).to_contain_text("cherry")
    expect(arr).not_to_contain_text("elderberry")
    shot("default views: array/map/tuple collapsed")

    # Map: one `key → value` line per entry.
    expect(output.get_by_test_id("cell-m")).to_contain_text("x → 1")

    # Named tuple: `name: value` lines from the type (no collapse — 2 fields).
    tup = output.get_by_test_id("cell-tup")
    expect(tup).to_contain_text("id: 1")
    expect(tup).to_contain_text("name: alpha")

    # Array(Tuple): each element rendered as its tuple view; collapsed to 3.
    arr_tup = output.get_by_test_id("cell-arr_tup")
    expect(arr_tup).to_contain_text("id: 1")
    expect(arr_tup).to_contain_text("name: c")
    expect(arr_tup).not_to_contain_text("name: d")

    # Expanding the array reveals the hidden elements and a collapse control.
    page.get_by_test_id("cell-arr-toggle").click()
    expect(arr).to_contain_text("elderberry")
    expect(page.get_by_test_id("cell-arr-toggle")).to_contain_text("collapse")
    shot("default views: array expanded")


def test_field_pickers_visibility_and_order_by(seeded_test_db, page: Page, shot) -> None:
    _open_query_panel(page)
    page.get_by_test_id("query-input").fill("SELECT id, name FROM items")

    # Fields describes the query's output columns and reveals both pickers.
    page.get_by_test_id("query-fields").click()
    expect(page.get_by_test_id("field-pickers")).to_be_visible()
    expect(page.locator('[data-testid="field-toggle"]')).to_have_count(2)
    expect(page.locator('[data-testid="field-toggle"][data-col="id"]')).to_be_visible()
    expect(page.locator('[data-testid="field-toggle"][data-col="name"]')).to_be_visible()
    shot("fields described - both pickers")

    # Execute renders both columns.
    page.get_by_test_id("query-run").click()
    output = page.get_by_test_id("query-output")
    expect(output).to_be_visible()
    expect(output.locator("table thead th")).to_have_count(2)
    shot("results with all columns")

    # Select fields is client-side: hiding `id` drops its column without re-running,
    # and the toggle immediately reflects the unselected state.
    id_toggle = page.locator('[data-testid="field-toggle"][data-col="id"]')
    id_toggle.click()
    expect(output.locator("table thead th")).to_have_count(1)
    expect(output.locator("table thead th")).to_contain_text("name")
    expect(id_toggle).to_have_attribute("data-on", "false")
    shot("id column hidden (client-side)")

    # Clear all hides every column; Select all restores them.
    page.get_by_test_id("fields-clear").click()
    expect(output.locator("table thead th")).to_have_count(0)
    shot("clear all - no columns")
    page.get_by_test_id("fields-select-all").click()
    expect(output.locator("table thead th")).to_have_count(2)
    shot("select all - columns restored")

    # CSV exports all columns regardless of visibility: hide `id`, it's still in the CSV.
    page.locator('[data-testid="field-toggle"][data-col="id"]').click()
    expect(output.locator("table thead th")).to_have_count(1)
    with page.expect_download() as dl_info:
        page.get_by_test_id("query-csv").click()
    header = open(dl_info.value.path(), encoding="utf-8").read().splitlines()[0]
    assert "id" in header
    assert "name" in header

    # Order by name DESC (server-side): selecting it does NOT change results until
    # the query re-runs. The order-by Run button re-runs the query (like Execute),
    # so it also applies the current limit.
    page.locator('[data-testid="orderby-add"][data-col="name"]').click()
    chip = page.locator('[data-testid="orderby-chip"][data-col="name"]')
    expect(chip).to_be_visible()
    chip.get_by_test_id("orderby-dir").click()  # ASC -> DESC
    expect(chip.get_by_test_id("orderby-dir")).to_have_text("DESC")
    shot("order by name DESC selected")
    page.get_by_test_id("query-limit").fill("2")
    page.get_by_test_id("orderby-run").click()
    expect(output).to_contain_text("gamma")
    expect(output).to_contain_text("beta")
    expect(output).not_to_contain_text("alpha")
    shot("ordered + limited results (order-by Run)")


def _author_params_yaml(page: Page, name: str, sql: str, params_yaml: str) -> None:
    """Fill the SQL, name the query, and author a `params:` block via the
    cell-view modal, then Save. Shared by the query-param tests below."""
    page.get_by_test_id("query-input").fill(sql)
    page.once("dialog", lambda d: d.accept(name))
    page.get_by_test_id("query-predefined-select").select_option("::new::")
    page.get_by_test_id("cell-view-toggle").click()
    expect(page.get_by_test_id("cell-view-modal")).to_be_visible()
    page.get_by_test_id("cell-view-input").fill(params_yaml)
    page.get_by_test_id("cell-view-save").click()
    expect(page.get_by_test_id("cell-view-modal")).not_to_be_visible()


def test_query_param_dropdown_substitutes_value(seeded_test_db, page: Page, shot) -> None:
    """A `params:` block in the cell_view YAML renders a dropdown per param; the
    selected value is substituted into the SQL via {name} (auto-quoted as a
    string) and the query re-runs immediately on change."""
    _open_query_panel(page)
    _author_params_yaml(
        page,
        "by-name",
        "SELECT name FROM items WHERE name = {sel} ORDER BY id",
        "params:\n  - name: sel\n    options: [alpha, beta, gamma]\n",
    )

    # The dropdown renders with the declared options; default is the first one.
    sel = page.locator('[data-testid="param-select"][data-param="sel"]')
    expect(sel).to_be_visible()
    expect(sel.locator("option")).to_have_count(3)
    shot("params dropdown rendered")

    # Selecting a value auto-re-runs the query; substitution is quoted correctly
    # (an unquoted value would be a ClickHouse error, not a filtered result).
    sel.select_option("beta")
    output = page.get_by_test_id("query-output")
    expect(output).to_be_visible()
    expect(output).to_contain_text("beta")
    expect(output).not_to_contain_text("alpha")
    expect(output).not_to_contain_text("gamma")
    shot("query re-run with sel=beta")

    # Switching the value re-runs again with the new substitution.
    sel.select_option("gamma")
    expect(output).to_contain_text("gamma")
    expect(output).not_to_contain_text("beta")
    shot("query re-run with sel=gamma")


def test_query_param_options_sql_populates_dropdown(seeded_test_db, page: Page, shot) -> None:
    """`options_sql` resolves the dropdown choices from a query: the first column
    of every row becomes an option, in the query's own order. The first row is
    the default; substituting it and running returns that row, and switching the
    selection re-runs with the new value."""
    _open_query_panel(page)
    _author_params_yaml(
        page,
        "by-options-sql",
        "SELECT name FROM items WHERE name = {sel} ORDER BY id",
        "params:\n  - name: sel\n    options_sql: SELECT DISTINCT name FROM items ORDER BY name\n",
    )

    # The dropdown is populated from the query result: alpha, beta, gamma.
    sel = page.locator('[data-testid="param-select"][data-param="sel"]')
    expect(sel).to_be_visible()
    expect(sel.locator("option")).to_have_count(3)
    expect(sel.locator("option").first).to_have_text("alpha")
    shot("options_sql dropdown populated")

    # Default is the first option (alpha); running substitutes and returns it.
    page.get_by_test_id("query-run").click()
    output = page.get_by_test_id("query-output")
    expect(output).to_be_visible()
    expect(output).to_contain_text("alpha")
    expect(output).not_to_contain_text("beta")
    shot("options_sql default (alpha) run")

    # Switching re-runs with the new substitution.
    sel.select_option("gamma")
    expect(output).to_contain_text("gamma")
    expect(output).not_to_contain_text("alpha")
    shot("options_sql re-run with sel=gamma")


def test_query_param_options_and_options_sql_are_mutually_exclusive(seeded_test_db, page: Page, shot) -> None:
    """A param declaring both `options` and `options_sql` is a config error:
    server-side cell_view validation rejects the save, so the modal stays open
    and no dropdown ever renders."""
    _open_query_panel(page)
    page.get_by_test_id("query-input").fill("SELECT name FROM items WHERE name = {sel} ORDER BY id")
    page.once("dialog", lambda d: d.accept("both-keys"))
    page.get_by_test_id("query-predefined-select").select_option("::new::")
    page.get_by_test_id("cell-view-toggle").click()
    expect(page.get_by_test_id("cell-view-modal")).to_be_visible()
    page.get_by_test_id("cell-view-input").fill(
        "params:\n  - name: sel\n    options: [alpha, beta]\n    options_sql: SELECT name FROM items\n"
    )
    page.get_by_test_id("cell-view-save").click()
    # Rejected: the modal stays open (a clean persist is what closes it).
    expect(page.get_by_test_id("cell-view-modal")).to_be_visible()
    shot("both options + options_sql -> save rejected")
    page.get_by_test_id("cell-view-cancel").click()
    expect(page.get_by_test_id("query-error")).to_contain_text("invalid cell_view")
    expect(page.locator('[data-testid="param-select"][data-param="sel"]')).to_have_count(0)


def test_query_param_options_sql_no_rows_blocks_run(seeded_test_db, page: Page, shot) -> None:
    """An `options_sql` that returns zero rows has nothing to choose from: the
    main query is blocked (Execute disabled) and the error banner names the
    param and the empty result."""
    _open_query_panel(page)
    _author_params_yaml(
        page,
        "empty-options",
        "SELECT name FROM items WHERE name = {sel}",
        "params:\n  - name: sel\n    options_sql: SELECT name FROM items WHERE 1 = 0\n",
    )
    error = page.get_by_test_id("query-error")
    expect(error).to_be_visible()
    expect(error).to_contain_text('options for "sel"')
    expect(error).to_contain_text("no rows")
    expect(page.get_by_test_id("query-run")).to_be_disabled()
    shot("options_sql empty -> blocked")


def test_query_param_options_sql_error_blocks_run(seeded_test_db, page: Page, shot) -> None:
    """An `options_sql` that errors blocks the main query (Execute disabled) and
    surfaces the failure through the banner, prefixed with the param name."""
    _open_query_panel(page)
    _author_params_yaml(
        page,
        "bad-options",
        "SELECT name FROM items WHERE name = {sel}",
        "params:\n  - name: sel\n    options_sql: SELECT name FROM no_such_table\n",
    )
    error = page.get_by_test_id("query-error")
    expect(error).to_be_visible()
    expect(error).to_contain_text('options for "sel"')
    expect(page.get_by_test_id("query-run")).to_be_disabled()
    shot("options_sql error -> blocked")
