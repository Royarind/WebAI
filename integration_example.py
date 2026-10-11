"""Illustrative integration into an existing async Playwright action layer."""
from playwright.async_api import Page
from webai_dom_intelligence import DOMIntelligence


async def select_colour(page: Page, colour: str) -> dict:
    engine = DOMIntelligence(page, max_candidates=100, max_attempts=5)

    # Site-specific validation should be more exact than "any selected element".
    async def validate_colour():
        # Inspect accessible labels, ARIA state, title, and class state.
        candidates = page.locator(
            '[aria-checked="true"], [aria-pressed="true"], [aria-selected="true"], '
            'input:checked, .selected, .is-selected, [data-selected="true"]'
        )
        count = await candidates.count()
        for i in range(min(count, 30)):
            el = candidates.nth(i)
            try:
                evidence = " ".join(filter(None, [
                    await el.get_attribute("aria-label"),
                    await el.get_attribute("title"),
                    await el.inner_text(),
                    await el.get_attribute("data-colour"),
                    await el.get_attribute("data-color"),
                    await el.get_attribute("class"),
                ])).lower()
                if colour.lower() in evidence:
                    return True
            except Exception:
                continue
        # Do not claim success unless page exposes evidence of the requested colour.
        return False

    return await engine.click_intent(
        f"select {colour} colour swatch",
        authorized=True,
        validate=validate_colour,
    )
