from pathlib import Path

import pytest

from cardgen.input_parser import parse_product
from cardgen.yml import find_offer, html_to_text, offer_to_input

FEED = """<?xml version="1.0" encoding="UTF-8"?>
<yml_catalog date="2026-11-03T08:00:00+03:00"><shop>
  <categories><category id="1">Манометры</category></categories>
  <offers>
    <offer id="10" available="true">
      <name>ДМ 02-100</name>
      <typePrefix>манометр показывающий</typePrefix>
      <categoryId>1</categoryId>
      <vendor>Манотомь</vendor>
      <description><![CDATA[<p>Для измерения <b>избыточного</b> давления.</p><ul><li>Корпус&nbsp;сталь</li></ul>]]></description>
      <param name="Артикул">123</param>
      <param name="Код товара">456</param>
      <param name="Класс точности">1,5</param>
      <param name="Диаметр корпуса" unit="мм">100</param>
    </offer>
    <offer id="11" available="true"><name>Пустой</name><vendor>X</vendor></offer>
  </offers>
</shop></yml_catalog>"""


@pytest.fixture
def feed(tmp_path: Path) -> Path:
    path = tmp_path / "feed.xml"
    path.write_text(FEED, encoding="utf-8")
    return path


def test_convert_offer(feed):
    offer, categories = find_offer(feed, "10")
    data = offer_to_input(offer, categories)
    assert data["name"] == "Манометр показывающий ДМ 02-100"
    assert data["manufacturer"] == "Манотомь"
    assert data["category"] == "Манометры"
    assert data["specs"] == {"Класс точности": "1,5", "Диаметр корпуса": "100 мм"}
    assert data["description"] == "Для измерения избыточного давления.\nКорпус сталь"
    parse_product(data)  # результат конвертера — валидный вход


def test_sparse_offer_converts_with_empty_fields(feed):
    offer, categories = find_offer(feed, "11")
    data = offer_to_input(offer, categories)
    assert data["specs"] == {} and data["description"] == ""


def test_offer_not_found(feed):
    with pytest.raises(KeyError):
        find_offer(feed, "999")


def test_html_to_text_handles_empty():
    assert html_to_text(None) is None
    assert html_to_text("<p> </p>") is None
