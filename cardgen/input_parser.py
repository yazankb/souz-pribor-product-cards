"""Разбор и нормализация входного JSON с понятными сообщениями об ошибках."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .schemas import ProductInput

KNOWN_FIELDS = {"name", "manufacturer", "specs", "description", "category"}
_WS = re.compile(r"\s+")


class InputError(ValueError):
    """Входные данные невозможно обработать. ``errors`` — список сообщений для пользователя."""

    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass
class ParsedInput:
    product: ProductInput
    warnings: list[str] = field(default_factory=list)
    # Характеристики, переданные с пустым значением: попадут в отчёт «данных нет».
    empty_specs: list[str] = field(default_factory=list)


def _clean(text: str) -> str:
    return _WS.sub(" ", text).strip()


def _pairs_hook(warnings: list[str]):
    def hook(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                warnings.append(f"Ключ «{key}» встречается несколько раз — использовано последнее значение.")
            result[key] = value
        return result

    return hook


def load_json(raw: str | bytes) -> tuple[Any, list[str]]:
    """Парсит JSON. Ошибка синтаксиса превращается в InputError с номером строки и столбца."""
    warnings: list[str] = []
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise InputError(["Входные данные не в кодировке UTF-8."]) from exc
    if not raw or not raw.strip():
        raise InputError(["Пустой ввод: ожидается JSON-объект с данными о товаре."])
    try:
        data = json.loads(raw.lstrip("﻿"), object_pairs_hook=_pairs_hook(warnings))
    except json.JSONDecodeError as exc:
        raise InputError(
            [f"Невалидный JSON: {exc.msg} (строка {exc.lineno}, столбец {exc.colno})."]
        ) from exc
    return data, warnings


def _spec_value_to_str(key: str, value: Any, errors: list[str]) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, (int, float)):
        return str(value).replace(".", ",")  # русская запись десятичных
    if isinstance(value, str):
        return _clean(value) or None
    if isinstance(value, list) and all(isinstance(v, (str, int, float)) for v in value):
        joined = "; ".join(_clean(str(v)) for v in value if str(v).strip())
        return joined or None
    errors.append(f"Характеристика «{key}»: значение должно быть строкой, числом или списком строк.")
    return None


def _normalize_specs(raw_specs: Any, errors: list[str]) -> list[tuple[str, Any]]:
    """Принимает specs как объект {"ключ": "значение"} или как список пар [{"name":..,"value":..}]."""
    if raw_specs is None:
        return []
    if isinstance(raw_specs, dict):
        return list(raw_specs.items())
    if isinstance(raw_specs, list):
        pairs = []
        for i, item in enumerate(raw_specs):
            if isinstance(item, dict) and "name" in item:
                pairs.append((item.get("name"), item.get("value")))
            else:
                errors.append(f"specs[{i}]: ожидается объект вида {{\"name\": ..., \"value\": ...}}.")
        return pairs
    errors.append("Поле «specs» должно быть объектом {\"характеристика\": \"значение\"}.")
    return []


def parse_product(data: Any, extra_warnings: list[str] | None = None) -> ParsedInput:
    """Проверяет структуру и нормализует данные. Собирает все ошибки сразу, а не по одной."""
    warnings = list(extra_warnings or [])
    errors: list[str] = []

    if not isinstance(data, dict):
        raise InputError(["Ожидается JSON-объект с полями name, manufacturer, specs, description."])

    def text_field(key: str, required: bool = False) -> str | None:
        value = data.get(key)
        if value is None:
            if required:
                errors.append(f"Поле «{key}» обязательно.")
            return None
        if not isinstance(value, (str, int, float)) or isinstance(value, bool):
            errors.append(f"Поле «{key}» должно быть строкой.")
            return None
        cleaned = _clean(str(value))
        if not cleaned and required:
            errors.append(f"Поле «{key}» не может быть пустым.")
        return cleaned or None

    name = text_field("name", required=True)
    manufacturer = text_field("manufacturer")
    description = text_field("description")
    category = text_field("category")

    specs: dict[str, str] = {}
    empty_specs: list[str] = []
    for key, value in _normalize_specs(data.get("specs"), errors):
        if not isinstance(key, str) or not _clean(key):
            errors.append("В specs есть характеристика без названия.")
            continue
        key = _clean(key)
        value_str = _spec_value_to_str(key, value, errors)
        if value_str is None:
            empty_specs.append(key)
        else:
            specs[key] = value_str

    unknown = sorted(set(data) - KNOWN_FIELDS)
    if unknown:
        warnings.append(f"Неизвестные поля проигнорированы: {', '.join(unknown)}.")

    if errors:
        raise InputError(errors)

    product = ProductInput(
        name=name or "",
        manufacturer=manufacturer,
        specs=specs,
        description=description,
        category=category,
    )
    return ParsedInput(product=product, warnings=warnings, empty_specs=empty_specs)


def parse_raw(raw: str | bytes) -> ParsedInput:
    data, warnings = load_json(raw)
    return parse_product(data, warnings)
