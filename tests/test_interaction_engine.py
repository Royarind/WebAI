from pathlib import Path

from playwright.sync_api import sync_playwright

from webai.interaction_engine import InteractionEngine


def test_custom_dropdown_recovers_from_wrong_accessible_role_and_verifies_selection():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
          <button id="trip" aria-label="Round trip">Round trip</button>
          <div id="menu"></div>
        """)
        page.locator("#trip").evaluate("""el => {
          el.addEventListener('click', () => {
            const menu = document.querySelector('#menu');
            if (menu.children.length) return;
            const option = document.createElement('div');
            option.setAttribute('role', 'option');
            option.setAttribute('aria-selected', 'false');
            option.textContent = 'One way';
            option.addEventListener('click', () => {
              option.setAttribute('aria-selected', 'true');
              el.textContent = 'One way';
              el.setAttribute('aria-label', 'One way');
              menu.setAttribute('data-selected', 'One way');
            });
            menu.appendChild(option);
          });
        }""")
        result = InteractionEngine(page).perform(
            "control", by="role", value="combobox", name="Round trip",
            operation="choose", target="One way"
        )
        assert result["ok"] is True
        assert result["verified"] is True
        assert page.get_by_role("button", name="One way", exact=True).count() == 1
        assert page.get_by_role("option", name="One way", exact=True).get_attribute("aria-selected") == "true"
        browser.close()


def test_inventory_includes_custom_controls_and_selected_state():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
          <div role="combobox" aria-label="Trip type" aria-expanded="false" tabindex="0">Round trip</div>
          <div role="switch" aria-label="Direct flights" aria-checked="true" tabindex="0" style="width:120px;height:32px"></div>
          <div role="option" aria-label="One way" aria-selected="true">One way</div>
        """)
        result = InteractionEngine(page).observe()
        by_name = {item.get("name"): item for item in result["controls"]}
        assert "Trip type" in by_name
        assert by_name["Trip type"]["role"] == "combobox"
        assert by_name["Direct flights"]["ariaChecked"] == "true"
        assert by_name["One way"]["ariaSelected"] == "true"
        browser.close()


def test_keyboard_hover_and_wait_for_are_supported():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
          <button id="target" aria-label="Target" onclick="this.textContent='Activated'">Target</button>
          <div id="late" hidden>Loaded</div>
          <script>setTimeout(() => document.querySelector('#late').hidden=false, 100)</script>
        """)
        engine = InteractionEngine(page)
        hover = engine.perform("hover", by="role", value="button", name="Target")
        assert hover["ok"] is True
        press = engine.perform("press", by="role", value="button", name="Target", key="Enter")
        assert press["ok"] is True
        assert page.locator("#target").inner_text() == "Activated"
        waited = engine.perform("wait_for", by="css", value="#late", operation="visible")
        assert waited["verified"] is True
        browser.close()


def test_drag_drop_reports_unverified_if_the_source_did_not_move():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
          <div id="source" draggable="true">Card</div>
          <div id="target">Column</div>
        """)
        result = InteractionEngine(page).perform(
            "drag_drop", by="css", value="#source",
            target_by="css", target_value="#target"
        )
        assert result["ok"] is True
        assert result["verified"] is False
        browser.close()


def test_upload_sets_file_and_verifies_filename(tmp_path: Path):
    file_path = tmp_path / "sample.txt"
    file_path.write_text("upload fixture", encoding="utf-8")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content('<label for="upload">Choose file</label><input id="upload" type="file">')
        result = InteractionEngine(page).perform(
            "upload", by="label", value="Choose file", path=str(file_path)
        )
        assert result["verified"] is True
        assert result["files"] == ["sample.txt"]
        browser.close()


def test_download_saves_file_and_reports_path(tmp_path: Path):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
          <a id="download" href="data:text/plain,webai-download" download="report.txt">Download report</a>
        """)
        destination = tmp_path / "saved" / "report.txt"
        result = InteractionEngine(page).perform(
            "download", by="role", value="link", name="Download report", path=str(destination)
        )
        assert result["verified"] is True
        assert destination.read_text(encoding="utf-8") == "webai-download"
        browser.close()



def test_javascript_confirm_is_dismissed_by_default_and_reported():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
          <button id="delete" onclick="if(confirm('Confirm deletion?')) this.textContent='Deleted'; else this.textContent='Cancelled'">Delete</button>
        """)
        result = InteractionEngine(page).perform("click", by="css", value="#delete")
        assert result["ok"] is True
        assert result["dialog"]["type"] == "confirm"
        assert result["dialog"]["decision"] == "dismissed"
        assert page.locator("#delete").inner_text() == "Cancelled"
        browser.close()


def test_javascript_confirm_can_be_accepted_when_explicitly_authorized():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
          <button id="continue" onclick="if(confirm('Continue?')) this.textContent='Continued'">Continue</button>
        """)
        result = InteractionEngine(page).perform(
            "click", by="css", value="#continue", dialog_action="accept"
        )
        assert result["dialog"]["decision"] == "accepted"
        assert page.locator("#continue").inner_text() == "Continued"
        browser.close()



def test_custom_switch_and_contenteditable_are_verified():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
          <div id="switch" role="switch" aria-label="Direct flights" aria-checked="false" tabindex="0"
            onclick="this.setAttribute('aria-checked', this.getAttribute('aria-checked') === 'true' ? 'false' : 'true')">Off</div>
          <div id="editor" contenteditable="true" role="textbox" aria-label="Notes"></div>
        """)
        from webai.actions import check, fill
        checked = check(page, "role", "switch", "Direct flights", True)
        assert checked["verified"] is True
        assert page.locator("#switch").get_attribute("aria-checked") == "true"
        filled = fill(page, "role", "textbox", "Meeting notes", "Notes")
        assert filled["verified"] is True
        assert page.locator("#editor").inner_text() == "Meeting notes"
        browser.close()


def test_coordinate_click_is_bounded_to_viewport_and_dispatches_event():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 500, "height": 300})
        page.set_content("""
          <button id="go" style="position:absolute;left:100px;top:80px;width:120px;height:40px"
            onclick="document.querySelector('#result').textContent='clicked'">Run</button>
          <output id="result"></output>
        """)
        engine = InteractionEngine(page)
        result = engine.perform("click_at", x=140, y=100)
        assert result["ok"] is True
        assert page.locator("#result").inner_text() == "clicked"
        import pytest
        with pytest.raises(ValueError, match="outside the current viewport"):
            engine.perform("click_at", x=900, y=100)
        browser.close()


def test_nested_scroll_container_reports_changed_scroll_position():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
          <div id="panel" style="height:100px;overflow:auto">
            <div style="height:700px">Scrollable content</div>
          </div>
        """)
        result = InteractionEngine(page).perform(
            "scroll", value="down", text=250, target_by="css", target_value="#panel"
        )
        assert result["verified"] is True
        assert result["after"]["top"] > result["before"]["top"]
        browser.close()
