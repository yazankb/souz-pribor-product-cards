"""Модели данных: вход, ответ LLM и итоговая карточка."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Ограничения из ТЗ
SEO_TITLE_MAX = 70
SEO_DESCRIPTION_MIN = 800
SEO_DESCRIPTION_MAX = 1200
QUERIES_MIN = 3
QUERIES_MAX = 5

NO_DATA = "данных нет"


class ProductInput(BaseModel):
    """Нормализованные входные данные о товаре."""

    name: str
    manufacturer: str | None = None
    specs: dict[str, str] = Field(default_factory=dict)
    description: str | None = None
    category: str | None = None


class Commercial(BaseModel):
    audience: list[str] = Field(default_factory=list, description="Кому подходит прибор")
    tasks: list[str] = Field(default_factory=list, description="Какие задачи решает")
    summary: str = ""


class LLMDraft(BaseModel):
    """Контракт ответа модели: только текстовые поля, без технических таблиц."""

    seo_title: str
    seo_description: str
    search_queries: list[str]
    commercial: Commercial
    notes: list[str] = Field(default_factory=list, description="Замечания модели о пробелах и противоречиях")


class Characteristic(BaseModel):
    name: str
    value: str
    source: Literal["input", "missing"]


class MissingField(BaseModel):
    field: str
    comment: str


class ValidationIssue(BaseModel):
    code: str
    field: str
    message: str


class ValidationReport(BaseModel):
    passed: bool
    attempts: int
    issues: list[ValidationIssue] = Field(default_factory=list)


class CardMeta(BaseModel):
    provider: str
    model: str
    generated_at: str
    instrument_type: str


class ProductCard(BaseModel):
    """Черновик карточки для контент-менеджера."""

    status: Literal["ok", "needs_review", "insufficient_data"]
    product_name: str
    manufacturer: str
    seo_title: str | None = None
    seo_title_length: int | None = None
    seo_description: str | None = None
    seo_description_length: int | None = None
    key_characteristics: list[Characteristic] = Field(default_factory=list)
    search_queries: list[str] = Field(default_factory=list)
    commercial_block: Commercial | None = None
    missing_data: list[MissingField] = Field(default_factory=list)
    needs_clarification: list[str] = Field(default_factory=list)
    input_warnings: list[str] = Field(default_factory=list)
    validation: ValidationReport
    meta: CardMeta
