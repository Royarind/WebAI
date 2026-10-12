"""Platform-neutral computer-use tools, kept separate from browser automation.

Filesystem operations use native Python APIs. Optional PyAutoGUI provides visual
mouse/keyboard/screenshot control on Windows, macOS and Linux. Destructive
operations are approval-gated and never execute from a bare request.
"""
from __future__ import annotations

import os
import platform
import shutil
import time
import uuid
from pathlib import Path
from typing import Any

try:
    import pyautogui  # type: ignore
except ImportError:  # optional dependency; filesystem tools remain available
    pyautogui = None


class ComputerUse:
    """Local computer tools across accessible filesystem locations.

    OS permissions still apply. Delete operations require separate explicit approval.
    """

    def __init__(self, roots: list[str | Path] | None = None, *, event_sink=None):
        # Optional WEBAI_FILE_ROOTS narrows search roots; otherwise discover all drives.
        raw = roots if roots is not None else [
            item.strip().strip('"')
            for item in os.getenv("WEBAI_FILE_ROOTS", "").split(os.pathsep)
            if item.strip()
        ]
        if roots is None and not raw:
            if os.name == "nt":
                import string
                raw = [f"{drive}:\\" for drive in string.ascii_uppercase
                       if os.path.exists(f"{drive}:\\")]
            else:
                raw = ["/"]
        self.roots = [Path(item).expanduser().resolve() for item in raw
                      if Path(item).expanduser().exists() and Path(item).expanduser().is_dir()]
        self.event_sink = event_sink
        self.pending_approvals: dict[str, dict[str, Any]] = {}

    def _event(self, kind: str, **data):
        event = {"timestamp": time.time(), "kind": kind, **data}
        if self.event_sink:
            self.event_sink(event)
        return event

    def capabilities(self) -> dict[str, Any]:
        return {
            "platform": platform.system(),
            "filesystem": True,
            "visual_control": pyautogui is not None,
            "roots": [str(root) for root in self.roots],
            "operations": ["search", "read", "copy", "move", "create_directory",
                           "create_text_file", "delete_with_approval", "screenshot",
                           "mouse", "keyboard", "hotkey", "clipboard"],
        }

    def _resolve(self, value: str | Path, *, allow_missing: bool = False) -> Path:
        path = Path(value).expanduser()
        # Relative paths resolve from the current working directory. Absolute paths
        # can target any drive/folder; normal OS permissions remain in force.
        if not path.is_absolute():
            path = Path.cwd() / path
        return path.resolve(strict=not allow_missing)

    def live_search_in_explorer(self, query: str) -> dict[str, Any]:
        """Visibly open Windows Explorer and initiate a This PC search."""
        if platform.system() != "Windows":
            return {"ok": False, "available": False, "reason": "Live Explorer interaction is Windows-only; filesystem search remains available."}
        gui = self._gui()
        query = str(query or "").strip()
        if not query or len(query) > 160:
            raise ValueError("Search query must contain 1–160 characters.")
        self._event("computer_step", message="Opening Windows File Explorer", action="open_explorer")
        gui.hotkey("win", "e")
        time.sleep(1.2)
        self._event("computer_step", message="Navigating Explorer to This PC", action="navigate_this_pc")
        gui.hotkey("ctrl", "l")
        gui.write("This PC", interval=0.06)
        gui.press("enter")
        time.sleep(1.4)
        self._event("computer_step", message=f"Searching This PC for: {query}", action="search_this_pc", query=query)
        gui.hotkey("ctrl", "e")
        gui.write(query, interval=0.04)
        gui.press("enter")
        time.sleep(1.0)
        self._event("computer_step", message="Search submitted in visible File Explorer", action="search_submitted", query=query)
        return {"ok": True, "available": True, "visible": True, "query": query, "note": "Explorer search was initiated; results should be visually checked in the open Explorer window."}
    def search(self, query: str, *, limit: int = 30) -> dict[str, Any]:
        query = str(query or "").strip().lower()
        if not query:
            raise ValueError("Search query cannot be empty.")
        results, scanned = [], 0
        for root in self.roots:
            for folder, dirs, files in os.walk(root, followlinks=False, onerror=lambda _error: None):
                # Avoid following symlinks while searching across broad filesystem roots.
                dirs[:] = [d for d in dirs if not (Path(folder) / d).is_symlink()]
                for name in files:
                    path = Path(folder) / name
                    if path.is_symlink():
                        continue
                    scanned += 1
                    name_match = query in name.lower()
                    snippet = ""
                    if path.suffix.lower() in {".txt", ".md", ".rst", ".log", ".json", ".csv", ".yaml", ".yml", ".xml", ".html", ".py", ".ini", ".toml"}:
                        try:
                            if path.stat().st_size <= 1_000_000:
                                text = path.read_text(encoding="utf-8", errors="replace")
                                lines = [line.strip() for line in text.splitlines() if query in line.lower()]
                                if lines:
                                    snippet = lines[0][:400]
                        except OSError:
                            pass
                    if name_match or snippet:
                        results.append({"path": str(path), "name": name, "snippet": snippet})
                        if len(results) >= max(1, min(int(limit), 100)):
                            self._event("file_search_complete", query=query, scanned=scanned, count=len(results), capped=True)
                            return {"ok": True, "query": query, "roots": [str(r) for r in self.roots],
                                    "files_scanned": scanned, "count": len(results), "results": results}
        self._event("file_search_complete", query=query, scanned=scanned, count=len(results), capped=False)
        return {"ok": True, "query": query, "roots": [str(r) for r in self.roots],
                "files_scanned": scanned, "count": len(results), "results": results}

    def read(self, path: str, *, max_chars: int = 20000) -> dict[str, Any]:
        target = self._resolve(path)
        if not target.is_file():
            raise ValueError("Read target must be a file.")
        if target.stat().st_size > 2_000_000:
            raise ValueError("File exceeds the 2 MB read limit.")
        text = target.read_text(encoding="utf-8", errors="replace")
        self._event("file_read", path=str(target), characters=min(len(text), max_chars))
        return {"ok": True, "path": str(target), "text": text[:max(1, min(int(max_chars), 100000))],
                "truncated": len(text) > max_chars}

    def copy(self, source: str, destination: str) -> dict[str, Any]:
        src = self._resolve(source)
        dst = self._resolve(destination, allow_missing=True)
        if not src.exists():
            raise FileNotFoundError(str(src))
        if dst.exists():
            raise FileExistsError("Destination already exists; choose another path to avoid accidental overwrite.")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst) if src.is_file() else shutil.copytree(src, dst)
        self._event("file_copied", source=str(src), destination=str(dst))
        return {"ok": True, "source": str(src), "destination": str(dst)}

    def move(self, source: str, destination: str) -> dict[str, Any]:
        src = self._resolve(source)
        dst = self._resolve(destination, allow_missing=True)
        if not src.exists():
            raise FileNotFoundError(str(src))
        if dst.exists():
            raise FileExistsError("Destination already exists; choose another path to avoid accidental overwrite.")
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        self._event("file_moved", source=str(src), destination=str(dst))
        return {"ok": True, "source": str(src), "destination": str(dst)}

    def create_directory(self, path: str) -> dict[str, Any]:
        target = self._resolve(path, allow_missing=True)
        target.mkdir(parents=True, exist_ok=False)
        self._event("directory_created", path=str(target))
        return {"ok": True, "path": str(target)}

    def create_text_file(self, path: str, content: str, *, overwrite: bool = False) -> dict[str, Any]:
        target = self._resolve(path, allow_missing=True)
        if target.exists() and not overwrite:
            raise FileExistsError("File already exists; explicit overwrite approval is required.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(content), encoding="utf-8")
        self._event("file_created" if not overwrite else "file_overwritten", path=str(target))
        return {"ok": True, "path": str(target), "characters": len(str(content))}

    def request_delete(self, path: str) -> dict[str, Any]:
        target = self._resolve(path)
        if not target.exists():
            raise FileNotFoundError(str(target))
        if target == Path(target.anchor):
            raise PermissionError("Deleting a filesystem or drive root is not allowed.")
        token = uuid.uuid4().hex
        self.pending_approvals[token] = {"operation": "delete", "path": str(target)}
        self._event("approval_required", operation="delete", path=str(target), approval_id=token)
        return {"ok": False, "approval_required": True, "approval_id": token,
                "operation": "delete", "path": str(target),
                "message": "Nothing was deleted. Explicit user approval is required."}

    def approve_delete(self, approval_id: str, *, approved: bool) -> dict[str, Any]:
        request = self.pending_approvals.pop(str(approval_id), None)
        if not request or request.get("operation") != "delete":
            raise ValueError("Unknown or already used approval ID.")
        if not approved:
            self._event("operation_rejected", operation="delete", path=request["path"])
            return {"ok": True, "deleted": False, "cancelled": True}
        target = self._resolve(request["path"])
        if target == Path(target.anchor):
            raise PermissionError("Deleting a filesystem or drive root is not allowed.")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
        self._event("operation_approved_and_completed", operation="delete", path=str(target))
        return {"ok": True, "deleted": True, "path": str(target)}

    def _gui(self):
        if pyautogui is None:
            raise RuntimeError("Visual desktop control is not installed. Install the computer-use extra for this OS.")
        return pyautogui

    def screenshot(self, path: str | None = None) -> dict[str, Any]:
        gui = self._gui()
        image = gui.screenshot()
        if path:
            target = self._resolve(path, allow_missing=True)
            target.parent.mkdir(parents=True, exist_ok=True)
            image.save(str(target))
            result = {"ok": True, "path": str(target), "width": image.width, "height": image.height}
        else:
            result = {"ok": True, "width": image.width, "height": image.height}
        self._event("desktop_screenshot", **result)
        return result

    def desktop_action(self, action: str, **kwargs) -> dict[str, Any]:
        gui = self._gui()
        # Deliberately narrow allowlist; callers cannot invoke arbitrary Python or shell commands.
        if action == "click":
            gui.click(x=int(kwargs["x"]), y=int(kwargs["y"]), clicks=max(1, min(int(kwargs.get("clicks", 1)), 2)))
        elif action == "move":
            gui.moveTo(int(kwargs["x"]), int(kwargs["y"]), duration=0.15)
        elif action == "press":
            gui.press(str(kwargs["key"]))
        elif action == "hotkey":
            keys = kwargs.get("keys")
            if not isinstance(keys, list) or not 1 <= len(keys) <= 4:
                raise ValueError("hotkey keys must be a list of 1–4 keys.")
            gui.hotkey(*[str(key) for key in keys])
        elif action == "type":
            text = str(kwargs.get("text", ""))
            if len(text) > 5000:
                raise ValueError("Text input is limited to 5000 characters per action.")
            gui.write(text, interval=0.01)
        else:
            raise ValueError(f"Unsupported desktop action: {action}")
        self._event("desktop_action", action=action, arguments={k: v for k, v in kwargs.items() if k != "text"})
        return {"ok": True, "action": action, "platform": platform.system(),
                "note": "Visual action executed; inspect the screen and verify its outcome."}
