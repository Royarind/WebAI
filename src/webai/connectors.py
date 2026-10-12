"""Read-only cross-application connectors for WebAI.

Local files are confined to explicitly configured roots. Outlook access uses a
pre-authorized Microsoft Graph bearer token supplied by the user; this module
does not collect passwords or perform OAuth sign-in itself. All connectors are
read-only in this initial integration.
"""
from __future__ import annotations

import csv
import json
import os
import re
from pathlib import Path
from typing import Any

import requests


TEXT_EXTENSIONS = {".txt", ".md", ".rst", ".log", ".json", ".csv", ".yaml", ".yml", ".xml", ".html"}
DEFAULT_IGNORES = {".git", ".venv", "venv", "node_modules", "__pycache__", "AppData", "Windows", "Program Files"}


def _configured_roots() -> list[Path]:
    raw = os.getenv("WEBAI_FILE_ROOTS", "").strip()
    if not raw:
        return []
    roots = []
    for item in raw.split(os.pathsep):
        item = item.strip().strip('"')
        if item:
            try:
                root = Path(item).expanduser().resolve()
                if root.exists() and root.is_dir():
                    roots.append(root)
            except OSError:
                continue
    return roots


class LocalFileConnector:
    """Search and read files inside WEBAI_FILE_ROOTS only."""

    def __init__(self, roots: list[str | Path] | None = None, *, max_file_bytes: int = 1_000_000):
        configured = [Path(root).expanduser().resolve() for root in roots] if roots is not None else _configured_roots()
        self.roots = [root for root in configured if root.exists() and root.is_dir()]
        self.max_file_bytes = max(1024, int(max_file_bytes))

    @property
    def available(self) -> bool:
        return bool(self.roots)

    def snapshot(self) -> dict[str, Any]:
        return {"available": self.available, "roots": [str(root) for root in self.roots],
                "read_only": True, "policy": "Only configured roots are searchable; files are never modified."}

    def _inside_roots(self, path: Path) -> bool:
        try:
            resolved = path.resolve()
            return any(resolved == root or root in resolved.parents for root in self.roots)
        except (OSError, RuntimeError):
            return False

    def search(self, query: str, *, limit: int = 10, extensions: list[str] | None = None) -> dict[str, Any]:
        query = str(query or "").strip()
        if not query:
            return {"ok": False, "error": "A non-empty search query is required.", "results": []}
        if not self.roots:
            return {"ok": False, "error": "Local file search is not configured. Set WEBAI_FILE_ROOTS to one or more permitted folders.", "results": []}
        allowed = {ext.lower() if ext.startswith(".") else "." + ext.lower() for ext in extensions} if extensions else TEXT_EXTENSIONS
        terms = [term for term in re.findall(r"[\w.-]{2,}", query.lower())]
        results = []
        visited = 0
        for root in self.roots:
            for folder, dirs, files in os.walk(root, followlinks=False):
                dirs[:] = [name for name in dirs if name not in DEFAULT_IGNORES]
                for filename in files:
                    path = Path(folder) / filename
                    if path.suffix.lower() not in allowed or not self._inside_roots(path):
                        continue
                    try:
                        if path.stat().st_size > self.max_file_bytes:
                            continue
                        text = path.read_text(encoding="utf-8", errors="replace")
                    except (OSError, PermissionError):
                        continue
                    visited += 1
                    lower = text.lower()
                    hits = sum(lower.count(term) for term in terms)
                    name_hits = sum(path.name.lower().count(term) for term in terms)
                    if hits or name_hits:
                        results.append({"path": str(path), "name": path.name, "match_count": hits + name_hits,
                                        "snippet": self._snippet(text, terms), "size_bytes": path.stat().st_size})
                        results.sort(key=lambda item: item["match_count"], reverse=True)
                        results = results[:max(1, min(int(limit), 50))]
        return {"ok": True, "query": query, "roots": [str(root) for root in self.roots],
                "files_scanned": visited, "count": len(results), "results": results}

    @staticmethod
    def _snippet(text: str, terms: list[str], max_chars: int = 420) -> str:
        lines = text.splitlines()
        for line in lines:
            if any(term in line.lower() for term in terms):
                return line.strip()[:max_chars]
        return text.strip().replace("\n", " ")[:max_chars]

    def read(self, file_path: str, *, max_chars: int = 12000) -> dict[str, Any]:
        try:
            path = Path(file_path).expanduser().resolve(strict=True)
        except (OSError, RuntimeError):
            return {"ok": False, "error": "File does not exist or cannot be resolved."}
        if not self._inside_roots(path):
            return {"ok": False, "error": "Access denied: file is outside configured WEBAI_FILE_ROOTS."}
        if not path.is_file():
            return {"ok": False, "error": "The requested path is not a file."}
        if path.suffix.lower() not in TEXT_EXTENSIONS:
            return {"ok": False, "error": f"Unsupported file type {path.suffix!r}; supported types: {', '.join(sorted(TEXT_EXTENSIONS))}."}
        try:
            if path.stat().st_size > self.max_file_bytes:
                return {"ok": False, "error": f"File exceeds the {self.max_file_bytes}-byte read limit."}
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return {"ok": False, "error": f"Unable to read file: {exc}"}
        return {"ok": True, "path": str(path), "text": text[:max(1, min(int(max_chars), 50000))],
                "truncated": len(text) > max_chars, "characters": len(text)}


