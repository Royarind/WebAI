from playwright.sync_api import sync_playwright

from webai.locators import overlay_inventory


def test_overlay_inventory_classifies_cookie_consent_and_exposes_controls():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
            <div role="dialog" aria-modal="true" class="cookie-modal">
              <h2>Cookie preferences</h2>
              <p>We use cookies to improve your experience.</p>
              <button>Reject optional cookies</button>
              <button aria-label="Close cookie preferences">×</button>
            </div>
        """)
        overlays = overlay_inventory(page)
        assert len(overlays) == 1
        assert overlays[0]["category"] == "cookie_consent"
        assert any("Reject optional cookies" in b["text"] for b in overlays[0]["buttons"])
        assert any(b["ariaLabel"] == "Close cookie preferences" for b in overlays[0]["buttons"])
        browser.close()


def test_overlay_inventory_preserves_task_relevant_bag_modal_classification():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
            <div role="dialog" aria-modal="true" data-testid="shopping-bag-modal">
              <h2>View Bag</h2>
              <p>Everyday Wide-Leg Pant</p>
              <button>Continue Shopping</button>
            </div>
        """)
        overlays = overlay_inventory(page)
        assert len(overlays) == 1
        assert overlays[0]["category"] == "task_flow"
        assert "Everyday Wide-Leg Pant" in overlays[0]["text"]
        browser.close()


def test_overlay_inventory_ignores_hidden_modal():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
            <div role="dialog" style="display:none"><button>Close</button></div>
        """)
        assert overlay_inventory(page) == []
        browser.close()
