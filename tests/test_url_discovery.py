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


def test_resolve_start_url_returns_valid_http_url(monkeypatch):
    client = LLMClient()
    client.settings = SimpleNamespace(
        api_key="test-key",
        base_url="https://openrouter.example/api/v1",
        model="test-model",
        timeout=30,
    )
    calls = {}

    def fake_post(url, **kwargs):
        calls["url"] = url
        calls["json"] = kwargs["json"]
        return FakeResponse('{"url":"https://en.wikipedia.org/"}')

    monkeypatch.setattr("webai.llm.requests.post", fake_post)
    assert client.resolve_start_url(
        "Open Wikipedia and find the Golden Gate Bridge article"
    ) == "https://en.wikipedia.org/"
    assert calls["url"] == "https://openrouter.example/api/v1/chat/completions"
    assert calls["json"]["temperature"] == 0


def test_resolve_start_url_rejects_ambiguous_task(monkeypatch):
    client = LLMClient()
    client.settings = SimpleNamespace(
        api_key="test-key",
        base_url="https://openrouter.example/api/v1",
        model="test-model",
        timeout=30,
    )
    monkeypatch.setattr(
        "webai.llm.requests.post",
        lambda *args, **kwargs: FakeResponse('{"url":null}'),
    )
    with pytest.raises(ValueError, match="could not determine"):
        client.resolve_start_url("Do something useful on the internet")


@pytest.mark.parametrize(
    "candidate",
    [
        "javascript:alert(1)",
        "file:///etc/passwd",
        "https://user:password@example.com/",
        "example.com",
    ],
)
def test_resolve_start_url_rejects_invalid_or_unsafe_urls(monkeypatch, candidate):
    client = LLMClient()
    client.settings = SimpleNamespace(
        api_key="test-key",
        base_url="https://openrouter.example/api/v1",
        model="test-model",
        timeout=30,
    )
    monkeypatch.setattr(
        "webai.llm.requests.post",
        lambda *args, **kwargs: FakeResponse('{"url":' + __import__("json").dumps(candidate) + '}'),
    )
    with pytest.raises(ValueError, match="invalid URL"):
        client.resolve_start_url("Open the website")
