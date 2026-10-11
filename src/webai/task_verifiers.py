"""Deterministic, task-specific browser outcome verifiers.

These checks use the live DOM rather than trusting a model's completion statement.
They are conservative: inconclusive evidence returns verified=False.
"""
from __future__ import annotations

from typing import Any
import time


SUPPORTED_VERIFIERS = {"text_present", "selected_option", "cart_contains"}


def _verify_task_outcome_once(page: Any, verifier: str, target: str) -> dict:
    """Run a named verification check against the live page.

    - text_present: target phrase is present in rendered page text.
    - selected_option: target phrase appears in a control with selected/checked state.
    - cart_contains: target phrase appears in a cart/bag/basket region, or on a cart URL.
    """
    target = (target or "").strip()
    if verifier not in SUPPORTED_VERIFIERS:
        return {
            "verified": False,
            "verifier": verifier,
            "reason": f"Unsupported task-specific verifier: {verifier!r}.",
        }
    if not target:
        return {"verified": False, "verifier": verifier, "reason": "Verification target is empty."}

    try:
        result = page.evaluate(
            """({kind, target}) => {
              const norm = s => (s || '').replace(/\\s+/g, ' ').trim().toLowerCase();
              const needle = norm(target);
              const textOf = el => norm([
                el.innerText || '', el.value || '',
                el.getAttribute('aria-label') || '',
                el.getAttribute('title') || '',
                el.getAttribute('data-color') || '',
                el.getAttribute('data-colour') || '',
                el.getAttribute('data-testid') || ''
              ].join(' '));
              const visible = el => {
                const r = el.getBoundingClientRect();
                const s = getComputedStyle(el);
                return r.width > 0 && r.height > 0 &&
                  s.display !== 'none' && s.visibility !== 'hidden' &&
                  Number(s.opacity || 1) > 0;
              };
              if (kind === 'text_present') {
                const body = norm(document.body?.innerText || '');
                return {verified: body.includes(needle), evidence: body.includes(needle) ? target : ''};
              }
              if (kind === 'selected_option') {
                const selected = Array.from(document.querySelectorAll(
                  '[aria-checked=true],[aria-selected=true],[aria-pressed=true],' +
                  'input:checked,option:checked,[data-selected=true],[data-state=selected],' +
                  '.selected,.is-selected,.active'
                )).filter(visible);
                const matches = selected.filter(el => textOf(el).includes(needle));
                return {
                  verified: matches.length > 0,
                  evidence: matches.slice(0, 5).map(textOf),
                  selected_count: selected.length
                };
              }
              if (kind === 'cart_contains') {
                const regions = Array.from(document.querySelectorAll(
                  '[role=dialog],aside,[aria-label],[title],[data-testid],[id],[class]'
                )).filter(visible).filter(el => {
                  const meta = norm([
                    el.getAttribute('aria-label') || '', el.getAttribute('title') || '',
                    el.getAttribute('data-testid') || '', el.id || '',
                    typeof el.className === 'string' ? el.className : ''
                  ].join(' '));
                  return /cart|bag|basket|shopping/.test(meta);
                });
                const unique = Array.from(new Set(regions));
                const matches = unique.filter(el => norm(el.innerText || '').includes(needle));
                const isCartUrl = /\\/(cart|bag|basket)(\\/|$|\\?)/i.test(location.pathname + location.search);
                const body = norm(document.body?.innerText || '');
                const bodyMatch = isCartUrl && body.includes(needle);
                return {
                  verified: matches.length > 0 || bodyMatch,
                  evidence: matches.slice(0, 5).map(el => (el.innerText || '').slice(0, 500)),
                  cart_url_match: bodyMatch,
                  region_count: unique.length
                };
              }
              return {verified:false, reason:'Unsupported verifier.'};
            }""",
            {"kind": verifier, "target": target},
        )
        return {"verifier": verifier, "target": target, **(result or {"verified": False})}
    except Exception as exc:
        return {
            "verified": False,
            "verifier": verifier,
            "target": target,
            "reason": f"{type(exc).__name__}: {exc}",
        }


def verify_task_outcome(
    page: Any,
    verifier: str,
    target: str,
    *,
    timeout_ms: int = 1200,
    interval_ms: int = 100,
) -> dict:
    """Poll a task-specific verifier briefly to allow asynchronous UI updates.

    The verifier is re-evaluated against the live DOM until it succeeds or the
    bounded timeout expires. It never repeats the user action.
    """
    if verifier not in SUPPORTED_VERIFIERS or not (target or "").strip():
        return _verify_task_outcome_once(page, verifier, target)

    timeout_ms = max(0, int(timeout_ms))
    interval_ms = max(10, int(interval_ms))
    deadline = time.monotonic() + timeout_ms / 1000
    last = _verify_task_outcome_once(page, verifier, target)
    while not last.get("verified") and time.monotonic() < deadline:
        remaining_ms = max(0, int((deadline - time.monotonic()) * 1000))
        if remaining_ms <= 0:
            break
        try:
            page.wait_for_timeout(min(interval_ms, remaining_ms))
        except Exception:
            break
        last = _verify_task_outcome_once(page, verifier, target)
    last["polling"] = {
        "timeout_ms": timeout_ms,
        "interval_ms": interval_ms,
        "verified_after_polling": bool(last.get("verified")),
    }
    return last
