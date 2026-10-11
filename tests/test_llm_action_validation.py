import json
from types import SimpleNamespace

import pytest

from webai.llm import LLMClient


class FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, content):
        self.content = content

    def json(self):
        return {"choices": [{"message": {"content": self.content}}]}


def make_client():
    client = LLMClient()
    client.settings = SimpleNamespace(
        api_key="test-key",
        base_url="https://openrouter.example/api/v1",
        model="test-model",
        timeout=30,
        vision_enabled=False,
    )
    return client


def test_next_action_reasks_model_when_locator_is_invalid(monkeypatch):
    client = make_client()
    responses = iter([
        '{"action":"click","by":"","value":"","name":"Search"}',
        '{"action":"click","by":"role","value":"button","name":"Search"}',
    ])
    requests = []

    def fake_post(url, **kwargs):
        requests.append(kwargs["json"])
        return FakeResponse(next(responses))

    monkeypatch.setattr("webai.llm.requests.post", fake_post)

    action = client.next_action([{"role": "user", "content": "Click Search"}])

    assert action == {
        "action": "click", "by": "role", "value": "button", "name": "Search"
    }
    assert len(requests) == 2
    assert "invalid locator" in requests[1]["messages"][-1]["content"].lower()


def test_next_action_pauses_instead_of_repeating_inspect_after_invalid_locator(monkeypatch):
    client = make_client()
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs["json"])
        return FakeResponse('{"action":"click","by":"unknown","value":""}')

    monkeypatch.setattr("webai.llm.requests.post", fake_post)

    action = client.next_action([{"role": "user", "content": "Click Search"}])

    assert action["action"] == "ask_user"
    assert "invalid locator" in action["reason"].lower()
    assert len(calls) == 3


def test_next_action_does_not_retry_unsupported_action(monkeypatch):
    client = make_client()
    calls = []

    def fake_post(url, **kwargs):
        calls.append(kwargs["json"])
        return FakeResponse('{"action":"teleport"}')

    monkeypatch.setattr("webai.llm.requests.post", fake_post)

    with pytest.raises(ValueError, match="unsupported action"):
        client.next_action([{"role": "user", "content": "Do a task"}])

    assert len(calls) == 1



@pytest.mark.parametrize("raw_by,expected", [
    ("get_by_placeholder", "placeholder"),
    ("getByRole('button')", "role"),
    ("locator strategy: css", "css"),
    ({"strategy": "label"}, "label"),
])
def test_next_action_normalizes_playwright_style_locator_strategies(monkeypatch, raw_by, expected):
    client = make_client()
    payload = {"action": "click", "by": raw_by, "value": "Search"}
    if expected == "role":
        payload["name"] = "Search"
    response_content = json.dumps(payload)

    monkeypatch.setattr(
        "webai.llm.requests.post",
        lambda url, **kwargs: FakeResponse(response_content),
    )

    action = client.next_action([{"role": "user", "content": "Click Search"}])
    assert action["by"] == expected
