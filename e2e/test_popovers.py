"""Popover dismissal: header dropdowns and the prompt's suggestion list close
when the click (or Escape) lands outside them, not only on their own trigger."""

from playwright.sync_api import Page, expect


def test_workspace_dropdown_closes_on_outside_click_and_escape(page: Page) -> None:
    page.goto("/queries", wait_until="networkidle")
    switcher = page.get_by_test_id("workspace-switcher")
    option = page.get_by_test_id("workspace-option").first

    # Clicking the page outside the dropdown closes it.
    switcher.click()
    expect(option).to_be_visible()
    page.locator("h1").click()
    expect(option).to_have_count(0)

    # Escape closes it too.
    switcher.click()
    expect(option).to_be_visible()
    page.keyboard.press("Escape")
    expect(option).to_have_count(0)


def test_prompt_suggestions_close_on_outside_click(page: Page) -> None:
    page.goto("/queries", wait_until="networkidle")
    page.get_by_test_id("prompt-input").fill("new")
    suggestions = page.get_by_test_id("prompt-suggestions")
    expect(suggestions).to_be_visible()

    page.locator("h1").click()
    expect(suggestions).to_have_count(0)
