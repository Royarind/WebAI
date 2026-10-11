import json, os, re
import requests
from dotenv import load_dotenv

ALLOWED = {"inspect", "click", "fill", "screenshot", "read_text", "status"}
LOCATORS = {"role", "label", "placeholder", "text", "test_id", "css", "xpath"}


def rule_plan(task: str) -> dict:
    """Conservative parser for explicit, supported natural-language tasks."""
    t = task.strip()
    low = t.lower()
    if any(x in low for x in ("delete ", "purchase", "pay now", "submit order", "place order", "transfer money", "send email", "publish")):
        raise ValueError("Potential side effect detected. Use a reviewed, explicit Python workflow.")
    if any(x in low for x in ("inspect", "list elements", "find elements", "show controls")):
        return {"action": "inspect"}
    if "screenshot" in low or "take a picture" in low:
        return {"action": "screenshot", "path": "artifacts/page.png"}
    if low in {"status", "where am i", "current page"}:
        return {"action": "status"}
    m = re.search(r"click\s+(?:the\s+)?(button|link|checkbox|radio)\s+(?:named\s+|called\s+)?[\"']?(.+?)[\"']?$", t, re.I)
    if m:
        return {"action": "click", "by": "role", "value": m.group(1).lower(), "name": m.group(2).strip().strip("\"'")}
    m = re.search(r"fill\s+(?:the\s+)?(?:field\s+|textbox\s+)?(?:label\s+)?[\"']?(.+?)[\"']?\s+with\s+[\"'](.*?)[\"']$", t, re.I)
    if m:
        return {"action": "fill", "by": "label", "value": m.group(1).strip().strip("\"'"), "text": m.group(2)}
    m = re.search(r"(?:read|get|extract)\s+text\s+from\s+(.+)$", t, re.I)
    if m:
        selector = m.group(1).strip().strip("\"'")
        return {"action": "read_text", "by": "xpath" if selector.startswith(("/", "(")) else "css", "value": selector}
    raise ValueError("Unsupported task. Try 'inspect the page', 'take a screenshot', 'status', 'click the link named More information', or 'fill Email with \\\"qa@example.com\\\"'.")


def llm_plan(task: str) -> dict:
    """Optional OpenAI-compatible planner. Output is schema-validated."""
    load_dotenv()
    base = os.getenv("WEBAI_LLM_BASE_URL", "").rstrip("/")
    model, key = os.getenv("WEBAI_LLM_MODEL", ""), os.getenv("WEBAI_LLM_API_KEY", "")
    if not (base and model and key):
        raise RuntimeError("Configure WEBAI_LLM_BASE_URL, WEBAI_LLM_MODEL and WEBAI_LLM_API_KEY in .env.")
    system = ("Return one JSON object with action, by, value, name, text, path. Allowed actions: inspect, click, fill, screenshot, read_text, status. "
              "Allowed locators: role, label, placeholder, text, test_id, css, xpath. Never plan purchases, payments, deletion, sending, publishing, or security bypass. JSON only.")
    r = requests.post(f"{base}/chat/completions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"model": model, "temperature": 0, "messages":[{"role":"system","content":system},{"role":"user","content":task}]},
        timeout=float(os.getenv("WEBAI_LLM_TIMEOUT", "30")))
    r.raise_for_status()
    plan = json.loads(r.json()["choices"][0]["message"]["content"])
    if not isinstance(plan, dict) or plan.get("action") not in ALLOWED:
        raise ValueError("LLM returned an unsupported action.")
    if plan["action"] in {"click", "fill", "read_text"}:
        if plan.get("by") not in LOCATORS or not isinstance(plan.get("value"), str) or not plan["value"]:
            raise ValueError("LLM returned an invalid locator.")
    if plan["action"] == "fill" and not isinstance(plan.get("text"), str):
        raise ValueError("LLM omitted fill text.")
    return plan
