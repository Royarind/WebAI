from playwright.sync_api import sync_playwright
from webai.actions import operate_control


def test_range_slider_uses_mouse_and_verifies_value():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content('<label for="price">Maximum price</label><input id="price" type="range" min="0" max="100" step="10" value="20">')
        result = operate_control(page, "css", "#price", "set_value", 70, name="Maximum price")
        assert result["verified"] is True
        assert page.locator("#price").input_value() == "70"
        browser.close()


def test_native_dropdown_selects_and_verifies_label():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content('<label for="size">Size</label><select id="size"><option value="s">Small</option><option value="m">Medium</option></select>')
        result = operate_control(page, "label", "Size", "choose", "Medium")
        assert result["verified"] is True
        assert page.locator("#size").input_value() == "m"
        browser.close()


def test_quantity_plus_button_changes_input_value():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
          <div id="quantity">
            <button aria-label="Decrease quantity" onclick="q.value=Math.max(1, Number(q.value)-1)">−</button>
            <input id="q" type="number" min="1" max="10" step="1" value="2">
            <button aria-label="Increase quantity" onclick="q.value=Math.min(10, Number(q.value)+1)">+</button>
          </div>
        """)
        result = operate_control(page, "css", "#q", "increment", steps=2)
        assert result["verified"] is True
        assert page.locator("#q").input_value() == "4"
        browser.close()



def test_native_select_accepts_option_value_and_multi_select():
    from webai.actions import select_option

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
          <select id="size"><option value="s">Small</option><option value="m">Medium</option></select>
          <select id="colors" multiple>
            <option value="red">Red</option><option value="blue">Blue</option><option value="green">Green</option>
          </select>
        """)
        one = select_option(page, "css", "#size", "m")
        assert one["verified"] is True
        assert page.locator("#size").input_value() == "m"
        many = select_option(page, "css", "#colors", ["red", "blue"])
        assert many["verified"] is True
        assert page.locator("#colors").locator("option:checked").count() == 2
        browser.close()



def test_custom_dropdown_waits_for_delayed_options():
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content("""
          <button id="trip" aria-label="Round trip">Round trip</button>
          <div id="menu"></div>
        """)
        page.locator("#trip").evaluate("""el => {
          el.addEventListener('click', () => {
            setTimeout(() => {
              const option = document.createElement('div');
              option.setAttribute('role', 'option');
              option.setAttribute('aria-selected', 'false');
              option.textContent = 'One way';
              option.onclick = () => {
                option.setAttribute('aria-selected', 'true');
                el.setAttribute('aria-label', 'One way');
                el.textContent = 'One way';
              };
              document.querySelector('#menu').replaceChildren(option);
            }, 180);
          });
        }""")
        result = operate_control(page, "role", "combobox", "choose", "One way", name="Round trip")
        assert result["verified"] is True
        assert page.get_by_role("option", name="One way").get_attribute("aria-selected") == "true"
        browser.close()
