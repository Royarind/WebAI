from pathlib import Path
from playwright.sync_api import sync_playwright
from webai.locators import make_locator, inventory
HTML = Path(__file__).parent / "site" / "index.html"

def test_role_locator_and_inventory():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(HTML.as_uri())
        assert make_locator(page, "role", "button", "Click me").count() == 1
        assert any(x["name"] == "Click me" for x in inventory(page))
        browser.close()

def test_xpath_locator():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(HTML.as_uri())
        assert make_locator(page, "xpath", "//input[@id='email']").count() == 1
        browser.close()

def test_inventory_finds_open_shadow_dom_and_iframe(tmp_path):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content('''<!doctype html><body>
          <button>Outside</button>
          <x-widget></x-widget>
          <iframe srcdoc="<button>Inside frame</button>"></iframe>
          <script>
            customElements.define('x-widget', class extends HTMLElement {
              constructor() { super(); const root=this.attachShadow({mode:'open'}); root.innerHTML='<button>Shadow action</button>'; }
            });
          </script>
        </body>''')
        from webai.locators import inventory
        items = inventory(page, limit=30)
        names = [x.get("name") for x in items]
        assert "Outside" in names
        assert "Shadow action" in names
        assert "Inside frame" in names
        browser.close()
