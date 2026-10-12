from playwright.sync_api import sync_playwright
import pytest

from webai.interaction_engine import InteractionEngine


def test_set_date_native_input_verifies_iso_value():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content('<label for="birth">Birth date</label><input id="birth" type="date">')
        result = InteractionEngine(page).perform(
            "set_date", by="label", value="Birth date", target="2026-10-13"
        )
        assert result["verified"] is True
        assert page.locator("#birth").input_value() == "2026-10-13"
        browser.close()


def test_set_date_rejects_invalid_native_date_before_mutation():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content('<label for="birth">Birth date</label><input id="birth" type="date">')
        with pytest.raises(ValueError, match="Invalid value"):
            InteractionEngine(page).perform(
                "set_date", by="label", value="Birth date", target="13/10/2026"
            )
        assert page.locator("#birth").input_value() == ""
        browser.close()


def test_select_tab_verifies_selected_state_and_panel():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
          <div role="tablist">
            <button role="tab" id="overview-tab" aria-controls="overview" aria-selected="false"
              onclick="this.setAttribute('aria-selected','true'); document.querySelector('#overview').hidden=false">Overview</button>
          </div>
          <section id="overview" hidden>Overview content</section>
        """)
        result = InteractionEngine(page).perform(
            "select_tab", by="role", value="tab", name="Overview"
        )
        assert result["verified"] is True
        assert page.locator("#overview-tab").get_attribute("aria-selected") == "true"
        assert page.locator("#overview").is_visible()
        browser.close()


def test_expand_and_collapse_are_state_aware_not_blind_toggles():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
          <button id="details" aria-expanded="false"
            onclick="this.setAttribute('aria-expanded', this.getAttribute('aria-expanded') === 'true' ? 'false' : 'true')">Details</button>
        """)
        engine = InteractionEngine(page)
        expanded = engine.perform("expand", by="css", value="#details")
        assert expanded["verified"] is True
        assert page.locator("#details").get_attribute("aria-expanded") == "true"
        expanded_again = engine.perform("expand", by="css", value="#details")
        assert expanded_again["verified"] is True
        assert page.locator("#details").get_attribute("aria-expanded") == "true"
        collapsed = engine.perform("collapse", by="css", value="#details")
        assert collapsed["verified"] is True
        assert page.locator("#details").get_attribute("aria-expanded") == "false"
        browser.close()


def test_table_action_scopes_button_to_unique_row_and_verifies_change():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
          <table><tbody>
            <tr><td>Order 1001</td><td><button onclick="this.closest('tr').remove()">Cancel</button></td></tr>
            <tr><td>Order 1002</td><td><button onclick="this.closest('tr').remove()">Cancel</button></td></tr>
          </tbody></table>
        """)
        result = InteractionEngine(page).perform(
            "table_action", text="Order 1001", target_name="Cancel"
        )
        assert result["verified"] is True
        assert page.get_by_role("row").filter(has_text="Order 1001").count() == 0
        assert page.get_by_role("row").filter(has_text="Order 1002").count() == 1
        browser.close()


def test_validate_form_reports_invalid_fields_without_submitting():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
          <form id="profile"><label for="email">Email</label>
            <input id="email" name="email" type="email" required>
            <button type="submit">Save</button>
          </form>
        """)
        result = InteractionEngine(page).perform("validate_form", by="css", value="#profile")
        assert result["verified"] is True
        assert result["valid"] is False
        assert result["submitted"] is False
        assert any(field["name"] == "email" for field in result["invalid_fields"])
        assert page.url.endswith("about:blank")
        browser.close()


def test_validate_form_reports_valid_state():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
          <form id="profile"><label for="email">Email</label>
            <input id="email" name="email" type="email" required value="person@example.com">
          </form>
        """)
        result = InteractionEngine(page).perform("validate_form", by="css", value="#profile")
        assert result["valid"] is True
        assert result["invalid_fields"] == []
        browser.close()