class OutlookGraphConnector:
    """Read-only Microsoft Graph email search using a pre-authorized access token."""

    BASE_URL = "https://graph.microsoft.com/v1.0"

    def __init__(self, access_token: str | None = None, *, timeout: float = 20):
        self.access_token = (access_token if access_token is not None else os.getenv("WEBAI_OUTLOOK_ACCESS_TOKEN", "")).strip()
        self.timeout = max(3, min(float(timeout), 60))

    @property
    def available(self) -> bool:
        return bool(self.access_token)

    def snapshot(self) -> dict[str, Any]:
        return {"available": self.available, "provider": "Microsoft Graph",
                "read_only": True, "scopes_expected": ["Mail.Read"],
                "configuration": "Set WEBAI_OUTLOOK_ACCESS_TOKEN to a valid Graph access token with Mail.Read consent."}

    def search_messages(self, query: str, *, limit: int = 10, unread_only: bool = False) -> dict[str, Any]:
        query = str(query or "").strip()
        if not query:
            return {"ok": False, "error": "A non-empty Outlook search query is required.", "messages": []}
        if not self.available:
            return {"ok": False, "error": "Outlook is not configured. Supply WEBAI_OUTLOOK_ACCESS_TOKEN with delegated Mail.Read permission.", "messages": []}
        top = max(1, min(int(limit), 25))
        # Graph $search supports quoted terms; use query parameters rather than string URL concatenation.
        params = {"$search": '"' + query.replace('"', ' ').replace("\r", " ").replace("\n", " ") + '"',
                  "$top": str(top),
                  "$select": "id,subject,from,receivedDateTime,bodyPreview,isRead,webLink,importance"}
        if unread_only:
            params["$filter"] = "isRead eq false"
        headers = {"Authorization": f"Bearer {self.access_token}", "ConsistencyLevel": "eventual"}
        try:
            response = requests.get(f"{self.BASE_URL}/me/messages", params=params, headers=headers, timeout=self.timeout)
            if response.status_code in (401, 403):
                return {"ok": False, "error": f"Microsoft Graph denied access (HTTP {response.status_code}). Refresh the token and confirm Mail.Read consent.", "messages": []}
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            return {"ok": False, "error": f"Outlook search failed: {exc}", "messages": []}
        messages = []
        for item in payload.get("value", []):
            sender = item.get("from", {}).get("emailAddress", {}) or {}
            messages.append({
                "id": item.get("id"), "subject": item.get("subject", ""),
                "sender": sender.get("name", ""), "sender_email": sender.get("address", ""),
                "received": item.get("receivedDateTime"), "preview": item.get("bodyPreview", ""),
                "is_read": item.get("isRead"), "importance": item.get("importance"),
                "web_link": item.get("webLink"),
            })
        return {"ok": True, "query": query, "count": len(messages), "messages": messages, "read_only": True}
