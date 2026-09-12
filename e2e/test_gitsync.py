"""Git-sync e2e. In CI a loopback git daemon (start-git-daemon action) serves a
remote that conftest points the default workspace at, so the full UI
commit/restore round trip runs; on an unconfigured stack that test skips and we
assert the controls render disabled."""

import httpx
import pytest
from playwright.sync_api import Page, expect


def _configured(base_url: str) -> bool:
    return bool(httpx.get(f"{base_url}/api/git/status").json().get("configured"))


def test_controls_disabled_when_unconfigured(page: Page, base_url: str):
    if _configured(base_url):
        pytest.skip("git sync is configured; disabled-state not applicable")
    page.goto(f"{base_url}/dashboard")
    expect(page.get_by_test_id("git-commit")).to_be_visible()
    expect(page.get_by_test_id("git-commit")).to_be_disabled()
    expect(page.get_by_test_id("git-restore-toggle")).to_be_visible()
    expect(page.get_by_test_id("git-restore-toggle")).to_be_disabled()


def test_commit_and_restore_dashboard_round_trip(page: Page, base_url: str):
    if not _configured(base_url):
        pytest.skip("git sync is not configured for this stack")

    # Seed v1 via the API, then commit it from the UI.
    httpx.post(
        f"{base_url}/api/dashboards",
        json={
            "name": "gs e2e",
            "connection": "prod",
            "html": "<html><body>v1</body></html>",
            "queries": {"q": "SELECT 1"},
        },
    ).raise_for_status()
    page.goto(f"{base_url}/dashboard?name=gs%20e2e")
    expect(page.get_by_test_id("git-commit")).to_be_enabled()
    page.get_by_test_id("git-commit").click()
    expect(page.get_by_test_id("git-commit")).to_have_text("Committed")

    # Drift the local copy to v2, then restore v1 from the revision list.
    httpx.post(
        f"{base_url}/api/dashboards",
        json={
            "name": "gs e2e",
            "connection": "prod",
            "html": "<html><body>v2</body></html>",
            "queries": {"q": "SELECT 2"},
        },
    ).raise_for_status()
    page.on("dialog", lambda d: d.accept())
    page.get_by_test_id("git-restore-toggle").click()
    rows = page.get_by_test_id("git-revision-row")
    expect(rows).to_have_count(1)
    rows.first.get_by_test_id("git-revision-restore").click()
    # The picker closes on a successful restore; only then check the store.
    expect(page.get_by_test_id("git-revisions")).to_be_hidden()
    d = httpx.get(f"{base_url}/api/dashboards/gs%20e2e").json()
    assert "v1" in d["html"]
    assert d["queries"] == {"q": "SELECT 1"}
