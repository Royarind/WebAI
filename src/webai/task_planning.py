"""Task decomposition, evidence ledger, and deliverable verification.

The planner remains LLM-driven, but these deterministic structures make progress
explicit and prevent a finish action from silently skipping required deliverables.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse


def is_research_task(goal: str) -> bool:
    text = (goal or "").lower()
    return any(word in text for word in ("research", "compare", "comparison", "official documentation", "source urls", "sources"))


def requested_item_count(goal: str, default: int = 1) -> int:
    match = re.search(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+)\b", goal or "", re.I)
    if not match:
        return default
    words = {"one":1,"two":2,"three":3,"four":4,"five":5,"six":6,"seven":7,"eight":8,"nine":9,"ten":10}
    value = match.group(1).lower()
    try:
        return max(1, min(10, int(value)))
    except ValueError:
        return words.get(value, default)


class TaskPlan:
    """A compact checklist derived from the request; never substitutes for model planning."""
    def __init__(self, goal: str):
        self.goal = (goal or "").strip()
        self.research = is_research_task(self.goal)
        self.required_sources = requested_item_count(self.goal, 1) if self.research else 0
        self.criteria = []
        if self.research:
            self.criteria = [
                {"id":"sources", "description":f"Use at least {self.required_sources} distinct source URLs", "required":True},
                {"id":"comparison", "description":"Answer the requested comparison/research fields", "required":True},
                {"id":"caveats", "description":"Mark unverifiable information explicitly", "required":True},
            ]

    def snapshot(self):
        return {"goal":self.goal, "research_task":self.research,
                "required_source_count":self.required_sources, "criteria":self.criteria}


class EvidenceStore:
    """Deduplicated evidence indexed by source URL and locator."""
    def __init__(self):
        self._items = []
        self._keys = set()

    def add(self, *, url, locator=None, text="", kind="page_text"):
        url = str(url or "").strip()
        parsed = urlparse(url)
        text = str(text or "").strip()
        if parsed.scheme not in {"http","https"} or not parsed.netloc or not text:
            return False
        key = (url, str((locator or {}).get("by","")), str((locator or {}).get("value","")), text[:300])
        if key in self._keys:
            return False
        self._keys.add(key)
        self._items.append({"url":url,"locator":locator or {},"kind":kind,"text":text[:3000]})
        self._items = self._items[-24:]
        return True

    def snapshot(self):
        return list(self._items)

    def source_urls(self):
        return list(dict.fromkeys(item["url"] for item in self._items))


def verify_deliverable(plan: TaskPlan, evidence: EvidenceStore, finish_action: dict) -> dict:
    """Conservatively verify that a research finish has enough sourced evidence."""
    if not plan.research:
        return {"verified":True,"checks":[],"reason":"No research-specific deliverable checks apply."}
    urls = evidence.source_urls()
    summary = str(finish_action.get("summary") or "")
    checks = [
        {"check":"source_count", "passed":len(urls) >= plan.required_sources,
         "actual":len(urls), "required":plan.required_sources},
        {"check":"summary_present", "passed":bool(summary.strip())},
    ]
    # A result is not considered fully verified merely because the model says "done".
    if any(word in plan.goal.lower() for word in ("table", "compare", "comparison")):
        checks.append({"check":"comparison_in_summary", "passed":any(
            word in summary.lower() for word in ("table", "compare", "comparison", "findings")
        )})
    missing = [item["check"] for item in checks if not item["passed"]]
    return {
        "verified":not missing,
        "checks":checks,
        "source_urls":urls,
        "missing_checks":missing,
        "reason":"All deterministic research checks passed." if not missing else
                 "Research deliverable is incomplete or not evidenced: " + ", ".join(missing),
    }
