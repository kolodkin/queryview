"""Popover dismissal: the header dropdowns close when the click (or Escape)
lands outside them, not only on their own trigger. Runs without a database —
no popover here needs a connection."""

from playwright.sync_api import Page, expect


def test_popovers_close_on_outside_click_and_escape(page: Page) -> None:
    page.goto("/connect", wait_until="networkidle")
    switcher = page.get_by_test_id("workspace-switcher")
    option = page.get_by_test_id("workspace-option").first

    def click_outside() -> None:
        # The page's empty left edge: the header popovers open on the right.
        page.mouse.click(5, 400)

    # Workspace dropdown: a click elsewhere on the page closes it.
    switcher.click()
    expect(option).to_be_visible()
    click_outside()
    expect(option).to_have_count(0)

    # ...and so does Escape.
    switcher.click()
    expect(option).to_be_visible()
    page.keyboard.press("Escape")
    expect(option).to_have_count(0)

    # The manage panel dismisses the same way while untouched...
    switcher.click()
    page.get_by_test_id("workspace-manage").click()
    name_input = page.get_by_test_id("workspace-name-input")
    expect(name_input).to_be_visible()
    click_outside()
    expect(name_input).to_have_count(0)

    # ...but once it holds unsaved input, an outside click and Escape both
    # leave it alone; its own Close dismisses it.
    switcher.click()
    page.get_by_test_id("workspace-manage").click()
    page.get_by_test_id("workspace-branch-input").fill("draft")
    click_outside()
    page.keyboard.press("Escape")
    expect(name_input).to_be_visible()
    page.get_by_role("button", name="Close").click()
    expect(name_input).to_have_count(0)
