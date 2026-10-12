from __future__ import annotations

SUPPORTED = {"role", "label", "placeholder", "text", "test_id", "css", "xpath"}


def make_locator(page_or_frame, by: str, value: str, name: str | None = None):
    """Create a Playwright locator in a Page or Frame context."""
    by = by.lower().strip()
    if by not in SUPPORTED:
        raise ValueError(f"Unsupported locator strategy: {by}. Choose from {sorted(SUPPORTED)}")
    if by == "role":
        if not name:
            raise ValueError("For by='role', pass name= accessible name.")
        return page_or_frame.get_by_role(value, name=name, exact=True)
    if by == "label":
        return page_or_frame.get_by_label(value, exact=True)
    if by == "placeholder":
        return page_or_frame.get_by_placeholder(value, exact=True)
    if by == "text":
        return page_or_frame.get_by_text(value, exact=True)
    if by == "test_id":
        return page_or_frame.get_by_test_id(value)
    if by == "css":
        return page_or_frame.locator(value)
    return page_or_frame.locator(value if value.startswith("xpath=") else f"xpath={value}")


_INVENTORY_SCRIPT = r"""(limit) => {
  const selector = [
    'a[href]', 'button', 'input', 'textarea', 'select', 'option', 'summary',
    '[contenteditable="true"]', '[tabindex]:not([tabindex="-1"])',
    '[role="button"]', '[role="link"]', '[role="checkbox"]', '[role="radio"]',
    '[role="combobox"]', '[role="listbox"]', '[role="option"]', '[role="menu"]',
    '[role="menuitem"]', '[role="menuitemcheckbox"]', '[role="menuitemradio"]',
    '[role="tab"]', '[role="switch"]', '[role="slider"]', '[role="spinbutton"]',
    '[role="searchbox"]', '[role="textbox"]', '[role="treeitem"]', '[role="gridcell"]',
    '[role="row"]', '[role="columnheader"]', '[role="dialog"]', '[aria-haspopup]',
    '[aria-expanded]', '[aria-pressed]', '[aria-selected]',
    '[aria-label]', '[data-testid][role]', '[data-testid][aria-label]', '[data-testid][tabindex]'
  ].join(',');
  const visible = el => {
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return s.visibility !== 'hidden' && s.display !== 'none' && r.width > 0 && r.height > 0;
  };
  const label = el => {
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();
    if (el.labels && el.labels.length) return [...el.labels].map(x => x.innerText.trim()).join(' ');
    const type = (el.getAttribute('type') || '').toLowerCase();
    const sensitive = ['password', 'hidden'].includes(type) ||
      /password|one-time-code|cc-number|cc-csc/i.test(el.getAttribute('autocomplete') || '') ||
      /password|secret|token|cvv|cvc|card.?number|security.?code/i.test((el.getAttribute('name') || '') + ' ' + (el.id || ''));
    return (el.innerText || (!sensitive ? el.value : '') || el.getAttribute('placeholder') || el.getAttribute('title') || '').trim();
  };
  const all = [];
  const walk = root => {
    for (const el of root.querySelectorAll('*')) {
      if (el.matches(selector) && visible(el)) all.push(el);
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  };
  walk(document);
  const priority = el => {
    if (/^(A|BUTTON|INPUT|TEXTAREA|SELECT|OPTION|SUMMARY)$/.test(el.tagName)) return 0;
    const role = el.getAttribute('role') || '';
    if (/^(button|link|checkbox|radio|combobox|listbox|option|menuitem|tab|switch|slider|spinbutton|searchbox|textbox)$/.test(role)) return 1;
    if (el.hasAttribute('aria-haspopup') || el.hasAttribute('aria-expanded')) return 2;
    if (el.hasAttribute('aria-checked') || el.hasAttribute('aria-selected') || el.hasAttribute('aria-pressed')) return 3;
    if (el.hasAttribute('tabindex')) return 4;
    return 5;
  };
  all.sort((a, b) => priority(a) - priority(b));
  return all.slice(0, limit).map((el, i) => {
    const type = (el.getAttribute('type') || '').toLowerCase();
    const sensitive = ['password', 'hidden'].includes(type) ||
      /password|one-time-code|cc-number|cc-csc/i.test(el.getAttribute('autocomplete') || '') ||
      /password|secret|token|cvv|cvc|card.?number|security.?code/i.test(
        (el.getAttribute('name') || '') + ' ' + (el.id || '')
      );
    return {
    index: i, tag: el.tagName.toLowerCase(), type,
    role: el.getAttribute('role') || '', name: label(el).slice(0, 160), id: el.id || '',
    testId: el.getAttribute('data-testid') || '', placeholder: el.getAttribute('placeholder') || '',
    href: el.tagName === 'A' ? el.href : '',
    value: sensitive ? '[redacted]' : (type === 'file' ? Array.from(el.files || []).map(f => f.name).join(', ') : ('value' in el ? String(el.value || '') : '')).slice(0, 180),
    checked: ('checked' in el ? !!el.checked : undefined),
    selected: ('selected' in el ? !!el.selected : undefined),
    ariaChecked: el.getAttribute('aria-checked') || '',
    ariaSelected: el.getAttribute('aria-selected') || '',
    ariaPressed: el.getAttribute('aria-pressed') || '',
    ariaExpanded: el.getAttribute('aria-expanded') || '',
    ariaHaspopup: el.getAttribute('aria-haspopup') || '',
    ariaValueNow: el.getAttribute('aria-valuenow') || '',
    min: el.getAttribute('min') || '',
    max: el.getAttribute('max') || '',
    step: el.getAttribute('step') || '',
    disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
    required: !!el.required || el.getAttribute('aria-required') === 'true',
    multiple: !!el.multiple,
    selectedOptions: el.tagName === 'SELECT' ? [...el.selectedOptions].map(o => o.label).slice(0, 12) : [],
    inShadowRoot: !!el.getRootNode().host
    };
  });
}"""


