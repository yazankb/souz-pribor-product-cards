"""Настройки из переменных окружения (и необязательного файла .env).

Ключ API никогда не хранится в коде: он читается из окружения или из .env,
который перечислен в .gitignore.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

try:  # python-dotenv необязателен: без него просто читаем окружение
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    load_dotenv = None

SUPPORTED_PROVIDERS = ("openai", "anthropic", "mock")

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "anthropic": "claude-opus-5-5",
    "mock": "mock",
}

# Стандартные имена переменных провайдеров — используются, если LLM_API_KEY не задан.
PROVIDER_KEY_VARS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


class ConfigError(ValueError):
    """Неверная или неполная конфигурация."""


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"Переменная {name} должна быть числом, получено: {raw!r}") from exc


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"Переменная {name} должна быть целым числом, получено: {raw!r}") from exc


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on", "да")


@dataclass(frozen=True)
class Settings:
    provider: str
    model: str
    api_key: str | None
    base_url: str | None
    timeout: float
    max_retries: int
    max_repair_attempts: int
    temperature: float | None  # None — не передавать (некоторые модели принимают только значение по умолчанию)
    json_mode: bool

    def validate(self) -> None:
        if self.provider not in SUPPORTED_PROVIDERS:
            raise ConfigError(
                f"Неизвестный LLM_PROVIDER={self.provider!r}. "
                f"Допустимые значения: {', '.join(SUPPORTED_PROVIDERS)}."
            )
        if self.provider == "mock":
            return
        if not self.api_key and not self._is_local_endpoint():
            key_var = PROVIDER_KEY_VARS.get(self.provider, "LLM_API_KEY")
            raise ConfigError(
                f"Не задан ключ API: укажите LLM_API_KEY (или {key_var}) в окружении или в файле .env. "
                "Для работы без ключа используйте режим --mock."
            )

    def _is_local_endpoint(self) -> bool:
        # Локальные OpenAI-совместимые серверы (Ollama, vLLM) обычно не требуют ключа.
        return bool(self.base_url) and any(
            host in self.base_url for host in ("localhost", "127.0.0.1", "[::1]")
        )


def load_settings(provider_override: str | None = None, env_file: str | Path | None = ".env") -> Settings:
    """Собирает настройки из окружения. ``provider_override`` используется для флага --mock."""
    if load_dotenv is not None and env_file and Path(env_file).is_file():
        load_dotenv(env_file, override=False)

    provider = (provider_override or os.getenv("LLM_PROVIDER", "openai")).strip().lower()
    api_key = os.getenv("LLM_API_KEY", "").strip() or os.getenv(PROVIDER_KEY_VARS.get(provider, ""), "").strip()
    settings = Settings(
        provider=provider,
        model="mock" if provider == "mock" else (os.getenv("LLM_MODEL", "").strip() or DEFAULT_MODELS.get(provider, "")),
        api_key=api_key or None,
        base_url=os.getenv("LLM_BASE_URL", "").strip() or None,
        timeout=_env_float("LLM_TIMEOUT", 60.0),
        max_retries=_env_int("LLM_MAX_RETRIES", 3),
        max_repair_attempts=_env_int("LLM_MAX_REPAIR_ATTEMPTS", 2),
        temperature=(None if os.getenv("LLM_TEMPERATURE", "").strip().lower() == "none"
                     else _env_float("LLM_TEMPERATURE", 0.3)),
        json_mode=_env_bool("LLM_JSON_MODE", True),
    )
    settings.validate()
    return settings
