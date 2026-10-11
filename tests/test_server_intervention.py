from types import SimpleNamespace

import webai.server as server


class FakeAgent:
    def __init__(self, result=None):
        self.browser = SimpleNamespace(page=object())
        self.calls = []
        self.result = result or {"status": "needs_input", "summary": "Solve CAPTCHA"}

    def run(self, task, url=None):
        self.calls.append((task, url))
        return self.result


def test_run_task_keeps_task_and_returns_intervention_state(monkeypatch):
    fake = FakeAgent()
    monkeypatch.setattr(server, "session_agent", fake)
    monkeypatch.setattr(server, "last_task", "")
    monkeypatch.setattr(server, "last_url", "")
    monkeypatch.setattr(server, "last_result", None)

    result = server.run_task(server.RunRequest(
        url="https://www.google.com",
        task="Search for three Python web frameworks",
    ))

    assert result["status"] == "needs_input"
    assert fake.calls == [("Search for three Python web frameworks", "https://www.google.com")]
    assert server.last_task == "Search for three Python web frameworks"
    assert server.last_url == "https://www.google.com"


def test_resume_uses_current_page_without_reopening_original_url(monkeypatch):
    fake = FakeAgent({"status": "completed", "summary": "Done"})
    monkeypatch.setattr(server, "session_agent", fake)
    monkeypatch.setattr(server, "last_task", "Search for three Python web frameworks")
    monkeypatch.setattr(server, "last_url", "https://www.google.com")
    monkeypatch.setattr(server, "last_result", {"status": "needs_input", "summary": "Paused"})

    result = server.resume_task()

    assert result["status"] == "completed"
    assert fake.calls == [("Search for three Python web frameworks", None)]


def test_dashboard_exposes_resume_control():
    assert 'id="resume"' in server.PAGE
    assert "fetch('/api/resume')" in server.PAGE
    assert "visible WebAI browser" in server.PAGE
