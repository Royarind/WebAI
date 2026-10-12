"""Specialized, evidence-driven handlers for composite web interactions.

These handlers complement the shared locator/action layer. They never guess among
ambiguous targets and return explicit verification status rather than treating a
dispatched event as proof of success.
"""
from __future__ import annotations

from datetime import date, datetime
import json
import re
from typing import Any


def _visible_unique(candidates, description: str):
    visible = []
    diagnostics = []
    seen = set()
    for locator, strategy in candidates:
        try:
            count = locator.count()
            if count != 1 or not locator.is_visible() or locator.is_disabled():
                if count:
                    diagnostics.append({"strategy": strategy, "matches": count})
                continue
            identity = locator.evaluate("""el => {
              const path = [];
              let node = el;
              while (node && node.nodeType === 1) {
                let index = 0, sibling = node;
                while ((sibling = sibling.previousElementSibling)) index++;
                path.unshift(index); node = node.parentElement;
              }
              const root = el.getRootNode();
              return (root && root.host ? 'shadow:' + root.host.tagName + '#' + (root.host.id || '') : '') + '/' + path.join('/');
            }""")
            key = (locator.evaluate("el => el.ownerDocument.URL"), identity)
            if key not in seen:
                seen.add(key)
                visible.append((locator, strategy))
        except Exception as exc:
            diagnostics.append({"strategy": strategy, "error": type(exc).__name__})
    if len(visible) != 1:
        raise LookupError(
            f"Expected exactly one visible, enabled {description}; found {len(visible)}. "
            f"Inspect current page evidence and refine the target. Candidates: "
            f"{json.dumps(diagnostics[:12], ensure_ascii=False)}"
        )
    return visible[0]


def _set_date(engine, by: str, value: str, name: str | None, target: Any,
              text: str | None, target_name: str | None) -> dict:
    raw = str(target if target is not None else text or "").strip()
    if not raw:
        raise ValueError("set_date requires target='YYYY-MM-DD' (or the format required by a native date/time input).")
    locator, healed = engine.resolve(by, value, name, "set_date")
    meta = locator.evaluate("""el => ({
      tag: el.tagName.toLowerCase(), type: (el.getAttribute('type') || '').toLowerCase(),
      value: ('value' in el) ? String(el.value) : '',
      disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true',
      label: el.getAttribute('aria-label') || el.innerText || '',
      expanded: el.getAttribute('aria-expanded')
    })""")
    if meta["disabled"]:
        raise ValueError("Cannot set a date on a disabled control.")
    if meta["tag"] == "input" and meta["type"] in {"date", "datetime-local", "month", "time"}:
        try:
            if meta["type"] == "date":
                date.fromisoformat(raw)
            elif meta["type"] == "datetime-local":
                datetime.fromisoformat(raw)
            elif meta["type"] == "month" and not re.fullmatch(r"\d{4}-\d{2}", raw):
                raise ValueError("month input expects YYYY-MM.")
            elif meta["type"] == "time" and not re.fullmatch(r"\d{2}:\d{2}(:\d{2})?", raw):
                raise ValueError("time input expects HH:MM or HH:MM:SS.")
        except ValueError as exc:
            raise ValueError(f"Invalid value {raw!r} for input type {meta['type']}: {exc}") from exc
        locator.fill(raw, timeout=engine.timeout_ms)
        actual = locator.input_value(timeout=engine.timeout_ms)
        verified = actual == raw
        if not verified:
            raise RuntimeError(f"Date/time verification failed: expected {raw!r}, observed {actual!r}.")
        return {"ok": True, "action": "set_date", "value": actual, "verified": True,
                "input_type": meta["type"], "healed": healed}
    # Custom calendars must expose an exact date/label contract. Open the trigger
    # once, then select only a unique date cell; never navigate months by guessing.
    if meta["expanded"] != "true":
        locator.click(timeout=engine.timeout_ms)
    contexts = [engine.page] + [frame for frame in engine.page.frames if frame != engine.page.main_frame]
    label = str(target_name or raw).strip()
    candidates = []
    for context in contexts:
        for selector, selector_value in (
            ("[data-date]", raw), ("[data-value]", raw), ("[aria-label]", label),
        ):
            try:
                candidates.append((context.locator(f'[{selector.strip("[]")}={json.dumps(selector_value)}]'), selector))
            except Exception:
                pass
        for role in ("button", "gridcell", "option", "link"):
            try:
                candidates.append((context.get_by_role(role, name=label, exact=True), f"role:{role}"))
            except Exception:
                pass
    chosen, strategy = _visible_unique(candidates, f"calendar date {label!r}")
    chosen.click(timeout=engine.timeout_ms)
    selected = False
    try:
        selected = (
            chosen.get_attribute("aria-selected") == "true"
            or chosen.get_attribute("aria-pressed") == "true"
            or chosen.get_attribute("aria-current") == "date"
        )
    except Exception:
        pass
    trigger_text = ""
    try:
        trigger_text = " ".join(filter(None, [
            locator.get_attribute("aria-label"), locator.get_attribute("aria-valuetext"),
            locator.inner_text(), locator.get_attribute("value")
        ]))
    except Exception:
        pass
    verified = selected or raw in trigger_text or label.casefold() in trigger_text.casefold()
    return {"ok": True, "action": "set_date", "value": raw, "strategy": strategy,
            "verified": bool(verified), "verification_note": (
                "Date selection is reflected in the control or selected-state semantics."
                if verified else "Date cell was clicked, but the chosen date is not yet observable; inspect before retrying."
            ), "healed": healed}


