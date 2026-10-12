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
            '<div><section><div role="option" tabindex="0" aria-label="Target action" '
            'onclick="this.textContent=\'Action completed\'">Run</div></section></div>'
        )
        result = click(page, "css", "#outdated-selector", "Target action")
        assert result["ok"] is True
        assert result["healed"]["to"]["strategy"] == "sync_dom_intelligence"
        assert page.get_by_role("option", name="Target action").inner_text() == "Action completed"
        browser.close()


def test_dom_intelligence_rejects_ambiguous_candidates():
    from webai.sync_dom_intelligence import SyncDOMIntelligence

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(
            '<div role="option" tabindex="0" aria-label="Target action">First</div>'
            '<button aria-label="Target action">Second</button>'
        )
        import pytest
        with pytest.raises(ValueError, match="ambiguous"):
            SyncDOMIntelligence(page).resolve("Target action")
        browser.close()

def test_click_hidden_radio_uses_associated_label_and_verifies_state():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
            <style>
              .choice { display:inline-block; position:relative; width:140px; height:48px; }
              .choice input { position:absolute; width:1px; height:1px; opacity:0.01; }
              .choice label { display:block; padding:14px; border:1px solid #aaa; cursor:pointer; }
              .choice input:checked + label { border:2px solid green; }
            </style>
            <div class="choice"><input id="regular" type="radio" name="fit" value="regular" checked><label for="regular">Regular</label></div>
            <div class="choice"><input id="petite" type="radio" name="fit" value="petite"><label for="petite">Petite</label></div>
        """)
        result = click(page, "css", "#petite", "Petite fit")
        assert result["ok"] is True
        assert result["verified"] is True
        assert page.locator("#petite").is_checked()
        assert not page.locator("#regular").is_checked()
        browser.close()


def test_click_already_selected_radio_does_not_click_again():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content('<label for="fit">Petite</label><input id="fit" type="radio" checked>')
        result = click(page, "css", "#fit", "Petite fit")
        assert result["ok"] is True
        assert result["already_selected"] is True
        assert page.locator("#fit").is_checked()
        browser.close()



def test_locator_is_ambiguous_when_same_named_control_exists_in_page_and_iframe():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
          <button aria-label="Continue">Continue</button>
          <iframe srcdoc="<button aria-label='Continue'>Continue</button>"></iframe>
        """)
        import pytest
        with pytest.raises(ValueError, match="ambiguous across the main page and frames"):
            click(page, "role", "button", "Continue")
        browser.close()
