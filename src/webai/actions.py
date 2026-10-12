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
        candidates = []
        try:
            candidates = main.evaluate_all("""els => els.slice(0, 6).map(el => ({
                tag: el.tagName.toLowerCase(),
                type: el.getAttribute('type') || '',
                role: el.getAttribute('role') || '',
                placeholder: el.getAttribute('placeholder') || '',
                title: el.getAttribute('title') || '',
                aria_label: el.getAttribute('aria-label') || '',
                text: (el.innerText || el.value || '').trim().slice(0, 100),
                visible: !!(el.getClientRects().length),
                disabled: !!el.disabled
            }))""")
        except Exception:
            pass
        raise ValueError(
            f"Locator is ambiguous: main page matched {main_count} element(s), "
            f"and {len(frame_matches)} child frame(s) had a unique match. "
            f"Candidate details (up to 6): {json.dumps(candidates, ensure_ascii=False)}. "
            "Choose a unique visible, enabled target; do not retry with equivalent selector syntax."
        )
    raise LookupError(f"No element matched locator for action (searched main page and {len(page.frames)-1} child frames).")


def _recover_locator(page, by, value, name, action):
    """Resolve a unique target and recover from role/strategy mismatches using evidence.

    Fallback is attempted for every locator strategy, including a failed role locator.
    Candidates must be visible and enabled. If multiple distinct elements remain,
    fail with diagnostics rather than choosing the first match.
    """
    try:
        locator = locate(page, by, value, name)
        if locator.count() == 1:
            return locator, None
    except (LookupError, ValueError) as first_error:
        original_error = first_error
    else:
        original_error = LookupError("The requested locator did not resolve uniquely.")
    if not name:
        raise original_error

    roles = ("button", "link", "checkbox", "radio", "textbox", "searchbox",
             "combobox", "listbox", "option", "menuitem", "tab", "switch",
             "slider", "spinbutton")
    contexts = [page] + [frame for frame in page.frames if frame != page.main_frame]
    candidates, diagnostics = {}, []
    for context_index, context in enumerate(contexts):
        for role in roles:
            try:
                candidate = context.get_by_role(role, name=name, exact=True)
                count = candidate.count()
                if count != 1:
                    if count:
                        diagnostics.append({"role": role, "matches": count, "context": context_index})
                    continue
                if not candidate.is_visible() or candidate.is_disabled():
                    diagnostics.append({"role": role, "matches": count, "visible": candidate.is_visible(),
                                        "disabled": candidate.is_disabled(), "context": context_index})
                    continue
                key = f"{context_index}:" + candidate.evaluate("""el => {
                    const parts = [];
                    while (el && el.nodeType === 1) {
                      let index = 0, sibling = el;
                      while ((sibling = sibling.previousElementSibling)) index++;
                      parts.unshift(index);
                      el = el.parentElement;
                    }
                    return parts.join('/');
                }""")
                candidates[key] = (candidate, {"strategy": "accessible_role", "role": role,
                                                "context": context_index})
            except Exception:
                continue
        if not candidates:
            try:
                candidate = context.get_by_text(name, exact=True)
                count = candidate.count()
                if count == 1 and candidate.is_visible():
                    key = f"{context_index}:" + candidate.evaluate("""el => {
                        const parts = [];
                        while (el && el.nodeType === 1) {
                          let index = 0, sibling = el;
                          while ((sibling = sibling.previousElementSibling)) index++;
                          parts.unshift(index);
                          el = el.parentElement;
                        }
                        return parts.join('/');
                    }""")
                    candidates[key] = (candidate, {"strategy": "exact_text", "context": context_index})
                elif count:
                    diagnostics.append({"strategy": "exact_text", "matches": count, "context": context_index})
            except Exception:
                pass
    if len(candidates) == 1:
        candidate, strategy = next(iter(candidates.values()))
        return candidate, {"from": {"by": by, "value": value, "name": name},
                           "to": strategy, "reason": str(original_error)}
    if len(candidates) > 1:
        raise ValueError(
            f"Could not safely recover {action} target {name!r}: {len(candidates)} distinct visible "
            f"elements match. Inspect the current page and specify a unique target. "
            f"Additional matches: {json.dumps(diagnostics[:12], ensure_ascii=False)}"
        ) from original_error
    raise original_error


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
        meta = locator.evaluate("""el => ({
          tag: el.tagName.toLowerCase(),
          contenteditable: el.isContentEditable,
          value: ('value' in el) ? String(el.value) : null,
          text: el.isContentEditable ? (el.innerText || el.textContent || '') : null
        })""")
        actual = meta["value"] if meta["value"] is not None else meta["text"]
        verified = str(actual or "") == str(text)
        if not verified:
            raise RuntimeError(
                f"Post-fill verification failed: expected {text!r}, observed {actual!r}."
            )
        return {"ok": True, "action": "fill", "locator": {"by": by, "value": value, "name": name},
                "healed": healed, "verified": verified, "observed_value": actual}
    except Exception as exc:
        evidence = _evidence(page, "fill", exc)
        raise RuntimeError(str(evidence)) from exc