def _activate_tab(engine, by: str, value: str, name: str | None) -> dict:
    locator, healed = engine.resolve(by, value, name, "select_tab")
    if locator.get_attribute("role") != "tab":
        raise ValueError("select_tab requires a target exposed as role=tab.")
    before = locator.get_attribute("aria-selected")
    if before != "true":
        locator.click(timeout=engine.timeout_ms)
    after = locator.get_attribute("aria-selected")
    panel_id = locator.get_attribute("aria-controls")
    panel_visible = False
    if panel_id:
        try:
            panel = locator.page.locator("#" + panel_id)
            panel_visible = panel.count() == 1 and panel.is_visible()
        except Exception:
            pass
    verified = after == "true" or panel_visible
    if not verified:
        raise RuntimeError("Tab activation was dispatched, but aria-selected or its controlled panel did not verify activation.")
    return {"ok": True, "action": "select_tab", "selected": True, "verified": True,
            "before_selected": before, "after_selected": after, "panel_id": panel_id,
            "panel_visible": panel_visible, "healed": healed}


def _set_expanded(engine, action: str, by: str, value: str, name: str | None) -> dict:
    locator, healed = engine.resolve(by, value, name, action)
    desired = action == "expand"
    meta = locator.evaluate("""el => ({
      expanded: el.getAttribute('aria-expanded'),
      tag: el.tagName.toLowerCase(),
      open: el.tagName.toLowerCase() === 'details' ? !!el.open :
            (el.closest('details') ? !!el.closest('details').open : null),
      disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true'
    })""")
    if meta["disabled"]:
        raise ValueError(f"Cannot {action} a disabled control.")
    if meta["expanded"] in {"true", "false"}:
        current = meta["expanded"] == "true"
    elif meta["open"] is not None:
        current = meta["open"]
    else:
        raise ValueError(f"Target exposes neither aria-expanded nor native details state; refusing an unverifiable {action}.")
    if current != desired:
        locator.click(timeout=engine.timeout_ms)
    after = locator.evaluate("""el => ({
      expanded: el.getAttribute('aria-expanded'),
      open: el.tagName.toLowerCase() === 'details' ? !!el.open :
            (el.closest('details') ? !!el.closest('details').open : null)
    })""")
    actual = after["expanded"] == "true" if after["expanded"] in {"true", "false"} else after["open"]
    if actual is not desired:
        raise RuntimeError(f"{action} action did not reach the requested state.")
    return {"ok": True, "action": action, "expanded": desired, "verified": True,
            "before": current, "after": actual, "healed": healed}


