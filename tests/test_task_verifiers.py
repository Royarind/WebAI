from playwright.sync_api import sync_playwright

from webai.task_verifiers import verify_task_outcome


def test_selected_option_verifier_checks_selected_state_not_unselected_text():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
            <button aria-pressed="false" aria-label="Citrine Forest Green">Green</button>
            <button aria-pressed="true" aria-label="Black">Black</button>
        """)
        result = verify_task_outcome(page, "selected_option", "Citrine Forest Green")
        assert result["verified"] is False
        result = verify_task_outcome(page, "selected_option", "Black")
        assert result["verified"] is True
        browser.close()


def test_cart_verifier_requires_target_in_cart_region():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
            <h1>Everyday Wide-Leg Pant</h1>
            <aside data-testid="shopping-bag">
                <p>Everyday Wide-Leg Pant</p>
                <p>Quantity: 1</p>
            </aside>
        """)
        result = verify_task_outcome(page, "cart_contains", "Everyday Wide-Leg Pant")
        assert result["verified"] is True
        result = verify_task_outcome(page, "cart_contains", "Different Product")
        assert result["verified"] is False
        browser.close()


def test_text_present_verifier_checks_rendered_text():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("<main><p>Profile updated successfully</p></main>")
        assert verify_task_outcome(page, "text_present", "Profile updated")["verified"] is True
        assert verify_task_outcome(page, "text_present", "Payment completed")["verified"] is False
        browser.close()


def test_unknown_verifier_fails_closed():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("<p>Some page</p>")
        result = verify_task_outcome(page, "model_says_ok", "Some page")
        assert result["verified"] is False
        browser.close()
