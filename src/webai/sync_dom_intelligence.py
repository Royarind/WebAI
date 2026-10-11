"""Synchronous DOM-intelligence fallback for WebAI's sync Playwright action layer.

This complements the async DOMIntelligence module without mixing Playwright APIs.
It only resolves a candidate; it never clicks or retries an action itself.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


INTERACTIVE = "button, a, input, select, textarea, [role], [tabindex], [onclick], [aria-label], label"


def _tokens(text: str) -> set[str]:
    return {t for t in re.findall(r"[a-z0-9]+", (text or "").lower()) if len(t) > 1}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").lower()).strip()


@dataclass
class SyncCandidate:
    frame: Any
    locator: Any
    score: float
    evidence: dict


class SyncDOMIntelligence:
    """Find a unique, visible, enabled element matching a natural-language intent."""

    def __init__(self, page, *, max_candidates: int = 120):
        self.page = page
        self.max_candidates = max_candidates
        self.diagnostics: dict = {}

    def resolve(self, intent: str):
        wanted = _tokens(intent)
        candidates: list[SyncCandidate] = []
        frame_errors = []
        for frame_index, frame in enumerate(self.page.frames):
            try:
                nodes = frame.locator(INTERACTIVE)
                count = min(nodes.count(), self.max_candidates)
                for i in range(count):
                    node = nodes.nth(i)
                    try:
                        if not node.is_visible() or not node.is_enabled():
                            continue
                        evidence = {
                            "tag": node.evaluate("(e) => e.tagName.toLowerCase()"),
                            "text": (node.inner_text(timeout=400) or "")[:180],
                            "aria_label": node.get_attribute("aria-label") or "",
                            "title": node.get_attribute("title") or "",
                            "test_id": node.get_attribute("data-testid") or node.get_attribute("data-test") or "",
                            "value": node.get_attribute("value") or "",
                            "name": node.get_attribute("name") or "",
                            "role": node.get_attribute("role") or "",
                        }
                        # Include nearby label/container context for swatches and custom controls.
                        try:
                            evidence["context"] = node.evaluate(
                                "(e) => (e.labels ? Array.from(e.labels).map(x=>x.innerText).join(' ') : '') + ' ' + (e.parentElement?.innerText || '')"
                            )[:220]
                        except Exception:
                            evidence["context"] = ""
                        hay = _tokens(" ".join(str(v) for v in evidence.values()))
                        overlap = len(wanted & hay) / max(1, len(wanted))
                        score = overlap * 10
                        target = _norm(intent)
                        for field, weight in (("aria_label", 7), ("text", 5), ("title", 4), ("test_id", 3), ("context", 3), ("value", 3)):
                            value = _norm(str(evidence.get(field, "")))
                            if target and target in value:
                                score += weight
                        # The accessible text can be shorter than the natural-language intent.
                        # A near-exact token match is acceptable, but ties are rejected below.
                        if overlap >= 0.5:
                            candidates.append(SyncCandidate(frame, node, score, {
                                "frame_index": frame_index, **evidence, "token_overlap": round(overlap, 3)
                            }))
                    except Exception:
                        continue
            except Exception as exc:
                frame_errors.append({"frame_url": frame.url, "error": f"{type(exc).__name__}: {exc}"})

        candidates.sort(key=lambda c: c.score, reverse=True)
        self.diagnostics = {
            "intent": intent,
            "frame_errors": frame_errors,
            "candidates": [c.evidence | {"score": c.score} for c in candidates[:10]],
        }
        if not candidates:
            raise LookupError(f"DOM intelligence found no visible candidate for intent {intent!r}.")
        # Do not guess if the top two candidates have equal evidence.
        if len(candidates) > 1 and candidates[0].score == candidates[1].score:
            raise ValueError(f"DOM intelligence found ambiguous candidates for {intent!r}.")
        return candidates[0].locator, self.diagnostics
