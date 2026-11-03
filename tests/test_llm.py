import json

import httpx
import pytest

from cardgen.config import ConfigError, Settings, load_settings
from cardgen.llm import (
    LLMAuthError,
    LLMError,
    LLMRateLimitError,
    LLMResponseError,
    LLMTimeoutError,
    OpenAICompatibleClient,
)


def _settings(**kw) -> Settings:
    base = dict(provider="openai", model="test-model", api_key="test-key", base_url=None, timeout=5,
                max_retries=2, max_repair_attempts=2, temperature=0.3, json_mode=True)
    base.update(kw)
    return Settings(**base)


def _ok(content='{"a": 1}', finish="stop"):
    return httpx.Response(200, json={"choices": [{"message": {"content": content}, "finish_reason": finish}]})


def _client(handler, **kw):
    sleeps = []
    client = OpenAICompatibleClient(_settings(**kw), http=httpx.Client(transport=httpx.MockTransport(handler)),
                                    sleep=sleeps.append)
    return client, sleeps


def test_success_and_request_shape():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return _ok()

    client, _ = _client(handler)
    assert client.complete("sys", [{"role": "user", "content": "hi"}]) == '{"a": 1}'
    assert seen["url"] == "https://api.openai.com/v1/chat/completions"
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "sys"}
    assert seen["body"]["response_format"] == {"type": "json_object"}


def test_rate_limit_retried_with_retry_after():
    responses = [httpx.Response(429, headers={"retry-after": "3"}, json={}), _ok()]
    client, sleeps = _client(lambda r: responses.pop(0))
    assert client.complete("s", [{"role": "user", "content": "x"}])
    assert sleeps == [3.0]


def test_rate_limit_exhausted():
    client, sleeps = _client(lambda r: httpx.Response(429, json={}))
    with pytest.raises(LLMRateLimitError):
        client.complete("s", [{"role": "user", "content": "x"}])
    assert len(sleeps) == 2  # max_retries=2 → 3 попытки


def test_auth_error_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(401, json={"error": {"message": "bad key"}})

    client, sleeps = _client(handler)
    with pytest.raises(LLMAuthError):
        client.complete("s", [{"role": "user", "content": "x"}])
    assert len(calls) == 1 and sleeps == []


def test_timeout_retried_then_raised():
    def handler(request):
        raise httpx.ReadTimeout("timeout", request=request)

    client, sleeps = _client(handler)
    with pytest.raises(LLMTimeoutError):
        client.complete("s", [{"role": "user", "content": "x"}])
    assert len(sleeps) == 2


def test_server_error_then_success():
    responses = [httpx.Response(503, text="unavailable"), _ok()]
    client, _ = _client(lambda r: responses.pop(0))
    assert client.complete("s", [{"role": "user", "content": "x"}])


@pytest.mark.parametrize("response", [_ok(content=""), _ok(finish="length"), httpx.Response(200, json={"x": 1})])
def test_bad_responses(response):
    client, _ = _client(lambda r: response)
    with pytest.raises(LLMResponseError):
        client.complete("s", [{"role": "user", "content": "x"}])


def test_missing_key_is_config_error(monkeypatch):
    for var in ("LLM_API_KEY", "OPENAI_API_KEY", "LLM_BASE_URL", "LLM_MODEL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(ConfigError, match="LLM_API_KEY"):
        load_settings(env_file=None)


def test_unknown_provider(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "foo")
    with pytest.raises(ConfigError, match="LLM_PROVIDER"):
        load_settings(env_file=None)


def test_local_endpoint_needs_no_key(monkeypatch):
    for var in ("LLM_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    assert load_settings(env_file=None).api_key is None


def test_mock_override_ignores_model(monkeypatch):
    monkeypatch.setenv("LLM_MODEL", "gpt-x")
    settings = load_settings(provider_override="mock", env_file=None)
    assert settings.provider == "mock" and settings.model == "mock"


class _FakeMessages:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.kwargs = response, error, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        if self.error:
            raise self.error
        return self.response


def _anthropic_client(response=None, error=None):
    pytest.importorskip("anthropic")
    from types import SimpleNamespace

    from cardgen.llm import AnthropicClient

    client = AnthropicClient(_settings(provider="anthropic", model="claude-test"))
    client._client = SimpleNamespace(messages=_FakeMessages(response, error))
    return client


def _anthropic_response(text, stop_reason="end_turn"):
    from types import SimpleNamespace

    return SimpleNamespace(stop_reason=stop_reason, content=[SimpleNamespace(type="text", text=text)])


def test_anthropic_success_and_request_shape():
    client = _anthropic_client(_anthropic_response('{"a": 1}'))
    assert client.complete("sys", [{"role": "user", "content": "x"}]) == '{"a": 1}'
    kwargs = client._client.messages.kwargs
    assert kwargs["system"] == "sys" and kwargs["model"] == "claude-test"
    assert "temperature" not in kwargs


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_anthropic_bad_stop_reason(stop_reason):
    client = _anthropic_client(_anthropic_response("x", stop_reason))
    with pytest.raises(LLMResponseError):
        client.complete("s", [{"role": "user", "content": "x"}])


def test_anthropic_connection_error_mapped():
    anthropic = pytest.importorskip("anthropic")
    error = anthropic.APIConnectionError(request=httpx.Request("POST", "https://api.anthropic.com"))
    client = _anthropic_client(error=error)
    with pytest.raises(LLMError, match="Сетевая ошибка"):
        client.complete("s", [{"role": "user", "content": "x"}])
