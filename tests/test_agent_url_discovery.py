from types import SimpleNamespace

from webai.agent import Agent


class FakePage:
    def __init__(self):
        self.url = "about:blank"

    def title(self):
        return "Test page"

    def evaluate(self, script):
        return []


class FakeBrowser:
    def __init__(self, **kwargs):
        self.page = FakePage()
        self.opened = []
        self.closed = False

    def start(self):
        return self

    def open(self, url):
        self.opened.append(url)
        self.page.url = url
        return {"url": url, "title": "Test page"}

    def status(self):
        return {"url": self.page.url, "title": "Test page"}

    def inspect(self, limit=150):
        return []

    def close(self):
        self.closed = True


class FakeLLM:
    def resolve_start_url(self, task):
        assert "Wikipedia" in task
        return "https://en.wikipedia.org/"

    def next_action(self, messages, screenshot_path=None):
        return {"action": "ask_user", "summary": "Test stopped safely."}


class FakeMemory:
    def recent_runs(self, limit=4):
        return []

    def notes_for(self, domain, limit=4):
        return []

    def add_run(self, *args, **kwargs):
        pass

    def add_note(self, *args, **kwargs):
        pass


def test_agent_keeps_owned_browser_open_when_intervention_is_required(monkeypatch):
    import webai.agent as agent_module

    monkeypatch.setattr(agent_module, "WebAI", FakeBrowser)
    monkeypatch.setattr(
        agent_module,
        "get_settings",
        lambda: SimpleNamespace(
            headless=False,
            vision_enabled=False,
            max_steps=1,
            artifact_dir="artifacts",
            memory_path="unused.sqlite3",
        ),
    )
    created = {}

    def make_browser(**kwargs):
        created["browser"] = FakeBrowser(**kwargs)
        return created["browser"]

    monkeypatch.setattr(agent_module, "WebAI", make_browser)
    agent = Agent(llm=FakeLLM(), memory=FakeMemory())
    result = agent.run("Open Wikipedia and find the Golden Gate Bridge article")

    assert created["browser"].opened == ["https://en.wikipedia.org/"]
    assert result["url"] == "https://en.wikipedia.org/"
    assert result["status"] == "needs_input"
    assert created["browser"].closed is False
