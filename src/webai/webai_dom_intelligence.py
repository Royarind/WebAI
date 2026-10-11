"""DOM traversal, candidate ranking, safe interaction and validation for Playwright.

This module deliberately prefers observable evidence over blind selector retries.
It supports regular DOM, open shadow roots, and Playwright-accessible frames.
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Awaitable, Callable, Optional

from playwright.async_api import Page, Locator, Frame, TimeoutError as PlaywrightTimeoutError


CONSEQUENTIAL_RE = re.compile(
    r"\b(buy now|add to bag|add to cart|checkout|place order|pay now|purchase|"
    r"submit order|confirm booking|delete|remove account|send payment)\b", re.I
)
INTERACTIVE_SELECTOR = (
    "button, a, input, select, textarea, [role], [tabindex], "
    "[onclick], [data-testid], [aria-label], label"
)


@dataclass
class Candidate:
    frame_index: int
    selector: str
    tag: str
    role: str
    name: str
    text: str
    aria_label: str
    title: str
    test_id: str
    classes: str
    visible: bool
    enabled: bool
    checked: Optional[bool]
    selected: Optional[bool]
    rect: dict[str, float]
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)


@dataclass
class Attempt:
    candidate: dict[str, Any]
    clicked: bool
    validated: bool
    error: Optional[str] = None


class DOMIntelligence:
    def __init__(
        self,
        page: Page,
        *,
        max_candidates: int = 80,
        max_attempts: int = 5,
        action_timeout_ms: int = 2500,
    ):
        self.page = page
        self.max_candidates = max_candidates
        self.max_attempts = max_attempts
        self.action_timeout_ms = action_timeout_ms
        self.last_diagnostics: dict[str, Any] = {}

    async def inspect(self, intent: str = "") -> list[Candidate]:
        """Inspect interactive nodes at every DOM depth and collect context."""
        all_candidates: list[Candidate] = []
        frames = list(self.page.frames)
        for frame_index, frame in enumerate(frames):
            try:
                raw = await frame.evaluate(
                    """(selector) => {
                      const norm = s => (s || '').replace(/\\\\s+/g, ' ').trim();
                      const visible = el => {
                        const r = el.getBoundingClientRect();
                        const cs = getComputedStyle(el);
                        return r.width > 0 && r.height > 0 &&
                          cs.visibility !== 'hidden' && cs.display !== 'none' &&
                          Number(cs.opacity || 1) > 0;
                      };
                      const nameOf = el => {
                        const labelled = el.getAttribute('aria-label') ||
                          el.getAttribute('title') ||
                          el.getAttribute('alt') ||
                          el.getAttribute('placeholder') || '';
                        const ids = (el.getAttribute('aria-labelledby') || '').split(/\\\\s+/).filter(Boolean);
                        const labelText = ids.map(id => document.getElementById(id)?.innerText || '').join(' ');
                        let labels = '';
                        try { labels = Array.from(el.labels || []).map(x => x.innerText).join(' '); } catch {}
                        return norm([labelled, labelText, labels, el.innerText, el.value].filter(Boolean).join(' ')).slice(0, 300);
                      };
                      const nodes = [];
                      const seen = new Set();
                      const visit = root => {
                        let list = [];
                        try { list = root.querySelectorAll(selector); } catch {}
                        for (const el of list) {
                          if (seen.has(el)) continue;
                          seen.add(el);
                          const r = el.getBoundingClientRect();
                          const tag = el.tagName.toLowerCase();
                          const role = el.getAttribute('role') || (
                            tag === 'button' ? 'button' :
                            tag === 'a' ? 'link' :
                            tag === 'input' ? (el.type || 'input') :
                            tag === 'select' ? 'combobox' : ''
                          );
                          let checked = null, selected = null;
                          if ('checked' in el) checked = !!el.checked;
                          if (el.getAttribute('aria-checked') != null) checked = el.getAttribute('aria-checked') === 'true';
                          if (el.getAttribute('aria-pressed') != null) selected = el.getAttribute('aria-pressed') === 'true';
                          if (el.getAttribute('aria-selected') != null) selected = el.getAttribute('aria-selected') === 'true';
                          const classes = typeof el.className === 'string' ? el.className : '';
                          nodes.push({
                            tag, role, name: nameOf(el), text: norm(el.innerText).slice(0, 240),
                            aria_label: el.getAttribute('aria-label') || '',
                            title: el.getAttribute('title') || '',
                            test_id: el.getAttribute('data-testid') || el.getAttribute('data-test') || '',
                            classes: norm(classes).slice(0, 200),
                            visible: visible(el),
                            enabled: !el.disabled && el.getAttribute('aria-disabled') !== 'true',
                            checked, selected,
                            rect: {x: r.x, y: r.y, width: r.width, height: r.height},
                            id: el.id || '',
                            name_attr: el.getAttribute('name') || '',
                            type: el.getAttribute('type') || '',
                            value: ('value' in el ? String(el.value || '') : ''),
                            depth: (() => { let d=0, n=el; while(n && n.parentElement){d++; n=n.parentElement;} return d; })(),
                            parent: norm(el.parentElement?.innerText || '').slice(0, 200),
                            outer: el.outerHTML.slice(0, 500)
                          });
                          // Recursively inspect open shadow roots.
                          if (el.shadowRoot) visit(el.shadowRoot);
                        }
                        // Search open shadow roots nested under arbitrary elements too.
                        let descendants = [];
                        try { descendants = root.querySelectorAll('*'); } catch {}
                        for (const el of descendants) if (el.shadowRoot) visit(el.shadowRoot);
                      };
                      visit(document);
                      return nodes;
                    }""",
                    INTERACTIVE_SELECTOR,
                )
                for item in raw:
                    # Build a usable selector, preferring stable attributes.
                    if item.get("test_id"):
                        selector = f'[data-testid="{_css_escape(item["test_id"])}"]'
                    elif item.get("id"):
                        selector = f'#{_css_escape(item["id"])}'
                    elif item.get("name_attr"):
                        selector = f'{item["tag"]}[name="{_css_escape(item["name_attr"])}"]'
                    else:
                        # outerHTML is diagnostic only; use text/role through locator strategy later.
                        selector = item.get("outer", "")[:180]
                    candidate = Candidate(
                        frame_index=frame_index,
                        selector=selector,
                        tag=item["tag"], role=item["role"], name=item["name"],
                        text=item["text"], aria_label=item["aria_label"],
                        title=item["title"], test_id=item["test_id"],
                        classes=item["classes"], visible=item["visible"],
                        enabled=item["enabled"], checked=item["checked"],
                        selected=item["selected"], rect=item["rect"],
                    )
                    candidate.score, candidate.reasons = self._score(candidate, intent, item)
                    all_candidates.append(candidate)
            except Exception as exc:
                self.last_diagnostics.setdefault("frame_inspection_errors", []).append(
                    {"frame_url": frame.url, "error": f"{type(exc).__name__}: {exc}"}
                )
        all_candidates.sort(key=lambda c: (c.score, c.visible, c.enabled), reverse=True)
        return all_candidates[: self.max_candidates]

    @staticmethod
    def _score(c: Candidate, intent: str, raw: dict[str, Any]) -> tuple[float, list[str]]:
        score, reasons = 0.0, []
        q = _tokens(intent)
        hay = _tokens(" ".join([
            c.name, c.text, c.aria_label, c.title, c.test_id, c.classes,
            raw.get("value", ""), raw.get("parent", ""), raw.get("outer", "")
        ]))
        if c.visible:
            score += 2; reasons.append("visible")
        if c.enabled:
            score += 1; reasons.append("enabled")
        if q:
            overlap = len(q & hay) / max(1, len(q))
            score += overlap * 12
            if overlap >= 0.7: reasons.append("strong intent text match")
            elif overlap > 0: reasons.append("partial intent text match")
        # Exact phrase/label is more valuable than class-name coincidence.
        intent_norm = _norm(intent)
        for value, weight, label in [
            (c.aria_label, 8, "aria-label"),
            (c.name, 7, "accessible name"),
            (c.title, 5, "title"),
            (c.text, 4, "visible text"),
            (c.test_id, 3, "test id"),
        ]:
            if intent_norm and intent_norm in _norm(value):
                score += weight
                reasons.append(f"exact intent phrase in {label}")
        if raw.get("tag") in ("button", "input"):
            score += 0.5
        return score, reasons

    async def click_intent(
        self,
        intent: str,
        *,
        authorized: bool = False,
        allow_consequential: bool = False,
        validate: Optional[Callable[[], Any]] = None,
        timeout_ms: Optional[int] = None,
    ) -> dict[str, Any]:
        """Find candidates, click in rank order, and validate after every attempt."""
        if not authorized:
            return {"status": "blocked", "reason": "Interaction not explicitly authorized."}
        if CONSEQUENTIAl := bool(CONSEQUENTIAL_RE.search(intent)):
            if not allow_consequential:
                return {
                    "status": "blocked",
                    "reason": "This intent appears consequential; explicit consequential-action authorization is required.",
                }

        started = time.time()
        timeout = timeout_ms or self.action_timeout_ms
        before = await self._state_fingerprint()
        candidates = await self.inspect(intent)
        attempts: list[Attempt] = []
        attempted_keys: set[tuple[int, str, str]] = set()

        for candidate in candidates:
            if len(attempts) >= self.max_attempts:
                break
            if not candidate.visible or not candidate.enabled or candidate.score < 1.0:
                continue
            key = (candidate.frame_index, candidate.tag, candidate.name or candidate.text)
            if key in attempted_keys:
                continue
            attempted_keys.add(key)
            frame = self.page.frames[candidate.frame_index]
            locator = await self._resolve_candidate(frame, candidate)
            if locator is None:
                attempts.append(Attempt(asdict(candidate), False, False, "Could not safely re-resolve candidate."))
                continue
            try:
                await locator.first.click(timeout=timeout, trial=True)
                await locator.first.click(timeout=timeout)
                await self.page.wait_for_timeout(150)
                validated = await self._validate(before, validate)
                attempts.append(Attempt(asdict(candidate), True, validated))
                if validated:
                    self.last_diagnostics = {
                        "status": "success", "intent": intent,
                        "attempts": [asdict(a) for a in attempts],
                        "elapsed_seconds": round(time.time() - started, 3),
                    }
                    return self.last_diagnostics
                # A click occurred but validation failed. Do not blindly click more
                # candidates if the page transitioned or a consequential state changed.
                after = await self._state_fingerprint()
                if after != before and await self._url_changed_or_dialog():
                    break
            except Exception as exc:
                attempts.append(Attempt(
                    asdict(candidate), False, False, f"{type(exc).__name__}: {exc}"
                ))
                # Refresh candidate snapshot on next iteration if the page mutated.
                continue

        self.last_diagnostics = {
            "status": "failed",
            "intent": intent,
            "reason": "No candidate produced a validated outcome.",
            "attempts": [asdict(a) for a in attempts],
            "top_candidates": [asdict(c) for c in candidates[:12]],
            "elapsed_seconds": round(time.time() - started, 3),
        }
        return self.last_diagnostics

    async def _resolve_candidate(self, frame: Frame, c: Candidate) -> Optional[Locator]:
        # Use stable, user-facing locator methods before CSS.
        try:
            if c.test_id:
                loc = frame.get_by_test_id(c.test_id)
                if await loc.count() == 1:
                    return loc
            if c.aria_label:
                loc = frame.locator(f'[aria-label="{_css_escape(c.aria_label)}"]')
                if await loc.count() == 1:
                    return loc
            if c.tag == "input" and c.name:
                loc = frame.get_by_label(c.name, exact=False)
                if await loc.count() == 1:
                    return loc
            if c.role and c.name:
                try:
                    loc = frame.get_by_role(c.role, name=c.name, exact=True)
                    if await loc.count() == 1:
                        return loc
                except Exception:
                    pass
            if c.title:
                loc = frame.locator(f'[title="{_css_escape(c.title)}"]')
                if await loc.count() == 1:
                    return loc
            if c.selector.startswith("[") or c.selector.startswith("#") or re.match(r"^[a-z]+\[", c.selector):
                loc = frame.locator(c.selector)
                if await loc.count() == 1:
                    return loc
            # Last resort: exact text, constrained to common interactive elements.
            text = (c.name or c.text).strip()
            if text and len(text) < 160:
                for tag in ("button", "[role=button]", "label", "input", "[role=radio]", "[role=option]"):
                    loc = frame.locator(tag).filter(has_text=text)
                    if await loc.count() == 1:
                        return loc
        except Exception:
            return None
        return None

    async def _state_fingerprint(self) -> str:
        try:
            return await self.page.evaluate("""() => JSON.stringify({
              url: location.href,
              title: document.title,
              body: (document.body?.innerText || '').slice(0, 3000),
              selected: Array.from(document.querySelectorAll(
                '[aria-checked=true],[aria-selected=true],[aria-pressed=true],input:checked,option:checked,.selected,.is-selected'
              )).slice(0,80).map(el => ({
                tag: el.tagName, text: (el.innerText || el.value || '').slice(0,120),
                label: el.getAttribute('aria-label'), cls: String(el.className || '').slice(0,120)
              }))
            })""")
        except Exception:
            return f"{self.page.url}|{time.time_ns()}"

    async def _validate(
        self, before: str, validate: Optional[Callable[[], Any]]
    ) -> bool:
        if validate is not None:
            try:
                result = validate()
                if asyncio.iscoroutine(result):
                    result = await result
                return bool(result)
            except Exception:
                return False
        after = await self._state_fingerprint()
        # Default validation is intentionally conservative: a meaningful state
        # change is evidence, but not proof of the precise desired result.
        return after != before

    async def _url_changed_or_dialog(self) -> bool:
        if len(self.page.frames) == 0:
            return True
        try:
            return await self.page.locator('[role=dialog], dialog[open]').count() > 0
        except Exception:
            return False


def _tokens(s: str) -> set[str]:
    return {x for x in re.findall(r"[a-z0-9]+", (s or "").lower()) if len(x) > 1}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").lower()).strip()


def _css_escape(s: str) -> str:
    # Quote escaping for ordinary attribute selectors. CSS.escape would be ideal
    # for arbitrary IDs, but this is sufficient for typical test IDs and labels.
    return (s or "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\a ")


__all__ = ["DOMIntelligence", "Candidate"]
