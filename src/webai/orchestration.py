"""Stateful orchestration primitives for outcome-oriented WebAI runs.

This module tracks objectives and tool capabilities explicitly. It does not claim
an objective is complete merely because an action succeeded: completion requires
the planner to identify supporting evidence, which is retained for audit.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class Capability:
    name: str
    domains: tuple[str, ...]
    available: bool
    mode: str
    description: str
    requires_approval: bool = False


class CapabilityRegistry:
    """A truthful inventory of execution routes available to this process."""

    def __init__(self, capabilities: list[Capability] | None = None):
        self._items: dict[str, Capability] = {}
        for capability in capabilities or []:
            self.register(capability)
        # Browser is the only general execution surface guaranteed by the
        # current runtime. Other integrations are declared unavailable until
        # a concrete connector is installed and configured.
        self.register(Capability(
            name="playwright_browser",
            domains=("browser", "research", "web"),
            available=True,
            mode="interactive_browser",
            description="Inspect and interact with the current Playwright browser session.",
        ))
        for name, domains, description in (
            ("windows_desktop", ("desktop",), "Native Windows desktop automation connector."),
            ("outlook", ("email", "calendar"), "Outlook mail and calendar connector."),
            ("whatsapp", ("messaging",), "WhatsApp conversation connector."),
            ("local_files", ("files", "office"), "Local file search and document access connector."),
            ("office_documents", ("office",), "Document and spreadsheet creation connector."),
        ):
            self.register(Capability(name, domains, False, "not_configured", description))

    def register(self, capability: Capability) -> None:
        self._items[capability.name] = capability

    def snapshot(self) -> dict[str, Any]:
        return {
            "available": [
                {"name": item.name, "domains": list(item.domains), "mode": item.mode,
                 "description": item.description, "requires_approval": item.requires_approval}
                for item in self._items.values() if item.available
            ],
            "unavailable": [
                {"name": item.name, "domains": list(item.domains), "mode": item.mode,
                 "description": item.description}
                for item in self._items.values() if not item.available
            ],
            "policy": "Never claim to have used an unavailable connector. Use an available alternative or explain the capability gap.",
        }

    def for_domains(self, domains: list[str]) -> dict[str, Any]:
        wanted = set(domains)
        return {
            "available": [item for item in self.snapshot()["available"]
                          if wanted.intersection(item["domains"])],
            "unavailable": [item for item in self.snapshot()["unavailable"]
                            if wanted.intersection(item["domains"])],
        }


class ObjectiveLedger:
    """Tracks objective status, dependencies, and the evidence behind completion."""

    VALID_STATUSES = {"pending", "in_progress", "blocked", "completed"}

    def __init__(self, objectives: list[dict[str, Any]] | None = None):
        self._objectives: dict[str, dict[str, Any]] = {}
        self._evidence: dict[str, dict[str, Any]] = {}
        for objective in objectives or []:
            self.add_objective(objective)

    def add_objective(self, objective: dict[str, Any]) -> None:
        oid = str(objective.get("id") or f"obj_{len(self._objectives) + 1}")
        if oid in self._objectives:
            return
        self._objectives[oid] = {
            "id": oid,
            "description": str(objective.get("description") or "").strip(),
            "status": objective.get("status", "pending"),
            "depends_on": list(objective.get("depends_on") or []),
            "evidence_ids": [],
            "blocker": None,
        }

    def add_evidence(self, evidence_id: str, evidence: dict[str, Any]) -> None:
        if evidence_id:
            self._evidence[evidence_id] = dict(evidence)

    def update(self, objective_id: str, status: str, *, evidence_ids: list[str] | None = None,
               blocker: str | None = None) -> dict[str, Any]:
        if status not in self.VALID_STATUSES:
            raise ValueError(f"Unsupported objective status: {status}")
        if objective_id not in self._objectives:
            raise KeyError(f"Unknown objective: {objective_id}")
        objective = self._objectives[objective_id]
        if status == "completed":
            dependencies = objective["depends_on"]
            unfinished = [dep for dep in dependencies if self._objectives.get(dep, {}).get("status") != "completed"]
            if unfinished:
                raise ValueError("Cannot complete objective before dependencies: " + ", ".join(unfinished))
            ids = list(dict.fromkeys(evidence_ids or []))
            missing = [eid for eid in ids if eid not in self._evidence]
            if not ids or missing:
                raise ValueError("Objective completion requires at least one registered evidence ID.")
            objective["evidence_ids"] = ids
        elif evidence_ids:
            objective["evidence_ids"] = list(dict.fromkeys(evidence_ids))
        objective["status"] = status
        objective["blocker"] = blocker
        return dict(objective)

    def next_objective(self) -> dict[str, Any] | None:
        for objective in self._objectives.values():
            if objective["status"] in {"pending", "in_progress"} and all(
                self._objectives.get(dep, {}).get("status") == "completed"
                for dep in objective["depends_on"]
            ):
                return dict(objective)
        return None

    def snapshot(self) -> dict[str, Any]:
        items = [dict(item) for item in self._objectives.values()]
        counts = {status: sum(item["status"] == status for item in items) for status in self.VALID_STATUSES}
        return {
            "objectives": items,
            "counts": counts,
            "next_objective": self.next_objective(),
            "evidence": dict(self._evidence),
            "all_completed": bool(items) and all(item["status"] == "completed" for item in items),
        }