def inventory_context(context, limit: int = 150) -> list[dict]:
    """Inspect every open page and its child frames; pierce open shadow roots per frame."""
    results: list[dict] = []
    for page_index, page in enumerate(context.pages):
        for frame_index, frame in enumerate(page.frames):
            remaining = max(0, limit - len(results))
            if remaining == 0:
                return results[:limit]
            try:
                items = frame.evaluate(_INVENTORY_SCRIPT, remaining)
                for item in items:
                    item["page_index"] = page_index
                    item["frame_index"] = frame_index
                    item["frame_url"] = frame.url
                    item["frame_name"] = frame.name
                results.extend(items)
            except Exception as exc:
                results.append({"page_index": page_index, "frame_index": frame_index,
                               "frame_url": frame.url, "discovery_error": type(exc).__name__,
                               "message": str(exc)[:200]})
    return results[:limit]


def inventory(page, limit: int = 150) -> list[dict]:
    return inventory_context(page.context, limit)



_OVERLAY_SCRIPT = r"""() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const visible = el => {
    const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.display !== 'none' &&
      s.visibility !== 'hidden' && Number(s.opacity || 1) > 0;
  };
  const selector = '[role="dialog"],[aria-modal="true"],dialog[open],[data-testid*="modal" i],[class*="modal" i]';
  const roots = Array.from(document.querySelectorAll(selector)).filter(visible);
  return roots.slice(-8).map((el, index) => {
    const buttons = Array.from(el.querySelectorAll(
      'button,a,[role="button"],input[type="button"],input[type="submit"]'
    )).filter(visible).slice(0, 20).map(btn => ({
      text: norm(btn.innerText || btn.value || ''),
      ariaLabel: btn.getAttribute('aria-label') || '',
      title: btn.getAttribute('title') || '',
      testId: btn.getAttribute('data-testid') || '',
      disabled: !!btn.disabled
    }));
    const text = norm(el.innerText || '').slice(0, 1000);
    const meta = norm([
      el.id || '', typeof el.className === 'string' ? el.className : '',
      el.getAttribute('data-testid') || '', el.getAttribute('aria-label') || ''
    ].join(' '));
    const lower = (text + ' ' + meta + ' ' + buttons.map(b =>
      b.text + ' ' + b.ariaLabel + ' ' + b.title + ' ' + b.testId
    ).join(' ')).toLowerCase();
    let category = 'unknown';
    if (/cookie|privacy preference|consent/.test(lower)) category = 'cookie_consent';
    else if (/newsletter|sign up for.*email|marketing|special offer|promo code|discount/.test(lower)) category = 'marketing';
    else if (/location|geolocation|your region|set your country|choose your country|zip code/.test(lower)) category = 'location_confirmation';
    else if (/shopping bag|view bag|cart|basket|checkout/.test(lower)) category = 'task_flow';
    else if (/sign in|log in|create an account/.test(lower)) category = 'authentication';
    return {index, category, text, meta, buttons};
  });
}""";


def overlay_inventory(page) -> list[dict]:
    """Describe visible DOM overlays without dismissing or clicking them."""
    try:
        return page.evaluate(_OVERLAY_SCRIPT) or []
    except Exception as exc:
        return [{"category": "inspection_error", "error": type(exc).__name__}]
