from types import SimpleNamespace

import pytest

from webai.llm import LLMClient


class FakeResponse:
    status_code = 200

    def __init__(self, payload, text=""):
        self.payload = payload
        self.text = text

    def json(self):
        return self.payload


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


def test_next_action_surfaces_provider_error_when_choices_are_missing(monkeypatch):
    client = make_client()
    response = FakeResponse({"error": {"message": "Provider is rate-limited"}})
    monkeypatch.setattr("webai.llm.requests.post", lambda *a, **k: response)

    with pytest.raises(RuntimeError, match="Provider is rate-limited"):
        client.next_action([{"role": "user", "content": "Find a page"}])


def test_next_action_reports_empty_content_without_key_error(monkeypatch):
    client = make_client()
    response = FakeResponse({"choices": [{"message": {"content": ""}, "finish_reason": "length"}]})
    monkeypatch.setattr("webai.llm.requests.post", lambda *a, **k: response)

    with pytest.raises(RuntimeError, match="empty model content"):
        client.next_action([{"role": "user", "content": "Find a page"}])


def test_next_action_accepts_normal_choice_response(monkeypatch):
    client = make_client()
    response = FakeResponse({
        "choices": [{
            "message": {
                "content": '{"action":"finish","summary":"Done","verified":true,"verification_evidence":"The page says Done."}'
            }
        }]
    })
    monkeypatch.setattr("webai.llm.requests.post", lambda *a, **k: response)

    action = client.next_action([{"role": "user", "content": "Find a page"}])
    assert action["action"] == "finish"
