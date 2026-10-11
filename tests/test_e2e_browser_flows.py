"""Integration-style tests for complete local browser action/verification flows."""
from playwright.sync_api import sync_playwright

from webai.actions import click
from webai.task_verifiers import verify_task_outcome


def test_stale_selector_recovers_then_selected_option_is_verified():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
            <main>
              <div role="option" tabindex="0" aria-label="Citrine Forest Green"
                   aria-pressed="false"
                   onclick="this.setAttribute('aria-pressed', 'true')">
                Citrine Forest Green
              </div>
            </main>
        """)

        result = click(page, "css", "#old-colour-selector", "Citrine Forest Green")
        assert result["ok"] is True
        assert result["healed"]["to"]["strategy"] == "sync_dom_intelligence"

        verification = verify_task_outcome(page, "selected_option", "Citrine Forest Green")
        assert verification["verified"] is True
        browser.close()


def test_delayed_cart_drawer_is_verified_without_repeating_add_action():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
            <main>
              <h1>Everyday Wide-Leg Pant</h1>
              <button id="add" onclick="
                document.querySelector('#add').disabled = true;
                setTimeout(() => {
                  document.querySelector('#bag').innerHTML =
                    '<p>Everyday Wide-Leg Pant</p><p>Quantity: 1</p>';
                  document.querySelector('#bag').setAttribute('data-ready', 'true');
                }, 250);
              ">Add to Bag</button>
              <aside id="bag" data-testid="shopping-bag" aria-label="Shopping bag"></aside>
            </main>
        """)

        clicked = click(page, "role", "button", "Add to Bag")
        assert clicked["ok"] is True
        assert page.locator("#add").is_disabled()

        verification = verify_task_outcome(
            page,
            "cart_contains",
            "Everyday Wide-Leg Pant",
            timeout_ms=1000,
            interval_ms=50,
        )
        assert verification["verified"] is True
        assert verification["polling"]["verified_after_polling"] is True
        # This test invokes the Add to Bag click once; polling only observes state.
        assert page.locator("#bag").get_attribute("data-ready") == "true"
        browser.close()


def test_delayed_confirmation_text_is_verified_after_render():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
            <main>
              <p id="status">Saving...</p>
              <script>
                setTimeout(() => {
                  document.querySelector('#status').textContent = 'Profile updated successfully';
                }, 150);
              </script>
            </main>
        """)
        result = verify_task_outcome(
            page, "text_present", "Profile updated successfully",
            timeout_ms=800, interval_ms=40,
        )
        assert result["verified"] is True
        browser.close()
