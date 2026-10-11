"""Deterministic checks for planner-provided completion evidence."""
from __future__ import annotations

import re
from typing import Any

_STOP = {
    "the", "and", "that", "this", "with", "from", "into", "for", "was",
    "were", "are", "is", "has", "have", "been", "being", "page", "visible",
    "shown", "shows", "displayed", "evidence", "verified", "verification",
    "selected", "successfully", "requested", "item", "state", "element",
}


def _tokens(value: str) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", (value or "").lower())
        if len(token) > 1 and token not in _STOP
    }


def collect_observable_state(page: Any) -> str:
    """Collect rendered text and common selected-state attributes from the live page."""
    return page.evaluate(
        """() => {
          const body = document.body?.innerText || '';
          const stateNodes = Array.from(document.querySelectorAll(
            '[aria-checked=true],[aria-selected=true],[aria-pressed=true],' +
            'input:checked,option:checked,[data-selected=true],[data-state=selected]'
          )).slice(0, 100).map(el => [
            el.tagName, el.innerText || '', el.value || '',
            el.getAttribute('aria-label') || '',
            el.getAttribute('title') || '',
            el.getAttribute('data-testid') || '',
            el.getAttribute('data-color') || '',
            el.getAttribute('data-colour') || '',
            el.getAttribute('aria-checked') || '',
            el.getAttribute('aria-selected') || '',
            el.getAttribute('aria-pressed') || '',
            String(el.className || '')
          ].join(' '));
          const labels = Array.from(document.querySelectorAll(
            '[aria-label],[title],[data-testid],[data-color],[data-colour]'
          )).slice(0, 200).map(el => [
            el.getAttribute('aria-label') || '',
            el.getAttribute('title') || '',
            el.getAttribute('data-testid') || '',
            el.getAttribute('data-color') || '',
            el.getAttribute('data-colour') || ''
          ].join(' '));
          return [
            location.href, document.title, body.slice(0, 12000),
            ...stateNodes, ...labels
          ].join(' ');
        }"""
    )


def verify_finish_evidence(page: Any, evidence: str) -> dict:
    """Check that a finish claim's meaningful terms are present in live UI evidence.

    This is a lexical grounding check, not proof of arbitrary business semantics.
    It is deliberately conservative and returns diagnostics instead of raising.
    """
    evidence = (evidence or "").strip()
    if not evidence:
        return {"verified": False, "reason": "No verification evidence was supplied."}
    try:
        observed = collect_observable_state(page)
    except Exception as exc:
        return {
            "verified": False,
            "reason": f"Could not read live page state: {type(exc).__name__}: {exc}",
        }

    phrase = re.sub(r"\s+", " ", evidence).strip().lower()
    observed_norm = re.sub(r"\s+", " ", observed).strip().lower()
    if phrase and phrase in observed_norm:
        return {"verified": True, "method": "exact_phrase", "evidence": evidence}

    expected = _tokens(evidence)
    actual = _tokens(observed)
    if len(expected) < 2:
        return {
            "verified": False,
            "reason": "Evidence is too generic to ground against the current page.",
            "matched_terms": sorted(expected & actual),
        }
    matched = expected & actual
    coverage = len(matched) / len(expected)
    verified = len(matched) >= 2 and coverage >= 0.6
    return {
        "verified": verified,
        "method": "term_overlap",
        "coverage": round(coverage, 3),
        "matched_terms": sorted(matched),
        "missing_terms": sorted(expected - actual),
        "reason": (
            "Evidence terms were found in the live page state."
            if verified else
            "The live page does not contain enough of the claimed evidence."
        ),
    }
