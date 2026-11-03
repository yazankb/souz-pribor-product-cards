import json

from fastapi.testclient import TestClient

from cardgen.config import ConfigError
from cardgen.generator import CardGenerator
from cardgen.llm import LLMTimeoutError
from cardgen.web import create_app

from .conftest import MANOMETER, FakeLLM, make_draft


def _client(llm=None, factory=None):
    factory = factory or (lambda: CardGenerator(llm))
    return TestClient(create_app(factory))


def test_index_page():
    resp = _client(FakeLLM([make_draft()])).get("/")
    assert resp.status_code == 200 and "Сгенерировать" in resp.text


def test_generate_ok():
    resp = _client(FakeLLM([make_draft()])).post("/api/generate", content=json.dumps(MANOMETER, ensure_ascii=False))
    assert resp.status_code == 200
    data = resp.json()
    assert data["card"]["status"] == "ok"
    assert data["markdown"].startswith("# Черновик карточки")


def test_invalid_json_400():
    resp = _client(FakeLLM([make_draft()])).post("/api/generate", content='{"name": ')
    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_input"


def test_validation_error_400():
    resp = _client(FakeLLM([make_draft()])).post("/api/generate", json={"specs": {}})
    assert resp.status_code == 400
    assert any("name" in m for m in resp.json()["messages"])


def test_llm_error_502():
    resp = _client(FakeLLM([LLMTimeoutError("таймаут")])).post("/api/generate", json=MANOMETER)
    assert resp.status_code == 502
    assert resp.json()["messages"] == ["таймаут"]


def test_not_configured_503():
    def factory():
        raise ConfigError("Не задан ключ API")

    resp = _client(factory=factory).post("/api/generate", json=MANOMETER)
    assert resp.status_code == 503


def test_saved_results_listed():
    data = _client(FakeLLM([make_draft()])).get("/api/results").json()
    assert data, "examples/output должен содержать готовые карточки"
    for item in data.values():
        assert item["card"]["status"] in ("ok", "needs_review", "insufficient_data")
        assert item["markdown"].startswith("# Черновик карточки")


def test_health_reports_missing_key(monkeypatch):
    from cardgen import web

    def no_key():
        raise ConfigError("Не задан ключ API")

    monkeypatch.setattr(web, "load_settings", no_key)
    data = _client(FakeLLM([make_draft()])).get("/api/health").json()
    assert data["configured"] is False and "ключ" in data["message"]
