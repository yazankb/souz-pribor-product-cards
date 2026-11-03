"""Клиенты LLM: OpenAI-совместимый API (OpenAI, OpenRouter, Ollama, vLLM…), Anthropic.

Все клиенты реализуют один метод ``complete(system, messages) -> str`` и
бросают исключения из иерархии ``LLMError`` с понятным сообщением.
"""

from __future__ import annotations

import random
import time
from typing import Callable, Protocol

import httpx

from .config import Settings

Message = dict[str, str]  # {"role": "user" | "assistant", "content": "..."}


class LLMError(RuntimeError):
    """Базовая ошибка обращения к LLM (сообщение показывается пользователю)."""


class LLMAuthError(LLMError):
    pass


class LLMRateLimitError(LLMError):
    pass


class LLMTimeoutError(LLMError):
    pass


class LLMResponseError(LLMError):
    pass


class LLMClient(Protocol):
    provider: str
    model: str

    def complete(self, system: str, messages: list[Message]) -> str: ...


def _retry_after_seconds(response: httpx.Response | None) -> float | None:
    if response is None:
        return None
    raw = response.headers.get("retry-after")
    try:
        return float(raw) if raw else None
    except ValueError:
        return None


class OpenAICompatibleClient:
    """Chat Completions API. Подходит для OpenAI, OpenRouter, DeepSeek, Ollama, vLLM и т.п."""

    provider = "openai"
    RETRYABLE_STATUS = {408, 409, 429, 500, 502, 503, 504}

    def __init__(self, settings: Settings, http: httpx.Client | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.model = settings.model
        self.settings = settings
        self.base_url = (settings.base_url or "https://api.openai.com/v1").rstrip("/")
        self._http = http or httpx.Client(timeout=settings.timeout)
        self._sleep = sleep

    def complete(self, system: str, messages: list[Message]) -> str:
        payload: dict = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
        }
        if self.settings.temperature is not None:
            payload["temperature"] = self.settings.temperature
        if self.settings.json_mode:
            payload["response_format"] = {"type": "json_object"}
        headers = {"Content-Type": "application/json"}
        if self.settings.api_key:
            headers["Authorization"] = f"Bearer {self.settings.api_key}"

        last_error: LLMError | None = None
        for attempt in range(self.settings.max_retries + 1):
            response: httpx.Response | None = None
            try:
                response = self._http.post(f"{self.base_url}/chat/completions", json=payload, headers=headers)
            except httpx.TimeoutException:
                last_error = LLMTimeoutError(f"Превышено время ожидания ответа LLM ({self.settings.timeout:.0f} с).")
            except httpx.HTTPError as exc:
                last_error = LLMError(f"Сетевая ошибка при обращении к LLM: {exc.__class__.__name__}.")
            else:
                if response.status_code == 200:
                    return self._extract_text(response)
                last_error = self._status_error(response)
                if response.status_code not in self.RETRYABLE_STATUS:
                    raise last_error
            if attempt < self.settings.max_retries:
                delay = _retry_after_seconds(response) or min(2 ** attempt + random.random(), 30)
                self._sleep(delay)
        assert last_error is not None
        raise last_error

    @staticmethod
    def _status_error(response: httpx.Response) -> LLMError:
        code = response.status_code
        try:
            detail = response.json().get("error", {})
            detail = detail.get("message", "") if isinstance(detail, dict) else str(detail)
        except (ValueError, AttributeError):
            detail = response.text[:200]
        if code in (401, 403):
            return LLMAuthError(f"LLM API отклонил ключ (HTTP {code}). Проверьте LLM_API_KEY.")
        if code == 429:
            return LLMRateLimitError("Превышен лимит запросов к LLM API (HTTP 429). Повторите позже.")
        if code == 404:
            return LLMError(f"Модель или endpoint не найдены (HTTP 404): {detail}. Проверьте LLM_MODEL и LLM_BASE_URL.")
        return LLMError(f"Ошибка LLM API (HTTP {code}): {detail}")

    @staticmethod
    def _extract_text(response: httpx.Response) -> str:
        try:
            data = response.json()
            choice = data["choices"][0]
            content = choice["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise LLMResponseError("Неожиданный формат ответа LLM API.") from exc
        if choice.get("finish_reason") == "length":
            raise LLMResponseError("Ответ модели обрезан по лимиту токенов.")
        if not content or not content.strip():
            raise LLMResponseError("Модель вернула пустой ответ.")
        return content


class AnthropicClient:
    """Claude через официальный SDK ``anthropic`` (повторы 429/5xx/таймаутов делает SDK)."""

    provider = "anthropic"

    def __init__(self, settings: Settings):
        try:
            import anthropic
        except ImportError as exc:  # pragma: no cover
            raise LLMError("Для LLM_PROVIDER=anthropic установите пакет: pip install anthropic") from exc
        self._anthropic = anthropic
        self.model = settings.model
        kwargs: dict = {"api_key": settings.api_key, "timeout": settings.timeout,
                        "max_retries": settings.max_retries}
        if settings.base_url:
            kwargs["base_url"] = settings.base_url
        self._client = anthropic.Anthropic(**kwargs)

    def complete(self, system: str, messages: list[Message]) -> str:
        a = self._anthropic
        try:
            response = self._client.messages.create(
                model=self.model, max_tokens=16000, system=system, messages=messages,
            )
        except a.AuthenticationError as exc:
            raise LLMAuthError("Anthropic API отклонил ключ. Проверьте LLM_API_KEY.") from exc
        except a.PermissionDeniedError as exc:
            raise LLMAuthError("У ключа нет доступа к этой модели или API.") from exc
        except a.NotFoundError as exc:
            raise LLMError(f"Модель {self.model!r} не найдена. Проверьте LLM_MODEL.") from exc
        except a.RateLimitError as exc:
            raise LLMRateLimitError("Превышен лимит запросов к Anthropic API (HTTP 429).") from exc
        except a.APITimeoutError as exc:
            raise LLMTimeoutError("Превышено время ожидания ответа Anthropic API.") from exc
        except a.APIStatusError as exc:
            raise LLMError(f"Ошибка Anthropic API (HTTP {exc.status_code}).") from exc
        except a.APIConnectionError as exc:
            raise LLMError("Сетевая ошибка при обращении к Anthropic API.") from exc

        if response.stop_reason == "refusal":
            raise LLMResponseError("Модель отказалась отвечать на запрос.")
        if response.stop_reason == "max_tokens":
            raise LLMResponseError("Ответ модели обрезан по лимиту токенов.")
        text = "".join(block.text for block in response.content if block.type == "text")
        if not text.strip():
            raise LLMResponseError("Модель вернула пустой ответ.")
        return text


def create_client(settings: Settings) -> LLMClient:
    if settings.provider == "anthropic":
        return AnthropicClient(settings)
    return OpenAICompatibleClient(settings)