def select_option(page, by, value, option, name=None):
    """Select a native option or route a custom selector through control handling."""
    locator, healed = _recover_locator(page, by, value, name, "select")
    tag = locator.evaluate("el => el.tagName.toLowerCase()")
    if tag != "select":
        result = operate_control(page, by, value, "choose", option, name)
        result["action"] = "select"
        result["selection_strategy"] = "custom_control"
        return result
    locator.select_option(option, timeout=8000)
    selected_values = locator.locator("option:checked").evaluate_all("els => els.map(el => el.value)")
    selected_labels = locator.locator("option:checked").evaluate_all("els => els.map(el => (el.label || el.textContent || '').trim())")
    requested = option if isinstance(option, list) else [option]
    verified = all(str(item) in selected_values or str(item) in selected_labels for item in requested)
    if not verified:
        raise RuntimeError(
            f"Select verification failed: expected {option!r}, got values={selected_values!r}, labels={selected_labels!r}."
        )
    return {"ok": True, "action": "select", "option": option,
            "selected_values": selected_values, "selected_labels": selected_labels,
            "healed": healed, "verified": True}


def check(page, by, value, name=None, checked=True):
    """Set native or ARIA checkbox/radio/switch state and verify it."""
    locator, healed = _recover_locator(page, by, value, name, "check")
    meta = locator.evaluate("""el => ({
      tag: el.tagName.toLowerCase(),
      type: (el.getAttribute('type') || '').toLowerCase(),
      role: (el.getAttribute('role') || '').toLowerCase(),
      checked: ('checked' in el) ? !!el.checked : null,
      ariaChecked: el.getAttribute('aria-checked'),
      ariaPressed: el.getAttribute('aria-pressed'),
      disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true'
    })""")
    if meta["disabled"]:
        raise ValueError("Cannot change a disabled checkbox, radio, or switch.")
    if meta["type"] in {"checkbox", "radio"} or meta["role"] in {"checkbox", "radio"}:
        if meta["role"] == "radio" and not checked:
            raise ValueError("A radio button cannot be unchecked directly; choose another radio option.")
        if meta["checked"] is True and checked or meta["ariaChecked"] == str(checked).lower():
            return {"ok": True, "action": "check", "checked": checked, "already_set": True,
                    "healed": healed, "verified": True}
        if checked:
            locator.check(timeout=8000)
        else:
            locator.uncheck(timeout=8000)
        try:
            actual = locator.is_checked()
        except Exception:
            actual = locator.get_attribute("aria-checked") == "true"
    elif meta["role"] == "switch" or meta["ariaChecked"] in {"true", "false"} or meta["ariaPressed"] in {"true", "false"}:
        current = meta["ariaChecked"] == "true" if meta["ariaChecked"] is not None else meta["ariaPressed"] == "true"
        if current != bool(checked):
            locator.click(timeout=8000)
        aria_checked = locator.get_attribute("aria-checked")
        aria_pressed = locator.get_attribute("aria-pressed")
        actual = aria_checked == "true" if aria_checked is not None else aria_pressed == "true"
    else:
        raise ValueError("Target is not an identifiable checkbox, radio button, or switch.")
    if actual != bool(checked):
        raise RuntimeError(f"Checkbox/switch verification failed: expected {bool(checked)}, got {actual}.")
    return {"ok": True, "action": "check", "checked": bool(checked), "healed": healed, "verified": True}


