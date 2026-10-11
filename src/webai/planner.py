import json, re
import requests
from dotenv import load_dotenv
from .config import get_settings

ALLOWED = {"inspect", "click", "fill", "control", "screenshot", "read_text", "status"}
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
    """Optional OpenAI-compatible planner, including local Ollama."""
    load_dotenv()
    s = get_settings()
    if s.provider != "ollama" and not s.api_key:
        raise RuntimeError("WEBAI_LLM_API_KEY is empty; configure a key for the selected hosted LLM provider.")
    headers = {"Content-Type": "application/json"}
    if s.provider != "ollama":
        headers["Authorization"] = "Bearer " + s.api_key
    system = (
        "Return one JSON object with action, by, value, name, text, path. Allowed actions: inspect, click, fill, control, screenshot, read_text, status. For sliders, dropdowns, and quantity controls, use control with operation set_value, choose, increment, or decrement and the appropriate target. "
        "Allowed locators: role, label, placeholder, text, test_id, css, xpath. Never plan purchases, payments, deletion, sending, publishing, or security bypass. JSON only."
    )
    try:
        r = requests.post(
            f"{s.base_url}/chat/completions",
            headers=headers,
            json={"model": s.model, "temperature": 0, "messages":[{"role":"system","content":system},{"role":"user","content":task}]},
            timeout=s.timeout,
        )
    except requests.exceptions.ConnectionError as exc:
        if s.provider == "ollama":
            raise RuntimeError(f"Cannot connect to Ollama at {s.base_url}. Start Ollama and pull model '{s.model}'.") from exc
        raise
    if r.status_code >= 400:
        raise RuntimeError(f"{'Ollama' if s.provider == 'ollama' else s.provider} HTTP {r.status_code}: {r.text[:1000]}")
    payload = r.json()
    try:
        content = payload["choices"][0]["message"]["content"]
        if isinstance(content, list):
            content = "".join(part.get("text", "") for part in content if isinstance(part, dict))
        stripped = content.strip()
        if stripped.startswith("```"):
            stripped = stripped.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        plan = json.loads(stripped)
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise ValueError(f"LLM returned an invalid planning response: {str(payload)[:800]}") from exc
    if not isinstance(plan, dict) or plan.get("action") not in ALLOWED:
        raise ValueError("LLM returned an unsupported action.")
    if plan["action"] in {"click", "fill", "read_text"}:
        if plan.get("by") not in LOCATORS or not isinstance(plan.get("value"), str) or not plan["value"]:
            raise ValueError("LLM returned an invalid locator.")
    if plan["action"] == "fill" and not isinstance(plan.get("text"), str):
        raise ValueError("LLM omitted fill text.")
    return plan
