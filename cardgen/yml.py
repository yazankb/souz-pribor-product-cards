"""Конвертер оффера из YML-фида (Яндекс.Маркет) во входной JSON сервиса.

Фид читается потоково (iterparse), поэтому большой файл не загружается в память целиком.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

# Служебные параметры фида — не технические характеристики.
SERVICE_PARAMS = {"артикул", "код товара", "штрихкод", "штрих-код", "ean", "код"}

_TAGS = re.compile(r"<[^>]+>")
_WS = re.compile(r"[ \t\r\f\v ]+")


@dataclass
class Offer:
    id: str
    name: str
    type_prefix: str | None
    vendor: str | None
    category_id: str | None
    url: str | None
    description: str | None
    params: list[tuple[str, str]] = field(default_factory=list)


def html_to_text(raw: str | None) -> str | None:
    if not raw:
        return None
    text = re.sub(r"(?i)<br\s*/?>|</p>|</li>", "\n", raw)
    text = html.unescape(_TAGS.sub(" ", text))
    lines = [_WS.sub(" ", line).strip() for line in text.splitlines()]
    text = "\n".join(line for line in lines if line)
    return text or None


def _text(elem: ET.Element, tag: str) -> str | None:
    child = elem.find(tag)
    if child is None or child.text is None:
        return None
    return child.text.strip() or None


def iter_feed(path: str | Path) -> tuple[dict[str, str], Iterator[Offer]]:
    """Возвращает словарь категорий и генератор офферов."""
    categories: dict[str, str] = {}

    def offers() -> Iterator[Offer]:
        for _, elem in ET.iterparse(str(path), events=("end",)):
            if elem.tag == "category":
                categories[elem.get("id", "")] = (elem.text or "").strip()
            elif elem.tag == "offer":
                params = []
                for p in elem.findall("param"):
                    name = (p.get("name") or "").strip()
                    value = (p.text or "").strip()
                    unit = (p.get("unit") or "").strip()
                    if name:
                        params.append((name, f"{value} {unit}".strip() if unit else value))
                yield Offer(
                    id=elem.get("id", ""),
                    name=_text(elem, "name") or _text(elem, "model") or "",
                    type_prefix=_text(elem, "typePrefix"),
                    vendor=_text(elem, "vendor"),
                    category_id=_text(elem, "categoryId"),
                    url=_text(elem, "url"),
                    description=html_to_text(_text(elem, "description")),
                    params=params,
                )
                elem.clear()

    return categories, offers()


def technical_params(offer: Offer) -> list[tuple[str, str]]:
    return [(k, v) for k, v in offer.params if k.lower() not in SERVICE_PARAMS]


def offer_to_input(offer: Offer, categories: dict[str, str]) -> dict:
    """Оффер → входной JSON. Пустые поля передаются явно, чтобы сервис отчитался о пробелах."""
    name = offer.name
    if offer.type_prefix and offer.type_prefix.lower() not in name.lower():
        prefix = offer.type_prefix[0].upper() + offer.type_prefix[1:]
        name = f"{prefix} {name}"
    return {
        "name": name,
        "manufacturer": offer.vendor or "",
        "category": categories.get(offer.category_id or "", "") or None,
        "specs": dict(technical_params(offer)),
        "description": offer.description or "",
    }


def find_offer(path: str | Path, offer_id: str) -> tuple[Offer, dict[str, str]]:
    categories, offers = iter_feed(path)
    for offer in offers:
        if offer.id == offer_id:
            return offer, categories
    raise KeyError(f"Оффер с id={offer_id} не найден в фиде.")