def _table_action(engine, row_text: str | None, control_name: str | None) -> dict:
    if not row_text or not control_name:
        raise ValueError("table_action requires text=<unique row text> and target_name=<button/link name>.")
    rows = engine.page.locator("tr,[role='row']").filter(has_text=row_text)
    count = rows.count()
    if count != 1:
        raise LookupError(f"Expected exactly one table row containing {row_text!r}; found {count}. Refine the row text.")
    row = rows
    before_text = row.inner_text().strip()[:1000]
    controls = []
    for role in ("button", "link"):
        candidate = row.get_by_role(role, name=control_name, exact=True)
        if candidate.count():
            controls.append((candidate, role))
    control, role = _visible_unique(controls, f"row action {control_name!r}")
    control.click(timeout=engine.timeout_ms)
    # Give the UI a short, bounded opportunity to apply a synchronous/asynchronous
    # row update; no repeat is attempted if the result is not observable.
    try:
        engine.page.wait_for_timeout(100)
    except Exception:
        pass
    after_count = rows.count()
    after_text = rows.inner_text().strip()[:1000] if after_count == 1 else ""
    verified = after_count != 1 or after_text != before_text
    return {"ok": True, "action": "table_action", "row_text": row_text,
            "control_name": control_name, "control_role": role, "before": before_text,
            "after": after_text, "row_count_after": after_count, "verified": bool(verified),
            "verification_note": "The row disappeared or changed." if verified else
                "Action was dispatched but the row did not visibly change; inspect before retrying."}


def _validate_form(engine, by: str, value: str, name: str | None) -> dict:
    locator, healed = engine.resolve(by, value, name, "validate_form")
    meta = locator.evaluate("""form => {
      const controls = Array.from(form.querySelectorAll('input,select,textarea,[contenteditable="true"]'));
      const invalid = controls.filter(el => {
        if (el.disabled || el.type === 'hidden') return false;
        if (el.willValidate === false) return false;
        return !el.checkValidity();
      }).map(el => ({
        tag: el.tagName.toLowerCase(),
        type: (el.getAttribute('type') || '').toLowerCase(),
        name: el.getAttribute('name') || '',
        id: el.id || '',
        label: (el.labels && el.labels.length ? Array.from(el.labels).map(l => l.innerText.trim()).join(' ') : '') ||
               el.getAttribute('aria-label') || el.getAttribute('placeholder') || el.name || el.id || 'unnamed field',
        message: el.validationMessage || 'Invalid value'
      }));
      return {isForm: form.tagName.toLowerCase() === 'form',
              valid: form.tagName.toLowerCase() === 'form' ? form.checkValidity() : controls.every(el => el.checkValidity()),
              invalid};
    }""")
    if not meta["isForm"]:
        raise ValueError("validate_form target must resolve to a <form> element.")
    return {"ok": True, "action": "validate_form", "valid": bool(meta["valid"]),
            "invalid_fields": meta["invalid"], "verified": True, "healed": healed,
            "submitted": False}


def perform_advanced(engine, action: str, *, by: str, value: str, name: str | None,
                     target: Any = None, text: str | None = None,
                     target_name: str | None = None) -> dict:
    """Dispatch advanced but bounded interaction types."""
    if action == "set_date":
        return _set_date(engine, by, value, name, target, text, target_name)
    if action == "select_tab":
        return _activate_tab(engine, by, value, name)
    if action in {"expand", "collapse"}:
        return _set_expanded(engine, action, by, value, name)
    if action == "table_action":
        return _table_action(engine, text, target_name)
    if action == "validate_form":
        return _validate_form(engine, by, value, name)
    raise ValueError(f"Unsupported advanced interaction action {action!r}.")
