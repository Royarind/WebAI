from types import SimpleNamespace

import pytest

from webai.llm import LLMClient


def response(status_code, body, headers=None):
    return SimpleNamespace(
        status_code=status_code,
        text=body,
        headers=headers or {},
    )


def test_in_flight_budget_error_includes_retry_after_and_avoids_blind_retry():
    err = response(
        402,
        '{"error":{"metadata":{"reason":"in_flight_budget_exhausted"}}}',
        {"Retry-After": "120"},
    )
    with pytest.raises(RuntimeError) as caught:
        LLMClient._raise_http_error(err, "action planning")
    message = str(caught.value)
    assert "in-flight request budget exhausted" in message
    assert "120 seconds" in message
    assert "Do not launch duplicate runs" in message


def test_rate_limit_error_includes_retry_after():
    with pytest.raises(RuntimeError, match="HTTP 429.*Retry-After: 30 seconds"):
        LLMClient._raise_http_error(
            response(429, '{"error":"rate limited"}', {"Retry-After": "30"}),
            "action planning",
        )


def test_other_provider_errors_remain_visible():
    with pytest.raises(RuntimeError, match="HTTP 500"):
        LLMClient._raise_http_error(response(500, "provider failure"), "URL discovery")
