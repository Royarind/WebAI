"""Deterministic human-intervention detection for WebAI.

This module classifies blockers; it never attempts to bypass CAPTCHAs, MFA,
authentication, browser permissions, or other access controls.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse


CATEGORIES = {
    "captcha_challenge", "authentication_required", "contact_input_required",
    "modal_intervention", "agent_stuck", "user_input_required",
    "approval_required", "browser_blocked",
}

_CAPTCHA = re.compile(
    r"captcha|recaptcha|hcaptcha|verify you are human|checking your browser|"
    r"automated quer(?:y|ies)|unusual traffic|security challenge|cf-chl-|"
    r"cloudflare challenge|robot check",
    re.I,
)
_AUTH = re.compile(
    r"sign in to continue|log in to continue|authentication required|"
    r"verify your identity|two.factor authentication|multi.factor authentication|"
    r"enter the verification code|one.time password|\bOTP\b|\bMFA\b",
    re.I,
)
_CONTACT = re.compile(
    r"enter (?:your )?(?:phone|mobile|email|e-mail|contact) (?:number|address|details)|"
    r"phone number is required|email address is required|provide (?:your )?(?:phone|email)",
    re.I,
)
_BLOCKED = re.compile(
    r"access denied|you have been blocked|request blocked|site can't be reached|"
    r"this site can.t be reached|err_connection|browser has been closed|"
    r"target page, context or browser has been closed",
    re.I,
)


def _safe_text(page, limit=7000):
    try:
        return str(page.locator("body").inner_text(timeout=1200) or "")[:limit]
    except Exception:
        return ""


def detect_intervention(page, *, task="", overlays=None, reason="", repeat_count=0):
    """Return a small, redacted intervention descriptor, or None.

    Strong URL/body signals take precedence. Generic input fields alone never
    trigger a pause: a phone/email field is only classified when the page
    explicitly says the information is required.
    """
    if page is None:
        return {
            "type": "browser_blocked",
            "title": "Browser unavailable",
            "reason": "The active browser page is unavailable.",
            "user_action": "Reopen the browser session and retry the task.",
        }

    try:
        url = str(page.url or "")
        title = str(page.title() or "")[:180]
    except Exception:
        return {
            "type": "browser_blocked", "title": "Browser unavailable",
            "reason": "WebAI could not read the active page.",
            "user_action": "Check that the browser window is still open, then retry.",
        }

    text = _safe_text(page)
    parsed = urlparse(url)
    host_path = (parsed.netloc + parsed.path).lower()
    combined = title + "\n" + text

    if _CAPTCHA.search(host_path) or _CAPTCHA.search(combined):
        return {
            "type": "captcha_challenge", "title": "Security challenge",
            "reason": "The site is presenting a CAPTCHA or anti-bot verification.",
            "url": url, "page_title": title,
            "user_action": "Complete the challenge yourself in the visible browser, then resume.",
        }

    if _BLOCKED.search(combined) or "chrome-error://" in url or "about:neterror" in url:
        return {
            "type": "browser_blocked", "title": "Page or browser blocked",
            "reason": "The site or browser reports that the page cannot continue normally.",
            "url": url, "page_title": title,
            "user_action": "Resolve the browser/site error manually, then resume if the page is usable.",
        }

    if _AUTH.search(combined):
        return {
            "type": "authentication_required", "title": "Sign-in or verification required",
            "reason": "The current page explicitly requests authentication or an identity code.",
            "url": url, "page_title": title,
            "user_action": "Sign in or complete verification in the visible browser. WebAI will not bypass it.",
        }

    if _CONTACT.search(combined):
        return {
            "type": "contact_input_required", "title": "Contact information required",
            "reason": "The site explicitly requests phone or email details to continue.",
            "url": url, "page_title": title,
            "user_action": "WebAI will use a configured saved profile value if available; otherwise enter it in the browser.",
        }

    blocking = []
    for overlay in overlays or []:
        if not isinstance(overlay, dict):
            continue
        category = str(overlay.get("category", "")).lower()
        overlay_text = str(overlay.get("text", ""))
        if category in {"authentication", "task_flow"}:
            continue
        if category in {"unknown", "inspection_error"} and re.search(
            r"required|verify|confirm|permission|allow access|choose an option|"
            r"select an option|complete your profile", overlay_text, re.I
        ):
            blocking.append(overlay_text[:180])
    if blocking:
        return {
            "type": "modal_intervention", "title": "A blocking dialog needs attention",
            "reason": "A visible dialog appears to require a user decision.",
            "url": url, "page_title": title,
            "user_action": "Review the dialog in the browser. Keep task-relevant cart/checkout dialogs open.",
        }

    if repeat_count >= 2:
        return {
            "type": "agent_stuck", "title": "Agent stopped repeating actions",
            "reason": "The same action failed repeatedly; WebAI stopped to avoid an automation loop.",
            "url": url, "page_title": title,
            "user_action": "Check the current page and controls, then resume or revise the task.",
        }

    if reason:
        return {
            "type": "user_input_required", "title": "WebAI needs your input",
            "reason": str(reason)[:300],
            "url": url, "page_title": title,
            "user_action": "Provide the missing detail in the browser or clarify the task, then resume.",
        }
    return None


def intervention_for_status(status, *, page=None, summary="", overlays=None):
    """Map agent pause statuses to a structured, UI-friendly intervention."""
    if status == "needs_approval":
        return {
            "type": "approval_required", "title": "Approval required",
            "reason": str(summary or "A consequential action is waiting for approval.")[:300],
            "url": getattr(page, "url", None) if page is not None else None,
            "user_action": "Review the proposed action and approve it explicitly before it is executed.",
        }
    if status == "step_limit":
        return detect_intervention(page, overlays=overlays, reason=summary or "The agent reached its configured step limit.")
    if status == "needs_input":
        return detect_intervention(page, overlays=overlays, reason=summary or "The agent needs clarification.")
    return None
