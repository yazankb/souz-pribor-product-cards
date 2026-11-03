"""Пост-проверка ответа LLM: форматные ограничения и защита от выдуманных фактов.

Проверка «заземления» (grounding) детерминированная:
1. Каждое число в сгенерированном тексте должно встречаться во входных данных.
2. «Рискованные» технические термины (интерфейсы, взрывозащита, поверка, ГОСТ,
   материалы, гарантия…) допустимы, только если они есть во входных данных.
Это не ловит все возможные выдумки (например, число, записанное словами), но
отсекает самые опасные для B2B-карточки: неверные цифры и несуществующие опции.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .schemas import (
    QUERIES_MAX,
    QUERIES_MIN,
    SEO_DESCRIPTION_MAX,
    SEO_DESCRIPTION_MIN,
    SEO_TITLE_MAX,
    LLMDraft,
    ProductInput,
    ValidationIssue,
)

# Число: «1,6», «0.25», «10 000» (пробел-разделитель тысяч), «02».
_NUMBER = re.compile(r"\d+(?:[   ]\d{3})*(?:[.,]\d+)?")

# (регулярное выражение, человекочитаемое название)
RISKY_TERMS: tuple[tuple[str, str], ...] = (
    (r"взрыв", "взрывозащита"),
    (r"\bex\b", "маркировка Ex"),
    (r"\bip\s?\d", "степень защиты IP"),
    (r"rs-?485", "интерфейс RS-485"),
    (r"rs-?232", "интерфейс RS-232"),
    (r"modbus", "протокол Modbus"),
    (r"\bhart\b", "протокол HART"),
    (r"profibus|profinet", "Profibus/Profinet"),
    (r"ethernet", "Ethernet"),
    (r"\busb\b", "USB"),
    (r"bluetooth", "Bluetooth"),
    (r"wi-?fi", "Wi-Fi"),
    (r"\bgsm\b", "GSM"),
    (r"поверк|поверен|межповероч", "поверка"),
    (r"госреестр|реестр[а-я]* средств измерен|утвержден[а-я]* тип", "Госреестр СИ"),
    (r"сертифик", "сертификация"),
    (r"декларац[а-я]* соответств", "декларация соответствия"),
    (r"\bгост\b", "ГОСТ"),
    (r"гаранти", "гарантия"),
    (r"нержаве", "нержавеющая сталь"),
    (r"латун", "латунь"),
    (r"бронз", "бронза"),
    (r"алюмини", "алюминий"),
    (r"глицерин|гидрозаполн|жидкостн[а-я]* заполн", "заполнение корпуса"),
    (r"виброуст|вибростойк|виброзащ", "виброустойчивость"),
    (r"агрессивн", "работа с агрессивными средами"),
    (r"пищев", "пищевое исполнение"),
    (r"кислород", "кислородное исполнение"),
    (r"аммиак", "аммиачное исполнение"),
    (r"морозостойк|арктич", "морозостойкое исполнение"),
)


def _normalize_number(token: str) -> str:
    token = re.sub(r"[   ]", "", token).replace(",", ".")
    try:
        value = Decimal(token).normalize()
    except InvalidOperation:
        return token
    return format(value, "f")


def numbers_in(text: str) -> set[str]:
    """Все числа в тексте в нормализованном виде (включая части «10 000» → 10000, 10, 0)."""
    found: set[str] = set()
    for match in _NUMBER.finditer(text):
        token = match.group(0)
        found.add(_normalize_number(token))
        for part in re.split(r"[   ]", token):
            found.add(_normalize_number(part))
    return found


def input_corpus(product: ProductInput) -> str:
    parts = [product.name, product.manufacturer or "", product.category or "", product.description or ""]
    for key, value in product.specs.items():
        parts.append(f"{key}: {value}")
    return "\n".join(parts)


def _ungrounded_numbers(text: str, allowed: set[str]) -> list[str]:
    bad: list[str] = []
    for match in _NUMBER.finditer(text):
        token = match.group(0)
        if _normalize_number(token) in allowed:
            continue
        parts = re.split(r"[   ]", token)
        if len(parts) > 1 and all(_normalize_number(p) in allowed for p in parts):
            continue  # «0 100» и т.п. — каждое число по отдельности есть во входе
        if token not in bad:
            bad.append(token)
    return bad


def generated_texts(draft: LLMDraft) -> dict[str, str]:
    """Тексты, которые попадут на сайт или к менеджеру (notes — служебные, не проверяются)."""
    texts = {
        "seo_title": draft.seo_title,
        "seo_description": draft.seo_description,
        "commercial.summary": draft.commercial.summary,
    }
    for i, q in enumerate(draft.search_queries):
        texts[f"search_queries[{i}]"] = q
    for i, a in enumerate(draft.commercial.audience):
        texts[f"commercial.audience[{i}]"] = a
    for i, t in enumerate(draft.commercial.tasks):
        texts[f"commercial.tasks[{i}]"] = t
    return texts


def check_grounding(draft: LLMDraft, product: ProductInput) -> list[ValidationIssue]:
    corpus = input_corpus(product)
    corpus_lower = corpus.lower()
    allowed_numbers = numbers_in(corpus)
    issues: list[ValidationIssue] = []

    for field, text in generated_texts(draft).items():
        for token in _ungrounded_numbers(text, allowed_numbers):
            issues.append(ValidationIssue(
                code="ungrounded_number",
                field=field,
                message=f"Число «{token}» отсутствует во входных данных.",
            ))
        lower = text.lower()
        for pattern, label in RISKY_TERMS:
            if re.search(pattern, lower) and not re.search(pattern, corpus_lower):
                issues.append(ValidationIssue(
                    code="ungrounded_term",
                    field=field,
                    message=f"Упомянуто «{label}», но во входных данных этого нет.",
                ))
    return issues


def check_format(draft: LLMDraft) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    title_len = len(draft.seo_title.strip())
    if title_len == 0:
        issues.append(ValidationIssue(code="empty", field="seo_title", message="SEO title пустой."))
    elif title_len > SEO_TITLE_MAX:
        issues.append(ValidationIssue(
            code="length", field="seo_title",
            message=f"Длина SEO title {title_len} символов, допустимо не более {SEO_TITLE_MAX}.",
        ))

    desc_len = len(draft.seo_description.strip())
    if not SEO_DESCRIPTION_MIN <= desc_len <= SEO_DESCRIPTION_MAX:
        issues.append(ValidationIssue(
            code="length", field="seo_description",
            message=f"Длина SEO description {desc_len} символов, требуется {SEO_DESCRIPTION_MIN}–{SEO_DESCRIPTION_MAX}.",
        ))

    queries = [q.strip().lower() for q in draft.search_queries if q.strip()]
    if len(set(queries)) != len(queries):
        issues.append(ValidationIssue(code="duplicates", field="search_queries",
                                      message="Поисковые запросы повторяются."))
    if not QUERIES_MIN <= len(set(queries)) <= QUERIES_MAX:
        issues.append(ValidationIssue(
            code="count", field="search_queries",
            message=f"Уникальных поисковых запросов {len(set(queries))}, требуется {QUERIES_MIN}–{QUERIES_MAX}.",
        ))

    if not draft.commercial.audience:
        issues.append(ValidationIssue(code="empty", field="commercial.audience",
                                      message="Не указано, кому подходит прибор."))
    if not draft.commercial.tasks:
        issues.append(ValidationIssue(code="empty", field="commercial.tasks",
                                      message="Не указано, какие задачи решает прибор."))
    if not draft.commercial.summary.strip():
        issues.append(ValidationIssue(code="empty", field="commercial.summary",
                                      message="Пустое краткое резюме для менеджера."))
    return issues


def validate_draft(draft: LLMDraft, product: ProductInput) -> list[ValidationIssue]:
    return check_format(draft) + check_grounding(draft, product)
