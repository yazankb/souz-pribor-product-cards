"""Представление карточки в Markdown для контент-менеджера."""

from __future__ import annotations

from .schemas import SEO_DESCRIPTION_MAX, SEO_DESCRIPTION_MIN, SEO_TITLE_MAX, ProductCard

STATUS_LABELS = {
    "ok": "Готово к вычитке — автоматические проверки пройдены",
    "needs_review": "Требует проверки — см. раздел «Автоматическая проверка»",
    "insufficient_data": "Недостаточно данных — карточка не сгенерирована",
}


def _md_cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def card_to_markdown(card: ProductCard) -> str:
    out: list[str] = [
        f"# Черновик карточки: {card.product_name}",
        "",
        f"**Статус:** {STATUS_LABELS[card.status]}  ",
        f"**Производитель:** {card.manufacturer}  ",
        f"**Тип прибора (авто):** {card.meta.instrument_type}",
        "",
    ]

    if card.seo_title is not None:
        out += [
            f"## SEO title ({card.seo_title_length}/{SEO_TITLE_MAX} символов)",
            "",
            "```text",
            card.seo_title,
            "```",
            "",
            f"## SEO description ({card.seo_description_length} символов, норма {SEO_DESCRIPTION_MIN}–{SEO_DESCRIPTION_MAX})",
            "",
            card.seo_description or "",
            "",
        ]

    out += ["## Ключевые характеристики", "", "| Характеристика | Значение |", "|---|---|"]
    for ch in card.key_characteristics:
        value = f"*{ch.value}*" if ch.source == "missing" else _md_cell(ch.value)
        out.append(f"| {_md_cell(ch.name)} | {value} |")
    out.append("")
    out.append("_Значения перенесены из входных данных без изменений; «данных нет» — поле не заполнено._")
    out.append("")

    if card.search_queries:
        out += ["## Поисковые запросы", ""]
        out += [f"{i}. {q}" for i, q in enumerate(card.search_queries, 1)]
        out.append("")

    if card.commercial_block:
        cb = card.commercial_block
        out += ["## Для менеджера", "", "**Кому подходит:**", ""]
        out += [f"- {a}" for a in cb.audience]
        out += ["", "**Какие задачи решает:**", ""]
        out += [f"- {t}" for t in cb.tasks]
        out += ["", f"**Коротко для клиента:** {cb.summary}", ""]

    if card.missing_data or card.needs_clarification:
        out += ["## Недостающие данные и что уточнить", ""]
        out += [f"- **{m.field}** — {m.comment}" for m in card.missing_data]
        out += [f"- {c}" for c in card.needs_clarification]
        out.append("")

    if card.input_warnings:
        out += ["## Предупреждения по входным данным", ""]
        out += [f"- {w}" for w in card.input_warnings]
        out.append("")

    out += ["## Автоматическая проверка", ""]
    v = card.validation
    if card.status == "insufficient_data":
        out.append("- Генерация не выполнялась.")
    elif v.passed:
        out.append(f"- Пройдена (попыток генерации: {v.attempts}): длины полей в норме, "
                   "все числа и технические термины в текстах есть во входных данных.")
    else:
        out.append(f"- Есть замечания после {v.attempts} попыток — исправьте вручную перед публикацией:")
        out += [f"  - `{i.field}`: {i.message}" for i in v.issues]
    source = ("LLM не вызывалась" if card.status == "insufficient_data"
              else f"Модель: {card.meta.provider} / {card.meta.model}")
    out += ["", "---", f"_{source}; сформировано {card.meta.generated_at}._", ""]
    return "\n".join(out)
