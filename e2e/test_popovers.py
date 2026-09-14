"""Popover dismissal: the header dropdowns and the prompt's suggestion list
close when the click (or Escape) lands outside them, not only on their own
trigger. Runs without a database — neither popover needs a connection."""

from playwright.sync_api import Page, expect


def test_popovers_close_on_outside_click_and_escape(page: Page) -> None:
    page.goto("/queries", wait_until="networkidle")
    switcher = page.get_by_test_id("workspace-switcher")
    option = page.get_by_test_id("workspace-option").first
    heading = page.locator("h1")  # outside every popover

    # Workspace dropdown: a click elsewhere on the page closes it.
    switcher.click()
    expect(option).to_be_visible()
    heading.click()
    expect(option).to_have_count(0)

    # ...and so does Escape.
    switcher.click()
    expect(option).to_be_visible()
    page.keyboard.press("Escape")
    expect(option).to_have_count(0)

    # The manage panel is the exception: it holds unsaved form input, so an
    # outside click and Escape both leave it alone; its own Close dismisses it.
    switcher.click()
    page.get_by_test_id("workspace-manage").click()
    name_input = page.get_by_test_id("workspace-name-input")
    expect(name_input).to_be_visible()
    heading.click()
    page.keyboard.press("Escape")
    expect(name_input).to_be_visible()
    page.get_by_role("button", name="Close").click()
    expect(name_input).to_have_count(0)

    # The prompt's suggestion list dismisses the same two ways.
    prompt = page.get_by_test_id("prompt-input")
    suggestions = page.get_by_test_id("prompt-suggestions")
    prompt.fill("new")
    expect(suggestions).to_be_visible()
    heading.click()
    expect(suggestions).to_have_count(0)

    prompt.fill("ne")  # a fresh value: re-typing the same one fires no change
    expect(suggestions).to_be_visible()
    page.keyboard.press("Escape")
    expect(suggestions).to_have_count(0)
