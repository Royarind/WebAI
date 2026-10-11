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
  const selector = 'a,button,input,textarea,select,[role="button"],[role="link"],[role="checkbox"],[role="radio"],[tabindex]:not([tabindex="-1"])';
  const visible = el => {
    const s = getComputedStyle(el), r = el.getBoundingClientRect();
    return s.visibility !== 'hidden' && s.display !== 'none' && r.width > 0 && r.height > 0;
  };
  const label = el => {
    if (el.getAttribute('aria-label')) return el.getAttribute('aria-label').trim();
    if (el.labels && el.labels.length) return [...el.labels].map(x => x.innerText.trim()).join(' ');
    return (el.innerText || el.value || el.getAttribute('placeholder') || el.getAttribute('title') || '').trim();
  };
  const all = [];
  const walk = root => {
    for (const el of root.querySelectorAll('*')) {
      if (el.matches(selector) && visible(el)) all.push(el);
      if (el.shadowRoot) walk(el.shadowRoot);
    }
  };
  walk(document);
  return all.slice(0, limit).map((el, i) => ({
    index: i, tag: el.tagName.toLowerCase(), type: el.getAttribute('type') || '',
    role: el.getAttribute('role') || '', name: label(el).slice(0, 160), id: el.id || '',
    testId: el.getAttribute('data-testid') || '', placeholder: el.getAttribute('placeholder') || '',
    href: el.tagName === 'A' ? el.href : '', disabled: !!el.disabled,
    inShadowRoot: !!el.getRootNode().host
  }));
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
