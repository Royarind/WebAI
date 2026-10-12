"""Evidence-driven web interaction engine shared by all Playwright actions.

The engine classifies controls, resolves targets conservatively, executes one
interaction, and verifies the observable postcondition. It intentionally does
not guess through ambiguity or blindly repeat potentially consequential actions.
"""
from __future__ import annotations

import json
from typing import Any

from . import actions
from .locators import inventory_context, make_locator, overlay_inventory


ACTIONABLE_ROLES = (
    "button", "link", "checkbox", "radio", "textbox", "searchbox",
    "combobox", "listbox", "option", "menuitem", "menuitemcheckbox",
    "menuitemradio", "tab", "switch", "slider", "spinbutton",
)


class InteractionEngine:
    """Unified, bounded interaction API for standard and custom web controls."""

    def __init__(self, page, timeout_ms: int = 5000):
        self.page = page
        self.timeout_ms = max(500, min(15000, int(timeout_ms)))

    def observe(self, limit: int = 180) -> dict:
        """Return a bounded snapshot of actionable controls, overlays and frames."""
        controls = inventory_context(self.page.context, limit=max(1, min(250, int(limit))))
        frames = []
        for index, frame in enumerate(self.page.frames):
            frames.append({
                "index": index,
                "name": frame.name or "",
                "url": frame.url,
                "is_main": frame == self.page.main_frame,
            })
        return {
            "url": self.page.url,
            "title": self.page.title(),
            "controls": controls,
            "overlays": overlay_inventory(self.page),
            "frames": frames,
            "control_count": len(controls),
        }

    @staticmethod
    def _visible_enabled(locator) -> bool:
        try:
            return locator.count() == 1 and locator.is_visible() and not locator.is_disabled()
        except Exception:
            return False

    def resolve(self, by: str, value: str, name: str | None = None, action: str = "interact"):
        """Resolve a unique target using the shared evidence-driven recovery logic."""
        return actions._recover_locator(self.page, by, value, name, action)

    def perform(self, action: str, *, by: str = "role", value: str = "",
                name: str | None = None, text: str | None = None,
                option: str | None = None, checked: bool = True,
                operation: str | None = None, target: Any = None,
                steps: int = 1, path: str | list[str] | None = None,
                target_by: str | None = None, target_value: str | None = None,
                target_name: str | None = None, key: str | None = None,
                dialog_action: str | None = None, prompt_text: str | None = None,
                x: float | None = None, y: float | None = None,
                to_x: float | None = None, to_y: float | None = None) -> dict:
        """Execute a supported interaction and return verification evidence."""
        action = str(action or "").strip().lower()
        before_url = self.page.url
        before_title = self.page.title()
        if action == "observe":
            return {"ok": True, "action": "observe", "observation": self.observe()}
        if action in {"click_at", "move_at", "drag_at"}:
            if x is None or y is None:
                raise ValueError(f"{action} requires numeric x and y coordinates from a fresh screenshot.")
            viewport = self.page.evaluate("() => ({width: innerWidth, height: innerHeight})")
            sx, sy = float(x), float(y)
            if not (0 <= sx < viewport["width"] and 0 <= sy < viewport["height"]):
                raise ValueError(f"Coordinates ({sx}, {sy}) are outside the current viewport {viewport}. Capture a fresh viewport screenshot.")
            before = self.page.evaluate("""({x,y}) => {
              const el = document.elementFromPoint(x,y);
              return el ? {tag: el.tagName.toLowerCase(), role: el.getAttribute('role') || '',
                label: el.getAttribute('aria-label') || '', text: (el.innerText || el.value || '').trim().slice(0,160)} : null;
            }""", {"x": sx, "y": sy})
            if action == "click_at":
                self.page.mouse.click(sx, sy)
            elif action == "move_at":
                self.page.mouse.move(sx, sy)
            else:
                if to_x is None or to_y is None:
                    raise ValueError("drag_at requires to_x and to_y destination coordinates.")
                dx, dy = float(to_x), float(to_y)
                if not (0 <= dx < viewport["width"] and 0 <= dy < viewport["height"]):
                    raise ValueError(f"Destination coordinates ({dx}, {dy}) are outside viewport {viewport}.")
                self.page.mouse.move(sx, sy)
                self.page.mouse.down()
                self.page.mouse.move(dx, dy, steps=12)
                self.page.mouse.up()
            after = self.page.evaluate("""({x,y}) => {
              const el = document.elementFromPoint(x,y);
              return el ? {tag: el.tagName.toLowerCase(), role: el.getAttribute('role') || '',
                label: el.getAttribute('aria-label') || '', text: (el.innerText || el.value || '').trim().slice(0,160)} : null;
            }""", {"x": sx, "y": sy})
            return {"ok": True, "action": action, "coordinates": {"x": sx, "y": sy},
                    "destination": ({"x": float(to_x), "y": float(to_y)} if action == "drag_at" else None),
                    "element_before": before, "element_after": after,
                    "action_dispatched": True, "verified": False,
                    "verification_note": "Mouse event was dispatched to the observed viewport coordinate; inspect the resulting page state before claiming task completion."}
        if action == "click":
            dialog_policy = str(dialog_action or "dismiss").strip().lower()
            if dialog_policy not in {"dismiss", "accept"}:
                raise ValueError("dialog_action must be dismiss or accept.")
            dialog_info = {}
            def handle_dialog(dialog):
                dialog_info.update({"type": dialog.type, "message": dialog.message,
                                    "default_value": getattr(dialog, "default_value", "")})
                # Confirm/prompt dialogs are accepted only when the planner has
                # explicit user authorization. Otherwise dismiss conservatively.
                if dialog_policy == "accept":
                    if dialog.type == "prompt":
                        dialog.accept(prompt_text or "")
                    else:
                        dialog.accept()
                    dialog_info["decision"] = "accepted"
                else:
                    dialog.dismiss()
                    dialog_info["decision"] = "dismissed"
            self.page.on("dialog", handle_dialog)
            try:
                result = actions.click(self.page, by, value, name, timeout_ms=self.timeout_ms)
            finally:
                try:
                    self.page.remove_listener("dialog", handle_dialog)
                except Exception:
                    pass
            if dialog_info:
                result["dialog"] = dialog_info
                result["dialog_policy"] = dialog_policy
            return result
        if action == "fill":
            return actions.fill(self.page, by, value, str(text or ""), name, timeout_ms=self.timeout_ms)
        if action == "select":
            return actions.select_option(self.page, by, value, option if option is not None else target, name)
        if action == "check":
            return actions.check(self.page, by, value, name, bool(checked))
        if action == "control":
            return actions.operate_control(
                self.page, by, value, operation or "choose",
                target if target is not None else option, name, steps, self.timeout_ms
            )
        if action in {"hover", "double_click", "right_click", "focus", "blur", "press", "upload", "drag_drop"}:
            locator, healed = self.resolve(by, value, name, action)
            upload_meta = None
            if action == "upload":
                upload_meta = locator.evaluate("""el => ({
                  tag: el.tagName.toLowerCase(), type: (el.getAttribute('type') || '').toLowerCase(),
                  disabled: !!el.disabled || el.getAttribute('aria-disabled') === 'true'
                })""")
                if upload_meta["disabled"]:
                    raise ValueError("Cannot upload through a disabled control.")
                # Native file inputs are often intentionally hidden behind a
                # visible Upload button. set_input_files works without exposing it.
                if not (upload_meta["tag"] == "input" and upload_meta["type"] == "file"):
                    locator.scroll_into_view_if_needed(timeout=self.timeout_ms)
                    if not locator.is_visible():
                        raise LookupError("Upload trigger is not visible.")
            else:
                locator.scroll_into_view_if_needed(timeout=self.timeout_ms)
                if not locator.is_visible():
                    raise LookupError(f"Target for {action} is not visible.")
            if action == "hover":
                locator.hover(timeout=self.timeout_ms)
                verified = locator.evaluate("el => !!(el.matches(':hover') || el.contains(document.activeElement))")
            elif action == "double_click":
                locator.dblclick(timeout=self.timeout_ms)
                verified = False
            elif action == "right_click":
                locator.click(button="right", timeout=self.timeout_ms)
                verified = False
            elif action == "focus":
                locator.focus(timeout=self.timeout_ms)
                verified = locator.evaluate("el => document.activeElement === el")
                if not verified:
                    raise RuntimeError("Focus action completed but target did not become active.")
            elif action == "blur":
                locator.evaluate("el => el.blur()")
                verified = not locator.evaluate("el => document.activeElement === el")
                if not verified:
                    raise RuntimeError("Blur action completed but target retained focus.")
            elif action == "press":
                allowed_keys = {"Enter", "Escape", "Tab", "Space", "ArrowUp", "ArrowDown",
                                "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown",
                                "Backspace", "Delete", "Control+A", "Control+C", "Control+V",
                                "Control+X", "Control+Z", "Control+Y", "Control+Enter",
                                "Shift+Tab", "Alt+ArrowDown", "Meta+A", "Meta+C", "Meta+V"}
                if key not in allowed_keys and not (isinstance(key, str) and len(key) == 1):
                    raise ValueError(f"Unsupported key {key!r}.")
                locator.press(key, timeout=self.timeout_ms)
                verified = False
            elif action == "upload":
                if not path:
                    raise ValueError("upload requires path to one or more existing local files.")
                from pathlib import Path
                raw_paths = path if isinstance(path, list) else [path]
                file_paths = [Path(item).expanduser().resolve(strict=True) for item in raw_paths]
                if not file_paths or any(not item.is_file() for item in file_paths):
                    raise ValueError("Every upload path must point to an existing file.")
                set_files = [str(item) for item in file_paths]
                expected_names = [item.name for item in file_paths]
                tag_type = upload_meta
                if tag_type["tag"] == "input" and tag_type["type"] == "file":
                    locator.set_input_files(set_files, timeout=self.timeout_ms)
                    files = locator.evaluate("el => Array.from(el.files || []).map(f => f.name)")
                else:
                    # Many sites hide the native file input behind an Upload/Attach
                    # button. Capture the browser file chooser event rather than
                    # attempting to type a path into the page.
                    with self.page.expect_file_chooser(timeout=self.timeout_ms) as chooser_info:
                        locator.click(timeout=self.timeout_ms)
                    chooser = chooser_info.value
                    chooser.set_files(set_files)
                    files = chooser.element.evaluate("el => Array.from(el.files || []).map(f => f.name)")
                verified = all(name in files for name in expected_names)
                if not verified:
                    raise RuntimeError(f"Upload was attempted but expected files {expected_names!r} were not all observable; got {files!r}.")
                return {"ok": True, "action": action, "path": set_files,
                        "files": files, "verified": True, "healed": healed}
            else:
                if not target_by or not target_value:
                    raise ValueError("drag_drop requires target_by and target_value for the destination.")
                destination, destination_healed = self.resolve(target_by, target_value, target_name, "drag_drop destination")
                before = locator.evaluate("""el => {
                  const path = [];
                  let node = el;
                  while (node && node.nodeType === 1) {
                    let index = 0, sibling = node;
                    while ((sibling = sibling.previousElementSibling)) index++;
                    path.unshift(index); node = node.parentElement;
                  }
                  return {parent: el.parentElement ? el.parentElement.tagName + '#' + (el.parentElement.id || '') : '',
                          path: path.join('/'), text: (el.innerText || '').slice(0,120)};
                }""")
                before_box = locator.bounding_box()
                locator.drag_to(destination, timeout=self.timeout_ms)
                after = locator.evaluate("""el => {
                  const path = [];
                  let node = el;
                  while (node && node.nodeType === 1) {
                    let index = 0, sibling = node;
                    while ((sibling = sibling.previousElementSibling)) index++;
                    path.unshift(index); node = node.parentElement;
                  }
                  return {parent: el.parentElement ? el.parentElement.tagName + '#' + (el.parentElement.id || '') : '',
                          path: path.join('/'), text: (el.innerText || '').slice(0,120)};
                }""")
                after_box = locator.bounding_box()
                moved = before["parent"] != after["parent"] or before["path"] != after["path"]
                if before_box and after_box:
                    moved = moved or abs(before_box["x"]-after_box["x"]) > 2 or abs(before_box["y"]-after_box["y"]) > 2
                return {"ok": True, "action": action, "verified": bool(moved),
                        "before": before, "after": after, "source_moved": bool(moved),
                        "source": {"by": by, "value": value, "name": name},
                        "destination": {"by": target_by, "value": target_value, "name": target_name},
                        "healed": {"source": healed, "destination": destination_healed},
                        "verification_note": "Position or parent changed." if moved else "Drag was dispatched, but a changed position/parent was not observed."}
            return {"ok": True, "action": action, "verified": bool(verified),
                    "action_dispatched": action in {"double_click", "right_click", "press"},
                    "locator": {"by": by, "value": value, "name": name},
                    "healed": healed, "url_before": before_url, "url_after": self.page.url}
        if action == "download":
            if not value and not name:
                raise ValueError("download requires a unique control locator.")
            locator, healed = self.resolve(by, value, name, "download")
            with self.page.expect_download(timeout=self.timeout_ms) as download_info:
                locator.click(timeout=self.timeout_ms)
            download = download_info.value
            if path:
                from pathlib import Path
                destination = Path(path)
                destination.parent.mkdir(parents=True, exist_ok=True)
                download.save_as(str(destination))
                saved_path = str(destination.resolve())
            else:
                saved_path = None
            return {"ok": True, "action": action, "suggested_filename": download.suggested_filename,
                    "path": saved_path, "verified": bool(download.suggested_filename), "healed": healed}
        if action == "wait_for":
            state = str(operation or "visible").lower()
            if state not in {"visible", "hidden", "attached", "detached"}:
                raise ValueError("wait_for operation must be visible, hidden, attached, or detached.")
            locator, healed = self.resolve(by, value, name, "wait_for")
            locator.wait_for(state=state, timeout=self.timeout_ms)
            return {"ok": True, "action": action, "state": state, "verified": True,
                    "locator": {"by": by, "value": value, "name": name}, "healed": healed}
        if action == "scroll":
            direction = str(value or "down").lower()
            if direction not in {"up", "down"}:
                raise ValueError("scroll direction must be up or down.")
            amount = max(100, min(1400, int(text or 650)))
            delta = amount if direction == "down" else -amount
            if target_value:
                locator, healed = self.resolve(target_by or by, target_value, target_name, "scroll")
                before = locator.evaluate("el => ({top: el.scrollTop, left: el.scrollLeft, height: el.scrollHeight, client: el.clientHeight})")
                locator.evaluate("(el, delta) => el.scrollBy(0, delta)", delta)
                self.page.wait_for_timeout(100)
                after = locator.evaluate("el => ({top: el.scrollTop, left: el.scrollLeft, height: el.scrollHeight, client: el.clientHeight})")
                changed = before["top"] != after["top"]
                return {"ok": True, "action": action, "direction": direction, "amount": amount,
                        "target": target_value, "before": before, "after": after, "verified": changed,
                        "healed": healed, "url": self.page.url}
            before = self.page.evaluate("() => window.scrollY")
            self.page.evaluate("(delta) => window.scrollBy(0, delta)", delta)
            after = self.page.evaluate("() => window.scrollY")
            return {"ok": True, "action": action, "direction": direction, "amount": amount,
                    "before": before, "after": after, "verified": before != after, "url": self.page.url}
        if action == "navigate":
            if not str(value).startswith(("http://", "https://")):
                raise ValueError("navigate requires an http(s) URL.")
            self.page.goto(value, wait_until="domcontentloaded", timeout=self.timeout_ms)
            return {"ok": True, "action": action, "url_before": before_url, "url_after": self.page.url,
                    "title_before": before_title, "title_after": self.page.title(),
                    "verified": self.page.url == value or self.page.url.startswith(value.rstrip("/") + "/")}
        if action == "read_text":
            locator, healed = self.resolve(by, value, name, action)
            result = locator.inner_text(timeout=self.timeout_ms)
            return {"ok": True, "action": action, "text": result[:6000], "verified": bool(result.strip()),
                    "healed": healed}
        if action == "screenshot":
            from pathlib import Path
            out = Path(path or "artifacts/page.png")
            out.parent.mkdir(parents=True, exist_ok=True)
            self.page.screenshot(path=str(out), full_page=True, timeout=self.timeout_ms)
            return {"ok": True, "action": action, "path": str(out), "verified": out.exists()}
        raise ValueError(f"Unsupported interaction action {action!r}.")
