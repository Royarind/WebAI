from __future__ import annotations
from pathlib import Path
from datetime import datetime
import json
from .locators import make_locator
from .webai_dom_intelligence import DOMIntelligence


def _one(locator, action: str):
    count = locator.count()
    if count == 0:
        raise LookupError(f"No element matched locator for {action}.")
    if count > 1:
        raise ValueError(f"Locator matched {count} elements; make it unique before {action}.")
    return locator


def locate(page, by, value, name=None):
    """Find a unique match in the main page or one of its frames."""
    main = make_locator(page, by, value, name)
    main_count = main.count()
    if main_count == 1:
        return main
    frame_matches = []
    for frame in page.frames:
        if frame == page.main_frame:
            continue
        try:
            loc = make_locator(frame, by, value, name)
            if loc.count() == 1:
                frame_matches.append(loc)
        except Exception:
            continue
    if main_count == 0 and len(frame_matches) == 1:
        return frame_matches[0]
    if main_count > 1 or len(frame_matches) > 1 or (main_count == 1 and frame_matches):
        raise ValueError("Locator is ambiguous across the page and its frames; narrow the locator.")
    raise LookupError(f"No element matched locator for action (searched main page and {len(page.frames)-1} child frames).")


def _recover_locator(page, by, value, name, action):
    """Conservative locator healing: only use explicit accessible name as fallback."""
    try:
        return locate(page, by, value, name), None
    except (LookupError, ValueError) as first_error:
        if name and by != "role":
            for role in ("button", "link", "checkbox", "radio", "textbox", "combobox"):
                try:
                    candidate = make_locator(page, "role", role, name)
                    if candidate.count() == 1:
                        return candidate, {"from": {"by": by, "value": value},
                                           "to": {"by": "role", "value": role, "name": name},
                                           "reason": str(first_error)}
                except Exception:
                    continue
        raise first_error


def _evidence(page, action: str, exc: Exception) -> dict:
    path = Path("artifacts") / f"failure_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
    screenshot_path = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(path), full_page=True, timeout=3000)
        screenshot_path = str(path)
    except Exception:
        pass
    return {"ok": False, "action": action, "error_type": type(exc).__name__,
            "error": str(exc), "url": getattr(page, "url", None),
            "screenshot": screenshot_path}


def click(page, by, value, name=None, timeout_ms=3000):
    try:
        locator, healed = _recover_locator(page, by, value, name, "click")
    except (LookupError, ValueError) as locator_error:
        # Only resolve a better target when the original locator did not resolve
        # uniquely. Never use DOM intelligence to retry after a click timeout,
        # because the original click may already have taken effect.
        if not name:
            raise
        from .sync_dom_intelligence import SyncDOMIntelligence
        intent = str(name).strip()
        if not intent:
            raise locator_error
        locator, diagnostics = SyncDOMIntelligence(page).resolve(intent)
        healed = {
            "from": {"by": by, "value": value, "name": name},
            "to": {"strategy": "sync_dom_intelligence", "intent": intent},
            "diagnostics": diagnostics,
            "reason": str(locator_error),
        }
    before_url = page.url
    try:
        # Product pages often expose visually hidden checkbox/radio inputs while
        # the associated label is the real user-facing target. Clicking the input
        # directly can be intercepted by an adjacent option label.
        input_meta = locator.evaluate("""el => ({
            tag: el.tagName.toLowerCase(),
            type: (el.getAttribute('type') || '').toLowerCase(),
            id: el.id || '',
            checked: !!el.checked,
            disabled: !!el.disabled,
            has_label: !!(el.labels && el.labels.length)
        })""")
        if input_meta["tag"] == "input" and input_meta["type"] in {"checkbox", "radio"} and input_meta["has_label"]:
            if input_meta["disabled"]:
                raise ValueError("Cannot click a disabled checkbox or radio input.")
            if input_meta["checked"]:
                return {"ok": True, "action": "click", "verified": True,
                        "already_selected": True, "control_type": input_meta["type"],
                        "locator": {"by": by, "value": value, "name": name}, "healed": healed}
            label = page.locator("label[for=" + json.dumps(input_meta["id"]) + "]")
            if label.count() == 1:
                box = label.bounding_box()
                if not box or box["width"] <= 0 or box["height"] <= 0:
                    raise LookupError("Associated option label is not visible.")
                label.click(timeout=timeout_ms, position={"x": min(5, max(1, box["width"] / 2)),
                                                          "y": box["height"] / 2})
                selected = locator.is_checked()
                if not selected:
                    raise RuntimeError("Option label was clicked, but the checkbox/radio state did not change.")
                return {"ok": True, "action": "click", "verified": True,
                        "control_type": input_meta["type"], "selected": True,
                        "locator": {"by": by, "value": value, "name": name},
                        "healed": healed, "url_before": before_url, "url_after": page.url}
        locator.click(timeout=timeout_ms)
        return {"ok": True, "action": "click", "locator": {"by": by, "value": value, "name": name},
                "healed": healed, "url_before": before_url, "url_after": page.url,
                "title_after": page.title(), "action_completed": True}
    except Exception as exc:
        evidence = _evidence(page, "click", exc)
        raise RuntimeError(str(evidence)) from exc


def fill(page, by, value, text, name=None, timeout_ms=8000):
    locator, healed = _recover_locator(page, by, value, name, "fill")
    try:
        locator.fill(text, timeout=timeout_ms)
        actual = locator.input_value(timeout=timeout_ms)
        verified = actual == text
        if not verified:
            raise RuntimeError("Post-fill verification failed: input value differs from requested text.")
        return {"ok": True, "action": "fill", "locator": {"by": by, "value": value, "name": name},
                "healed": healed, "verified": verified}
    except Exception as exc:
        evidence = _evidence(page, "fill", exc)
        raise RuntimeError(str(evidence)) from exc


def select_option(page, by, value, option, name=None):
    locator, healed = _recover_locator(page, by, value, name, "select")
    locator.select_option(option, timeout=8000)
    selected = locator.input_value()
    if selected != option:
        raise RuntimeError(f"Select verification failed: expected {option!r}, got {selected!r}.")
    return {"ok": True, "action": "select", "option": option, "healed": healed, "verified": True}


def check(page, by, value, name=None, checked=True):
    locator, healed = _recover_locator(page, by, value, name, "check")
    locator.check(timeout=8000) if checked else locator.uncheck(timeout=8000)
    actual = locator.is_checked()
    if actual != checked:
        raise RuntimeError("Checkbox verification failed.")
    return {"ok": True, "action": "check", "checked": checked, "healed": healed, "verified": True}


def screenshot(page, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(path), full_page=True)
    return str(path)


async def click_with_dom_intelligence(
    page,
    intent: str,
    validate=None,
    authorized: bool = False,
):
    """Click an element inferred from natural language intent using DOM intelligence.
    
    Inspects DOM, open shadow roots, and frames, ranks candidate elements,
    attempts clicks in order of confidence, and validates outcomes.
    """
    engine = DOMIntelligence(
        page,
        max_candidates=80,
        max_attempts=5,
    )
    return await engine.click_intent(
        intent,
        authorized=authorized,
        validate=validate,
    )
