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
                steps: int = 1, path: str | None = None,
                target_by: str | None = None, target_value: str | None = None,
                target_name: str | None = None, key: str | None = None) -> dict:
        """Execute a supported interaction and return verification evidence."""
        action = str(action or "").strip().lower()
        before_url = self.page.url
        before_title = self.page.title()
        if action == "observe":
            return {"ok": True, "action": "observe", "observation": self.observe()}
        if action == "click":
            return actions.click(self.page, by, value, name, timeout_ms=self.timeout_ms)
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
        if action in {"hover", "double_click", "press", "upload", "drag_drop"}:
            locator, healed = self.resolve(by, value, name, action)
            locator.scroll_into_view_if_needed(timeout=self.timeout_ms)
            if not locator.is_visible():
                raise LookupError(f"Target for {action} is not visible.")
            if action == "hover":
                locator.hover(timeout=self.timeout_ms)
                verified = locator.evaluate("el => !!(el.matches(':hover') || el.contains(document.activeElement))")
            elif action == "double_click":
                locator.dblclick(timeout=self.timeout_ms)
                verified = True
            elif action == "press":
                allowed_keys = {"Enter", "Escape", "Tab", "Space", "ArrowUp", "ArrowDown",
                                "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown",
                                "Backspace", "Delete"}
                if key not in allowed_keys and not (isinstance(key, str) and len(key) == 1):
                    raise ValueError(f"Unsupported key {key!r}.")
                locator.press(key, timeout=self.timeout_ms)
                verified = True
            elif action == "upload":
                if not path:
                    raise ValueError("upload requires path to an existing local file.")
                from pathlib import Path
                file_path = Path(path).expanduser().resolve(strict=True)
                if not file_path.is_file():
                    raise ValueError("Upload path must be a file.")
                locator.set_input_files(str(file_path), timeout=self.timeout_ms)
                files = locator.evaluate("el => Array.from(el.files || []).map(f => f.name)")
                verified = file_path.name in files
                if not verified:
                    raise RuntimeError("Upload was attempted but the selected filename could not be verified.")
                return {"ok": True, "action": action, "path": str(file_path),
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
            self.page.evaluate("(delta) => window.scrollBy(0, delta)", amount if direction == "down" else -amount)
            return {"ok": True, "action": action, "direction": direction, "amount": amount,
                    "verified": True, "url": self.page.url}
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
