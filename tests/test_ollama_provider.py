import requests
import pytest

from webai.config import get_settings
from webai.llm import LLMClient


class FakeResponse:
    def __init__(self, payload, status_code=200, text=""):
        self._payload = payload
        self.status_code = status_code
        self.text = text
        self.headers = {}

    def json(self):
        return self._payload


def _clear_ollama_env(monkeypatch):
    for name in (
        "WEBAI_OLLAMA_BASE_URL",
        "WEBAI_OLLAMA_MODEL",
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL",
        "ACTIVE_LLM_PROVIDER",
    ):
        monkeypatch.delenv(name, raising=False)


def test_default_hosted_provider_configuration_is_preserved(monkeypatch):
    _clear_ollama_env(monkeypatch)
    monkeypatch.setenv("WEBAI_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("WEBAI_LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("WEBAI_LLM_MODEL", "openrouter/free")
    settings = get_settings()

    assert settings.provider == "openrouter"
    assert settings.base_url == "https://openrouter.ai/api/v1"
    assert settings.model == "openrouter/free"


def test_ollama_configuration_ignores_hosted_defaults(monkeypatch):
    monkeypatch.setenv("WEBAI_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("WEBAI_LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("WEBAI_LLM_MODEL", "openrouter/free")
    monkeypatch.setenv("WEBAI_OLLAMA_MODEL", "qwen3:4b")
    monkeypatch.delenv("WEBAI_OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)

    settings = get_settings()

    assert settings.provider == "ollama"
    assert settings.base_url == "http://localhost:11434/v1"
    assert settings.model == "qwen3:4b"


def test_ollama_action_request_needs_no_api_key_or_authorization(monkeypatch):
    monkeypatch.setenv("WEBAI_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("WEBAI_OLLAMA_BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("WEBAI_OLLAMA_MODEL", "qwen3:4b")
    monkeypatch.setenv("WEBAI_LLM_TIMEOUT", "90")
    monkeypatch.delenv("WEBAI_LLM_API_KEY", raising=False)
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse({
            "choices": [{
                "message": {
                    "content": '{"action":"inspect","reason":"Check current page"}'
                }
            }]
        })

    monkeypatch.setattr("webai.llm.requests.post", fake_post)
    action = LLMClient().next_action([{"role": "user", "content": "Inspect the page"}])

    assert action["action"] == "inspect"
    assert captured["url"] == "http://localhost:11434/v1/chat/completions"
    assert captured["json"]["model"] == "qwen3:4b"
    assert captured["timeout"] == (5, 90)
    assert "Authorization" not in captured["headers"]


def test_ollama_connection_error_has_actionable_message(monkeypatch):
    monkeypatch.setenv("WEBAI_LLM_PROVIDER", "ollama")
    monkeypatch.setenv("WEBAI_OLLAMA_MODEL", "qwen3:4b")
    monkeypatch.delenv("WEBAI_LLM_API_KEY", raising=False)

    def fail_connection(*args, **kwargs):
        raise requests.exceptions.ConnectionError("connection refused")

    monkeypatch.setattr("webai.llm.requests.post", fail_connection)
    with pytest.raises(RuntimeError, match="Cannot connect to Ollama"):
        LLMClient().next_action([{"role": "user", "content": "Inspect the page"}])


def test_hosted_provider_still_requires_api_key(monkeypatch):
    monkeypatch.setenv("WEBAI_LLM_PROVIDER", "openrouter")
    monkeypatch.setenv("WEBAI_LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("WEBAI_LLM_API_KEY", "")

    with pytest.raises(RuntimeError, match="WEBAI_LLM_API_KEY is empty"):
        LLMClient().next_action([{"role": "user", "content": "Inspect the page"}])



@pytest.mark.parametrize(
    "payload, message",
    [
        ({"action": {"nested": "dict"}}, "invalid action field"),
        ({"action": "click", "by": {"nested": "dict"}, "value": "Search"}, "invalid locator strategy"),
        ({"action": "click", "by": "role", "value": {"nested": "dict"}}, "invalid locator value"),
    ],
)
def test_parse_action_reports_malformed_field_types(payload, message):
    import json

    with pytest.raises(ValueError, match=message):
        LLMClient._parse_action(json.dumps(payload))
