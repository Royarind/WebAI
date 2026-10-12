from types import SimpleNamespace

from webai.agent import Agent


def test_local_file_task_routes_without_browser(monkeypatch, tmp_path):
    root = tmp_path / "documents"
    root.mkdir()
    (root / "project.md").write_text("Aurora release is planned for Friday.", encoding="utf-8")
    monkeypatch.setenv("WEBAI_FILE_ROOTS", str(root))
    monkeypatch.delenv("WEBAI_OUTLOOK_ACCESS_TOKEN", raising=False)

    agent = Agent.__new__(Agent)
    agent.browser = None
    agent.settings = SimpleNamespace(timeout=10)

    result = agent._run_connector_only("Search my local files for Aurora")
    assert result is not None
    assert result["status"] == "completed"
    assert result["data"]["local_files"]["count"] == 1
    assert agent.browser is None


def test_outlook_briefing_reports_configuration_instead_of_opening_browser(monkeypatch):
    monkeypatch.delenv("WEBAI_OUTLOOK_ACCESS_TOKEN", raising=False)
    agent = Agent.__new__(Agent)
    agent.browser = None
    agent.settings = SimpleNamespace(timeout=10)

    result = agent._run_connector_only("Summarize my Outlook inbox")
    assert result is not None
    assert result["status"] == "needs_input"
    assert "WEBAI_OUTLOOK_ACCESS_TOKEN" in result["summary"]
    assert agent.browser is None
