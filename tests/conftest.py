import json

import pytest

from cardgen.input_parser import parse_product

MANOMETER = {
    "name": "Манометр показывающий DM 02",
    "manufacturer": "Манотомь",
    "specs": {
        "диапазон измерений": "0–1,6 МПа",
        "класс точности": "1,5",
        "присоединение": "G1/2",
        "диаметр корпуса": "100 мм",
    },
    "description": "Прибор предназначен для измерения избыточного давления неагрессивных жидкостей и газов.",
}

_FILLER = (
    "Прибор применяется на объектах водоснабжения и отопления, а также в технологических линиях. "
    "Модель удобна для комплектации новых объектов и замены приборов при ремонте. "
)


def make_draft(**overrides) -> dict:
    """Корректный ответ модели, проходящий все проверки для MANOMETER."""
    description = (
        "Манометр показывающий DM 02 производства Манотомь предназначен для измерения избыточного давления "
        "неагрессивных жидкостей и газов. Диапазон измерений 0–1,6 МПа, класс точности 1,5, присоединение G1/2, "
        "диаметр корпуса 100 мм. "
    )
    while len(description) < 900:
        description += _FILLER
    draft = {
        "seo_title": "Манометр показывающий DM 02 Манотомь, 0–1,6 МПа",
        "seo_description": description.strip(),
        "search_queries": ["манометр dm 02", "манометр 1,6 мпа g1/2", "манометр dm 02 купить"],
        "commercial": {
            "audience": ["Службы КИПиА", "Монтажные организации"],
            "tasks": ["Контроль давления в трубопроводах", "Замена манометров при ремонте"],
            "summary": "Показывающий манометр для контроля давления жидкостей и газов.",
        },
        "notes": [],
    }
    draft.update(overrides)
    return draft


class FakeLLM:
    """LLM-заглушка с заранее заданными ответами; запоминает все запросы."""

    provider = "fake"
    model = "fake-model"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls: list[list[dict]] = []

    def complete(self, system, messages):
        self.calls.append([dict(m) for m in messages])
        item = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, str) else json.dumps(item, ensure_ascii=False)


@pytest.fixture
def manometer():
    return parse_product(json.loads(json.dumps(MANOMETER)))
