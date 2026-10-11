"""Local-only profile autofill for WebAI.

Sensitive values are read from environment variables and are filled directly by
Playwright; they are never added to the LLM prompt or run-history database.
Existing browser/account autofill values are left untouched.
"""
import os
import re


PROFILE_ENV = {
    "name": ("WEBAI_PROFILE_NAME",),
    "email": ("WEBAI_PROFILE_EMAIL",),
    "phone": ("WEBAI_PROFILE_PHONE",),
    "address": ("WEBAI_PROFILE_ADDRESS",),
    "password": ("WEBAI_PROFILE_PASSWORD",),
}


def _profile_values():
    return {kind: next((os.getenv(key, "").strip() for key in keys if os.getenv(key, "").strip()), "")
            for kind, keys in PROFILE_ENV.items()}


def _kind(field):
    text = " ".join(str(field.get(k, "")) for k in ("name", "id", "type", "placeholder", "autocomplete", "label")).lower()
    if field.get("type") == "password" or "current-password" in text or "new-password" in text:
        return "password"
    if field.get("type") == "email" or re.search(r"\b(email|e-mail)\b", text):
        return "email"
    if field.get("type") == "tel" or re.search(r"\b(phone|mobile|telephone)\b", text):
        return "phone"
    if re.search(r"\b(address|street|shipping address|billing address)\b", text):
        return "address"
    if field.get("autocomplete") in {"name", "given-name", "family-name"} or re.search(r"\b(full name|your name|first name|last name)\b", text):
        return "name"
    return None


def autofill_known_profile(page):
    """Fill blank, visible, confidently labelled fields from local env profile.

    Returns field kinds filled (never their values). Does not submit forms or
    overwrite values already populated by a browser/account/password manager.
    """
    values = _profile_values()
    if not any(values.values()) or page is None:
        return []
    filled = []
    try:
        fields = page.locator("input,textarea").evaluate_all("""els => els.map((el, index) => {
          const r = el.getBoundingClientRect(), s = getComputedStyle(el);
          const label = el.labels ? Array.from(el.labels).map(x => x.innerText).join(' ') : '';
          return {index, tag: el.tagName.toLowerCase(), type: (el.type || '').toLowerCase(),
            name: el.name || '', id: el.id || '', placeholder: el.placeholder || '',
            autocomplete: el.autocomplete || '', label, value: el.value || '',
            visible: r.width > 0 && r.height > 0 && s.display !== 'none' && s.visibility !== 'hidden',
            disabled: !!el.disabled, readOnly: !!el.readOnly};
        })""")
        locator = page.locator("input,textarea")
        for field in fields:
            if not field.get("visible") or field.get("disabled") or field.get("readOnly") or field.get("value"):
                continue
            kind = _kind(field)
            value = values.get(kind or "", "")
            if not value:
                continue
            # Do not fill one-time codes, CAPTCHA responses, or arbitrary textareas.
            marker = " ".join(str(field.get(k, "")) for k in ("name", "id", "type", "placeholder", "autocomplete", "label")).lower()
            if re.search(r"captcha|one.time|verification code|security code|otp|cvv|card number", marker):
                continue
            if field.get("tag") == "textarea" and kind != "address":
                continue
            try:
                locator.nth(int(field["index"])).fill(value, timeout=1200)
                filled.append(kind)
            except Exception:
                continue
    except Exception:
        return filled
    return sorted(set(filled))
