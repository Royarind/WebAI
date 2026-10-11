"""Deterministic, task-specific browser outcome verifiers.

These checks use the live DOM rather than trusting a model's completion statement.
They are conservative: inconclusive evidence returns verified=False.
"""
from __future__ import annotations

from typing import Any


SUPPORTED_VERIFIERS = {"text_present", "selected_option", "cart_contains"}


def verify_task_outcome(page: Any, verifier: str, target: str) -> dict:
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
