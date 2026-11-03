"""Веб-форма и JSON API.

    uvicorn cardgen.web:app --reload      # или: python -m cardgen serve

POST /api/generate принимает тот же JSON, что и CLI, и возвращает карточку
в JSON и Markdown. Ошибки возвращаются с понятным сообщением и кодом:
400 — невалидный вход, 502 — ошибка LLM API, 503 — сервис не настроен.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from starlette.concurrency import run_in_threadpool

from .config import ConfigError, load_settings
from .generator import CardGenerator
from .input_parser import InputError, parse_raw
from .llm import LLMError, create_client
from .render import card_to_markdown

STATIC_DIR = Path(__file__).parent / "static"
EXAMPLES_DIR = Path(__file__).resolve().parent.parent / "examples"
EXAMPLE_DIRS = ("input", "from_feed", "invalid")


def default_generator_factory() -> CardGenerator:
    settings = load_settings()
    return CardGenerator(create_client(settings), max_repair_attempts=settings.max_repair_attempts)


def create_app(generator_factory: Callable[[], CardGenerator] = default_generator_factory) -> FastAPI:
    app = FastAPI(title="AI-помощник для товарных карточек", version="0.1.0")
    state: dict[str, CardGenerator] = {}

    def get_generator() -> CardGenerator:
        if "gen" not in state:
            state["gen"] = generator_factory()
        return state["gen"]

    @app.get("/", include_in_schema=False)
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html", media_type="text/html; charset=utf-8")

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    @app.get("/api/examples")
    def examples() -> dict:
        """Примеры входных данных для кнопки «Подставить пример» в форме."""
        items = {}
        for sub in EXAMPLE_DIRS:
            for path in sorted((EXAMPLES_DIR / sub).glob("*.json")):
                items[f"{sub}/{path.stem}"] = path.read_text(encoding="utf-8")
        return items

    @app.post("/api/generate")
    async def generate(request: Request) -> JSONResponse:
        raw = await request.body()
        try:
            parsed = parse_raw(raw)
        except InputError as exc:
            return JSONResponse(status_code=400, content={"error": "invalid_input", "messages": exc.errors})
        try:
            generator = get_generator()
        except (ConfigError, LLMError) as exc:
            return JSONResponse(status_code=503, content={"error": "not_configured", "messages": [str(exc)]})
        try:
            # Синхронный вызов LLM выполняется в пуле потоков, чтобы не блокировать event loop.
            card = await run_in_threadpool(generator.generate, parsed)
        except LLMError as exc:
            return JSONResponse(status_code=502, content={"error": "llm_error", "messages": [str(exc)]})
        return JSONResponse(content={"card": card.model_dump(), "markdown": card_to_markdown(card)})

    return app


app = create_app()