def screenshot(page, path, full_page=True):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(path), full_page=bool(full_page))
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


def operate_control(page, by, value, operation, target=None, name=None, steps=1, timeout_ms=5000):
    """Operate common interactive controls through Playwright and verify state.

    Supported operations: set_value (range/slider/input), choose (native select),
    increment, decrement, and press (keyboard value adjustment). For +/- buttons,
    value should identify the quantity input; its nearby container is searched first.
    """
    operation = str(operation or "").strip().lower()
    allowed = {"set_value", "choose", "increment", "decrement", "press"}
    if operation not in allowed:
        raise ValueError(f"Unsupported control operation {operation!r}; choose from {sorted(allowed)}.")
    locator, healed = _recover_locator(page, by, value, name, operation)
    _one(locator, operation)
    if not locator.is_visible():
        raise ValueError("Target control is not visible. Scroll it into view and inspect again.")
    if locator.is_disabled():
        raise ValueError("Target control is disabled.")
    meta = locator.evaluate("""el => ({
      tag: el.tagName.toLowerCase(), type: (el.getAttribute('type') || '').toLowerCase(),
      role: (el.getAttribute('role') || '').toLowerCase(), value: ('value' in el) ? String(el.value) : '',
      min: el.getAttribute('min'), max: el.getAttribute('max'), step: el.getAttribute('step'),
      ariaValueNow: el.getAttribute('aria-valuenow'), ariaValueMin: el.getAttribute('aria-valuemin'),
      ariaValueMax: el.getAttribute('aria-valuemax'), disabled: !!el.disabled,
      label: el.getAttribute('aria-label') || el.innerText || ''
    })""")
    before_url = page.url
    if operation == "set_value":
        if target is None:
            raise ValueError("set_value requires a target value.")
        if meta["type"] == "range" or meta["role"] == "slider":
            locator.scroll_into_view_if_needed()
            box = locator.bounding_box()
            if not box or box["width"] <= 0 or box["height"] <= 0:
                raise LookupError("Slider has no visible bounding box.")
            minimum = float(meta.get("min") or meta.get("ariaValueMin") or 0)
            maximum = float(meta.get("max") or meta.get("ariaValueMax") or 100)
            desired = float(target)
            if maximum <= minimum or desired < minimum or desired > maximum:
                raise ValueError(f"Slider target must be between {minimum:g} and {maximum:g}.")
            # Use real Playwright mouse input rather than mutating the DOM value.
            rtl = locator.evaluate("el => getComputedStyle(el).direction === 'rtl'")
            ratio = (desired - minimum) / (maximum - minimum)
            if rtl:
                ratio = 1 - ratio
            x = box["x"] + ratio * box["width"]
            y = box["y"] + box["height"] / 2
            page.mouse.move(box["x"] + box["width"] / 2, y)
            page.mouse.down()
            page.mouse.move(x, y, steps=12)
            page.mouse.up()
            actual = locator.get_attribute("aria-valuenow") if meta["role"] == "slider" else locator.input_value()
            if actual is None:
                actual = locator.evaluate("el => String(el.value)")
            if float(actual) != desired:
                # Keyboard adjustment is a bounded fallback for browser/OS snapping.
                locator.focus()
                current = float(actual)
                step = float(meta.get("step") or 1)
                key = "ArrowRight" if desired > current else "ArrowLeft"
                for _ in range(min(100, int(abs(desired-current) / step))):
                    if current == desired:
                        break
                    locator.press(key, timeout=timeout_ms)
                    actual = locator.get_attribute("aria-valuenow") if meta["role"] == "slider" else locator.input_value()
                    current = float(actual or current)
                if float(actual) != desired:
                    raise RuntimeError(f"Slider verification failed: expected {target!r}, got {actual!r}.")
        else:
            locator.fill(str(target), timeout=timeout_ms)
            actual = locator.input_value(timeout=timeout_ms)
            if str(actual) != str(target):
                raise RuntimeError(f"Control value verification failed: expected {target!r}, got {actual!r}.")
    elif operation == "choose":
        if target is None:
            raise ValueError("choose requires an option value or visible label.")
        if meta["tag"] == "select":
            locator.select_option(label=str(target), timeout=timeout_ms)
            actual = locator.locator("option:checked").inner_text()
            selected_value = locator.input_value()
            if str(actual).strip() != str(target) and str(selected_value) != str(target):
                raise RuntimeError(f"Dropdown verification failed for {target!r}.")
        else:
            # Custom dropdowns may expose their trigger as a button, combobox,
            # tab, or generic labelled element. Open once, then inspect rendered
            # options across the page and its frames before selecting.
            locator.click(timeout=timeout_ms)
            target_name = str(target).strip()
            if not target_name:
                raise ValueError("Dropdown option label must not be empty.")
            contexts = [page] + [frame for frame in page.frames if frame != page.main_frame]
            candidates = []
            diagnostics = []
            option_roles = ("option", "menuitem", "menuitemcheckbox", "menuitemradio",
                            "radio", "checkbox", "button", "tab")
            for context in contexts:
                for role in option_roles:
                    try:
                        option_locator = context.get_by_role(role, name=target_name, exact=True)
                        count = option_locator.count()
                        if count == 1 and option_locator.is_visible() and not option_locator.is_disabled():
                            candidates.append((option_locator, role))
                        elif count:
                            diagnostics.append({"role": role, "matches": count})
                    except Exception:
                        continue
            if not candidates:
                for context in contexts:
                    try:
                        option_locator = context.get_by_text(target_name, exact=True)
                        count = option_locator.count()
                        if count == 1 and option_locator.is_visible():
                            candidates.append((option_locator, "exact_text"))
                        elif count:
                            diagnostics.append({"strategy": "exact_text", "matches": count})
                    except Exception:
                        continue
            # Deduplicate semantic locators that point to the same DOM node.
            unique = {}
            for option_locator, role in candidates:
                try:
                    node_key = option_locator.evaluate("""el => {
                      const parts = [];
                      while (el && el.nodeType === 1) {
                        let index = 0, sibling = el;
                        while ((sibling = sibling.previousElementSibling)) index++;
                        parts.unshift(index);
                        el = el.parentElement;
                      }
                      return parts.join('/');
                    }""")
                    unique[(option_locator.evaluate("el => el.ownerDocument.URL"), node_key)] = (option_locator, role)
                except Exception:
                    unique[(id(option_locator), role)] = (option_locator, role)
            if len(unique) != 1:
                raise LookupError(
                    f"Could not uniquely identify visible dropdown option {target_name!r}; "
                    f"found {len(unique)} distinct candidates. Inspect the open menu and retry with evidence. "
                    f"Matches: {json.dumps(diagnostics[:10], ensure_ascii=False)}"
                )
            option_locator, selected_role = next(iter(unique.values()))
            option_locator.click(timeout=timeout_ms)
            # Verify selected/checked state when exposed; otherwise require the
            # trigger's accessible label/text to reflect the chosen value.
            verified = False
            try:
                option_role = option_locator.get_attribute("role") or selected_role
                selected_state = (
                    option_locator.get_attribute("aria-selected") == "true"
                    or option_locator.get_attribute("aria-checked") == "true"
                    or option_locator.get_attribute("aria-pressed") == "true"
                )
                if option_role in {"radio", "checkbox"}:
                    selected_state = selected_state or option_locator.is_checked()
                verified = selected_state
            except Exception:
                pass
            try:
                selected = locator.get_attribute("aria-valuetext") or locator.get_attribute("aria-label") or locator.inner_text()
                verified = verified or target_name.casefold() in str(selected).casefold()
            except Exception:
                pass
            if not verified:
                # Some widgets close the menu and render the chosen value in an
                # associated value field. Look for one exact visible selected marker.
                for context in contexts:
                    try:
                        selected_nodes = context.locator(
                            '[aria-selected="true"],[aria-checked="true"],[aria-pressed="true"]'
                        ).filter(has_text=target_name)
                        if selected_nodes.count() == 1 and selected_nodes.is_visible():
                            verified = True
                            break
                    except Exception:
                        continue
            if not verified:
                raise RuntimeError(
                    f"Clicked dropdown option {target_name!r}, but the selected state could not be verified. "
                    "The menu may have changed; inspect the current page before any retry."
                )
    elif operation in {"increment", "decrement"}:
        try:
            steps = max(1, min(20, int(steps)))
        except (TypeError, ValueError):
            steps = 1
        locator.scroll_into_view_if_needed()
        if meta["tag"] == "input" and meta["type"] == "number":
            current = float(locator.input_value() or 0)
            increment = float(meta.get("step") or 1)
            desired = current + (increment * steps if operation == "increment" else -increment * steps)
            if meta.get("min") is not None:
                desired = max(float(meta["min"]), desired)
            if meta.get("max") is not None:
                desired = min(float(meta["max"]), desired)
            locator.fill(str(int(desired) if desired.is_integer() else desired))
            actual = float(locator.input_value())
            if actual != desired:
                raise RuntimeError(f"Quantity verification failed: expected {desired}, got {actual}.")
        else:
            # Look only near the target control to avoid clicking unrelated +/- buttons.
            container = locator.locator("xpath=..")
            button_words = ("plus", "increase", "increment", "add", "minus", "decrease", "decrement", "remove")
            candidates = []
            for scope in (container, container.locator("xpath=..")):
                buttons = scope.locator("button,[role='button'],input[type='button']")
                for i in range(min(buttons.count(), 20)):
                    btn = buttons.nth(i)
                    label = " ".join(filter(None, [btn.inner_text(), btn.get_attribute("aria-label"), btn.get_attribute("title"), btn.get_attribute("data-testid")])).strip().lower()
                    positive = any(w in label for w in ("plus", "increase", "increment", "add", "quantity up"))
                    negative = any(w in label for w in ("minus", "decrease", "decrement", "remove", "quantity down"))
                    if (operation == "increment" and positive) or (operation == "decrement" and negative):
                        candidates.append(btn)
                if candidates:
                    break
            if len(candidates) != 1:
                raise LookupError(f"Could not identify exactly one nearby {operation} button for this control.")
            for _ in range(steps):
                candidates[0].click(timeout=timeout_ms)
            actual = locator.input_value() if meta["tag"] == "input" else locator.get_attribute("aria-valuenow")
            if actual is None:
                raise RuntimeError("The +/- action was performed but the resulting quantity is not observable.")
    else:
        key = str(target or "ArrowRight")
        if key not in {"ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown"}:
            raise ValueError("press supports only ArrowLeft, ArrowRight, Home, End, PageUp, and PageDown.")
        locator.focus()
        locator.press(key, timeout=timeout_ms)
        actual = locator.get_attribute("aria-valuenow") or locator.input_value()
        if actual is None:
            raise RuntimeError("Keyboard action completed but the resulting control value is not observable.")
    return {"ok": True, "action": "control", "operation": operation, "target": target,
            "before": meta.get("value") or meta.get("ariaValueNow"), "verified": True,
            "locator": {"by": by, "value": value, "name": name}, "healed": healed,
            "url_before": before_url, "url_after": page.url}
