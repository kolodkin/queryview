"""YAML export/import e2e: download a dashboard as YAML from the UI, drift the
stored copy, then import the downloaded file back and verify it overwrote the
drift. Needs no external services — only the app itself."""

import httpx
from playwright.sync_api import Page, expect


def test_dashboard_export_import_round_trip(page: Page, base_url: str, tmp_path, shot):
    # Seed v1 via the API.
    httpx.post(
        f"{base_url}/api/dashboards",
        json={
            "name": "yio e2e",
            "html": "<html><body>v1</body></html>",
            "queries": {"q": "SELECT 1"},
        },
    ).raise_for_status()

    page.goto(f"{base_url}/dashboard?name=yio%20e2e")
    expect(page.get_by_test_id("yaml-export")).to_be_enabled()
    shot("dashboard with export-import controls")
    with page.expect_download() as dl_info:
        page.get_by_test_id("yaml-export").click()
    download = dl_info.value
    assert download.suggested_filename == "yio e2e.dashboard.yaml"
    saved = tmp_path / download.suggested_filename
    download.save_as(str(saved))
    text = saved.read_text(encoding="utf-8")
    assert "kind: dashboard" in text and "v1" in text

    # Drift the stored copy to v2, then import the downloaded v1 file back.
    httpx.post(
        f"{base_url}/api/dashboards",
        json={
            "name": "yio e2e",
            "html": "<html><body>v2</body></html>",
            "queries": {"q": "SELECT 2"},
        },
    ).raise_for_status()
    page.get_by_test_id("yaml-import-file").set_input_files(str(saved))
    expect(page.get_by_test_id("yaml-import")).to_have_text("Imported")
    shot("imported yaml overwrote the drifted copy")
    d = httpx.get(f"{base_url}/api/dashboards/yio%20e2e").json()
    assert "v1" in d["html"]
    assert d["queries"] == {"q": "SELECT 1"}
