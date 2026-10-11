import pytest
from playwright.async_api import async_playwright
try:
    from webai.webai_dom_intelligence import DOMIntelligence
except ImportError:
    from webai_dom_intelligence import DOMIntelligence


@pytest.mark.asyncio
async def test_inspects_and_clicks_button(tmp_path):
    html = """
    <html><body>
      <div><section><button aria-label="Choose Citrine Forest Green"
        data-testid="citrine-green" aria-pressed="false"
        onclick="this.setAttribute('aria-pressed','true')">Green swatch</button></section></div>
    </body></html>
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content(html)
        engine = DOMIntelligence(page)
        candidates = await engine.inspect("select Citrine Forest Green colour")
        assert candidates
        async def is_selected():
            return await page.get_by_test_id("citrine-green").get_attribute("aria-pressed") == "true"

        result = await engine.click_intent(
            "select Citrine Forest Green colour",
            authorized=True,
            validate=is_selected,
        )
        assert result["status"] == "success"
        await browser.close()


@pytest.mark.asyncio
async def test_blocks_consequential_without_permission():
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page()
        await page.set_content("<button>Add to Bag</button>")
        result = await DOMIntelligence(page).click_intent(
            "click Add to Bag", authorized=True
        )
        assert result["status"] == "blocked"
        await browser.close()
