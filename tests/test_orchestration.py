import pytest

from webai.orchestration import CapabilityRegistry, ObjectiveLedger


def test_capability_registry_is_honest_about_unconfigured_connectors():
    registry = CapabilityRegistry().snapshot()
    assert any(item["name"] == "playwright_browser" for item in registry["available"])
    assert any(item["name"] == "outlook" for item in registry["unavailable"])
    assert any(item["name"] == "whatsapp" for item in registry["unavailable"])


def test_objective_cannot_be_completed_without_registered_evidence():
    ledger = ObjectiveLedger([{"id": "a", "description": "Find the source"}])
    with pytest.raises(ValueError, match="evidence ID"):
        ledger.update("a", "completed", evidence_ids=["missing"])


def test_objective_completion_requires_registered_evidence():
    ledger = ObjectiveLedger([{"id": "a", "description": "Find the source"}])
    ledger.add_evidence("evidence_1", {"url": "https://example.com", "text": "Relevant result"})
    result = ledger.update("a", "completed", evidence_ids=["evidence_1"])
    assert result["status"] == "completed"
    assert ledger.snapshot()["all_completed"] is True


def test_dependencies_block_downstream_objectives():
    ledger = ObjectiveLedger([
        {"id": "a", "description": "Collect information"},
        {"id": "b", "description": "Compare information", "depends_on": ["a"]},
    ])
    assert ledger.next_objective()["id"] == "a"
    with pytest.raises(ValueError, match="dependencies"):
        ledger.update("b", "completed", evidence_ids=["evidence_1"])
    ledger.add_evidence("evidence_1", {"text": "Collected"})
    ledger.update("a", "completed", evidence_ids=["evidence_1"])
    assert ledger.next_objective()["id"] == "b"
