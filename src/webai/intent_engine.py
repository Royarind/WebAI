"""Outcome-oriented intent assessment for WebAI.

This module supplies structured intent and next-step context to the agent. It is
deliberately deterministic and explainable; the LLM still handles semantic
reasoning, while this layer keeps goals, likely capabilities, constraints, and
completion expectations explicit across planning cycles.
"""
from __future__ import annotations

import re
from typing import Any


_DOMAIN_TERMS = {
    "browser": ("website", "web page", "webpage", "browser", "online", "website", "search online", "url", "site"),
    "desktop": ("desktop", "computer", "windows", "screen", "application", "app", "open outlook", "outlook desktop"),
    "email": ("email", "emails", "outlook", "inbox", "mailbox", "email thread", "attachment"),
    "messaging": ("whatsapp", "message", "messages", "chat", "reply", "text them", "send a message"),
    "files": ("file", "files", "folder", "folders", "document", "documents", "pdf", "spreadsheet", "desktop"),
    "calendar": ("calendar", "meeting", "meetings", "schedule", "appointment", "availability"),
    "office": ("excel", "workbook", "spreadsheet", "word document", "powerpoint", "presentation", "report"),
    "research": ("research", "compare", "comparison", "find out", "investigate", "sources", "summarize", "summary"),
}
_OUTPUT_TERMS = {
    "summary": ("summarize", "summary", "brief me", "catch me up", "overview", "key points"),
    "comparison": ("compare", "comparison", "versus", " vs ", "differences"),
    "draft": ("draft", "prepare a reply", "write a reply", "compose", "word this", "in my style"),
    "file": ("save as", "create a file", "excel", "spreadsheet", "document", "presentation", "pdf", "report"),
    "action": ("send", "submit", "book", "purchase", "delete", "update", "change", "schedule"),
}
_RISK_TERMS = {
    "external_communication": ("send email", "send a message", "reply", "forward", "publish", "post this"),
    "financial": ("pay", "payment", "purchase", "buy", "transfer money", "place order", "checkout"),
    "destructive": ("delete", "remove permanently", "overwrite", "erase"),
    "commitment": ("book", "confirm booking", "submit application", "submit form", "schedule meeting"),
}


def _matches(text: str, phrases: tuple[str, ...]) -> list[str]:
    normalized = re.sub(r"\\s+", " ", text.lower()).strip()
    low = f" {normalized} "
    return [phrase.strip() for phrase in phrases if f" {phrase.strip()} " in low]


def assess_intent(goal: str, *, available_capabilities: list[str] | None = None) -> dict[str, Any]:
    """Infer likely intent, tool domains, deliverables, risks, and missing context."""
    original = str(goal or "").strip()
    low = original.lower()
    domains = [name for name, terms in _DOMAIN_TERMS.items() if _matches(low, terms)]
    outputs = [name for name, terms in _OUTPUT_TERMS.items() if _matches(low, terms)]
    risks = [name for name, terms in _RISK_TERMS.items() if _matches(low, terms)]

    if any(term in low for term in ("catch me up", "what needs my attention", "what am i waiting for", "daily briefing")):
        intent = "briefing"
        domains = list(dict.fromkeys(domains + ["email", "calendar", "files"]))
        outputs = list(dict.fromkeys(outputs + ["summary"]))
    elif any(term in low for term in ("in my style", "sound like me", "my usual tone", "mimic my style")):
        intent = "personalized_communication"
        domains = list(dict.fromkeys(domains + ["messaging"]))
        outputs = list(dict.fromkeys(outputs + ["draft"]))
    elif any(term in low for term in ("find", "search", "locate", "where is")):
        intent = "information_retrieval"
    elif any(term in low for term in ("compare", "versus", " vs ")):
        intent = "comparison"
    elif any(term in low for term in ("send", "submit", "book", "purchase", "delete", "update", "schedule")):
        intent = "action_execution"
    elif any(term in low for term in ("summarize", "summary", "brief me", "catch me up")):
        intent = "summarization"
    else:
        intent = "general_goal"

    # Split on common conjunctions and list markers without assuming each clause
    # is a separate objective. Keep the raw request authoritative.
    clauses = [part.strip(" .;\n\t-") for part in re.split(
        r"\s+(?:and then|then|after that|also)\s+|[;\n]+", original, flags=re.I
    ) if part.strip(" .;\n\t-")]
    objectives = []
    for index, clause in enumerate(clauses[:10], 1):
        objectives.append({
            "id": f"obj_{index}",
            "description": clause,
            "status": "pending",
            "completion_evidence_required": True,
        })
    if not objectives and original:
        objectives = [{"id": "obj_1", "description": original, "status": "pending", "completion_evidence_required": True}]

    capabilities = list(dict.fromkeys(available_capabilities or [
        "browser", "desktop", "email", "messaging", "local_files", "office_documents", "calendar"
    ]))
    unavailable = [domain for domain in domains if domain not in capabilities and not (
        domain == "files" and "local_files" in capabilities
    )]
    needs_context = []
    if "messaging" in domains and not any(word in low for word in ("this person", "this conversation", "current chat", "selected chat", "to ")):
        needs_context.append("Identify the intended recipient or conversation from current context; ask if ambiguous.")
    if risks:
        needs_context.append("Require explicit authorization before consequential external, financial, destructive, or commitment-making actions.")

    return {
        "original_request": original,
        "intent": intent,
        "likely_tool_domains": domains,
        "expected_outputs": outputs,
        "risk_categories": risks,
        "objectives": objectives,
        "available_capabilities": capabilities,
        "capability_gaps": unavailable,
        "context_rules": needs_context,
        "planning_policy": [
            "Optimize for the user's intended outcome, not literal click-by-click instructions.",
            "Inspect current application state and available tools before choosing an execution route.",
            "Choose the next action that reduces the most important unresolved uncertainty or advances a pending objective.",
            "After every action, compare observed state with expected state and revise the plan when evidence changes.",
            "Do not mark objectives complete without observable evidence; explain blockers or ask concise clarifying questions when necessary.",
        ],
    }


def next_step_guidance(intent: dict[str, Any], *, observation: dict | None = None,
                       progress: dict | None = None, last_result: dict | None = None) -> dict[str, Any]:
    """Build a compact, state-aware decision context for the next planning cycle."""
    observation = observation or {}
    progress = progress or {}
    last_result = last_result or {}
    objectives = intent.get("objectives", [])
    evidence = progress.get("evidence_ledger", []) or []
    visited = progress.get("visited_pages", []) or []
    failed = last_result.get("ok") is False
    if failed:
        next_step = "Diagnose the observed failure, inspect the current state, and choose a different recovery strategy; do not blindly repeat the same action."
    elif not observation:
        next_step = "Inspect the available environment and identify the most reliable tool route before acting."
    elif any(item.get("status") == "pending" for item in objectives):
        next_step = "Select the highest-value pending objective, determine what evidence or action is missing, and take one purposeful step."
    else:
        next_step = "Check the completion criteria against observed evidence; verify the result before finishing."
    return {
        "intent": intent.get("intent", "general_goal"),
        "pending_objectives": [o for o in objectives if o.get("status") != "completed"],
        "evidence_item_count": len(evidence),
        "visited_page_count": len(visited),
        "last_action_failed": failed,
        "current_url": observation.get("url"),
        "next_step_guidance": next_step,
    }
