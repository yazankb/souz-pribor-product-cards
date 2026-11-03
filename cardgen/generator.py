"""Оркестрация: вход → детерминированные характеристики → LLM → проверка → цикл исправлений → карточка."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone

from pydantic import ValidationError

from .input_parser import ParsedInput
from .llm import LLMClient, LLMError, LLMResponseError, Message
from .prompts import SYSTEM_PROMPT, build_repair_prompt, build_user_prompt
from .schemas import (
    NO_DATA,
    CardMeta,
    LLMDraft,
    ProductCard,
    ValidationIssue,
    ValidationReport,
)
from .specs import build_specs_report, is_sufficient
from .validation import validate_draft

_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_llm_json(text: str) -> LLMDraft:
    """Извлекает JSON из ответа модели (допускает обёртку ```json) и проверяет схему."""
    cleaned = _FENCE.sub("", text.strip())
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("в ответе нет JSON-объекта")
    try:
        data = json.loads(cleaned[start:end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"невалидный JSON ({exc.msg})") from exc
    try:
        draft = LLMDraft.model_validate(data)
    except ValidationError as exc:
        fields = ", ".join(".".join(str(p) for p in err["loc"]) for err in exc.errors())
        raise ValueError(f"не хватает или неверного типа поля: {fields}") from exc
    # Нормализуем пробелы по краям, чтобы длины считались честно.
    draft.seo_title = draft.seo_title.strip()
    draft.seo_description = draft.seo_description.strip()
    draft.search_queries = [q.strip() for q in draft.search_queries if q.strip()]
    return draft


def _severity(issues: list[ValidationIssue]) -> tuple[int, int]:
    """Для выбора лучшей попытки: выдуманные факты хуже, чем ошибки длины."""
    grounding = sum(1 for i in issues if i.code.startswith("ungrounded"))
    return grounding, len(issues)


class CardGenerator:
    def __init__(self, llm: LLMClient, max_repair_attempts: int = 2):
        self.llm = llm
        self.max_repair_attempts = max_repair_attempts

    def _meta(self, instrument_type: str) -> CardMeta:
        return CardMeta(
            provider=self.llm.provider,
            model=self.llm.model,
            generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            instrument_type=instrument_type,
        )

    def generate(self, parsed: ParsedInput) -> ProductCard:
        product = parsed.product
        report = build_specs_report(parsed)
        base = dict(
            product_name=product.name,
            manufacturer=product.manufacturer or NO_DATA,
            key_characteristics=report.characteristics,
            missing_data=report.missing,
            input_warnings=parsed.warnings,
            meta=self._meta(report.profile.title),
        )

        if not is_sufficient(parsed):
            return ProductCard(
                status="insufficient_data",
                needs_clarification=[
                    "Недостаточно данных для генерации: нужны хотя бы характеристики (specs) "
                    "или текстовое описание / фрагмент паспорта. Запрос в LLM не отправлялся, "
                    "чтобы модель не придумывала характеристики.",
                ],
                validation=ValidationReport(passed=False, attempts=0),
                **base,
            )

        messages: list[Message] = [{"role": "user", "content": build_user_prompt(product, report)}]
        best: tuple[LLMDraft, list[ValidationIssue]] | None = None
        attempts = 0
        last_parse_error: str | None = None

        for attempt in range(1, self.max_repair_attempts + 2):
            try:
                raw = self.llm.complete(SYSTEM_PROMPT, messages)
            except LLMError:
                if best is None:
                    raise
                break  # исправление не удалось — отдаём лучший из уже полученных вариантов
            attempts = attempt
            try:
                draft = parse_llm_json(raw)
            except ValueError as exc:
                last_parse_error = str(exc)
                messages += [{"role": "assistant", "content": raw},
                             {"role": "user", "content": build_repair_prompt([], last_parse_error)}]
                continue

            issues = validate_draft(draft, product)
            if best is None or _severity(issues) <= _severity(best[1]):
                best = (draft, issues)
            if not issues:
                break
            messages += [{"role": "assistant", "content": raw},
                         {"role": "user", "content": build_repair_prompt(issues)}]

        if best is None:
            raise LLMResponseError(
                f"Модель {attempts} раз(а) вернула ответ не по схеме: {last_parse_error}."
            )

        draft, issues = best
        clarifications = [n.strip() for n in draft.notes if n.strip()]
        return ProductCard(
            status="ok" if not issues else "needs_review",
            seo_title=draft.seo_title,
            seo_title_length=len(draft.seo_title),
            seo_description=draft.seo_description,
            seo_description_length=len(draft.seo_description),
            search_queries=draft.search_queries,
            commercial_block=draft.commercial,
            needs_clarification=clarifications,
            validation=ValidationReport(passed=not issues, attempts=attempts, issues=issues),
            **base,
        )
