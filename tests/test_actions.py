import pytest
from pathlib import Path
from playwright.sync_api import sync_playwright
from webai.actions import click, fill, check
HTML = Path(__file__).parent / "site" / "index.html"

def test_fill_click_and_check():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(HTML.as_uri())
        fill(page, "label", "Email", "qa@example.com")
        assert page.locator("#email").input_value() == "qa@example.com"
        click(page, "role", "button", "Click me")
        assert page.locator("#result").inner_text() == "Clicked successfully"
        check(page, "css", "#agree")
        assert page.locator("#agree").is_checked()
        browser.close()

def test_action_verification_and_frame_locator():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content('<iframe srcdoc="<label for=\'q\'>Frame query</label><input id=\'q\'>"></iframe>')
        from webai.actions import fill
        result = fill(page, "label", "Frame query", "found")
        assert result["ok"] and result["verified"]
        assert page.frames[1].locator("#q").input_value() == "found"
        browser.close()


@pytest.mark.asyncio
async def test_click_with_dom_intelligence():
    from playwright.async_api import async_playwright
    from webai.actions import click_with_dom_intelligence

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(
            '<button aria-label="Confirm Action" onclick="this.textContent=\'Confirmed\'">Click Me</button>'
        )
        async def is_confirmed():
            return await page.locator("button").inner_text() == "Confirmed"

        res = await click_with_dom_intelligence(
            page,
            intent="Confirm Action",
            authorized=True,
            validate=is_confirmed,
        )
        assert res["status"] == "success"
        await browser.close()


def test_click_uses_dom_intelligence_when_original_locator_is_missing():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(
            '<div><section><button aria-label="Target action" '
            'onclick="this.textContent=\'Action completed\'">Run</button></section></div>'
        )
        result = click(page, "css", "#outdated-selector", "Target action")
        assert result["ok"] is True
        assert result["healed"]["to"]["strategy"] == "sync_dom_intelligence"
        assert page.get_by_role("button", name="Target action").inner_text() == "Action completed"
        browser.close()


def test_dom_intelligence_rejects_ambiguous_candidates():
    from webai.sync_dom_intelligence import SyncDOMIntelligence

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(
            '<button aria-label="Target action">First</button>'
            '<button aria-label="Target action">Second</button>'
        )
        import pytest
        with pytest.raises(ValueError, match="ambiguous"):
            SyncDOMIntelligence(page).resolve("Target action")
        browser.close()
