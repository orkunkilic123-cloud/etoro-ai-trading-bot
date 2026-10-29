"""Offline, mocked checks for isolated free-tier commentary."""
import httpx
import pytest

from etoro_demo_bot.free_llm import FreeLLMError, analyze_research


def test_network_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FREE_LLM_MODEL", "test-model")
    monkeypatch.setenv("FREE_LLM_API_KEY", "placeholder")
    monkeypatch.delenv("FREE_LLM_NETWORK_ENABLED", raising=False)
    with pytest.raises(FreeLLMError, match="Network disabled"):
        analyze_research("public data")


def test_mocked_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FREE_LLM_MODEL", "test-model")
    monkeypatch.setenv("FREE_LLM_NETWORK_ENABLED", "1")
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.groq.com"
        return httpx.Response(200, json={"choices": [{"message": {"content": "Uncertain."}}]})
    result = analyze_research("public data", api_key="placeholder", transport=httpx.MockTransport(respond))
    assert result.text == "Uncertain."


def test_http_failure_is_sanitized(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FREE_LLM_MODEL", "test-model")
    monkeypatch.setenv("FREE_LLM_NETWORK_ENABLED", "1")
    transport = httpx.MockTransport(lambda request: httpx.Response(429, text="secret-value"))
    with pytest.raises(FreeLLMError) as err:
        analyze_research("public data", api_key="placeholder", transport=transport)
    assert "secret-value" not in str(err.value)
