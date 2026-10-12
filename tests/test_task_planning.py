from webai.task_planning import EvidenceStore, TaskPlan, requested_item_count, verify_deliverable


def test_task_plan_extracts_research_source_count():
    plan = TaskPlan(
        "Research three Python browser-automation tools using official documentation and compare them in a table."
    )
    assert plan.research is True
    assert plan.required_sources == 3
    assert {item["id"] for item in plan.criteria} == {"sources", "comparison", "caveats"}


def test_evidence_store_deduplicates_and_rejects_invalid_urls():
    store = EvidenceStore()
    entry = {
        "url": "https://example.test/docs",
        "locator": {"by": "css", "value": "main"},
        "text": "Selenium supports multiple language bindings.",
    }
    assert store.add(**entry) is True
    assert store.add(**entry) is False
    assert store.add(url="file:///tmp/a", text="not web evidence") is False
    assert store.source_urls() == ["https://example.test/docs"]


def test_research_verifier_requires_distinct_sourced_evidence_and_comparison():
    plan = TaskPlan("Research three browser tools and compare them in a table.")
    store = EvidenceStore()
    for host in ("selenium.dev", "playwright.dev", "robotframework.org"):
        store.add(
            url=f"https://{host}/docs",
            locator={"by": "css", "value": "main"},
            text="Official documentation with language support and key capabilities.",
        )

    result = verify_deliverable(
        plan, store,
        {"summary": "Comparison table of three browser automation tools."},
    )
    assert result["verified"] is True
    assert len(result["source_urls"]) == 3


def test_research_verifier_does_not_accept_missing_sources():
    plan = TaskPlan("Research three browser tools and compare them in a table.")
    result = verify_deliverable(plan, EvidenceStore(), {"summary": "Comparison table completed."})
    assert result["verified"] is False
    assert "source_count" in result["missing_checks"]
