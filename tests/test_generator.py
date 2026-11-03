import json

import pytest

from cardgen.generator import CardGenerator, parse_llm_json
from cardgen.input_parser import parse_product
from cardgen.llm import LLMRateLimitError, LLMResponseError
from cardgen.render import card_to_markdown
from cardgen.schemas import NO_DATA

from .conftest import MANOMETER, FakeLLM, make_draft


def test_happy_path(manometer):
    llm = FakeLLM([make_draft()])
    card = CardGenerator(llm).generate(manometer)
    assert card.status == "ok"
    assert card.validation.attempts == 1
    assert card.seo_title_length == len(card.seo_title) <= 70
    assert 800 <= card.seo_description_length <= 1200
    # Пробел «Корпус / степень защиты» отражён как «данных нет»
    assert any(c.value == NO_DATA for c in card.key_characteristics)


def test_hallucination_triggers_repair(manometer):
    bad = make_draft(seo_title="Манометр DM 02 Манотомь, IP65, поверка")
    llm = FakeLLM([bad, make_draft()])
    card = CardGenerator(llm).generate(manometer)
    assert card.status == "ok"
    assert card.validation.attempts == 2
    repair_request = llm.calls[1][-1]["content"]
    assert "65" in repair_request and "поверка" in repair_request


def test_persistent_hallucination_flagged_for_review(manometer):
    bad = make_draft(seo_title="Манометр DM 02, гарантия 3 года")
    llm = FakeLLM([bad])
    card = CardGenerator(llm, max_repair_attempts=2).generate(manometer)
    assert card.status == "needs_review"
    assert card.validation.attempts == 3
    assert any(i.code == "ungrounded_number" for i in card.validation.issues)
    assert "Есть замечания" in card_to_markdown(card)


def test_best_attempt_prefers_grounded_over_length(manometer):
    hallucinated = make_draft(seo_title="Манометр DM 02, IP65")
    too_short = make_draft(seo_description="Короткое описание без выдумок.")
    llm = FakeLLM([hallucinated, too_short, too_short])
    card = CardGenerator(llm).generate(manometer)
    assert card.status == "needs_review"
    assert all(i.code == "length" for i in card.validation.issues)


def test_malformed_json_then_valid(manometer):
    llm = FakeLLM(["Вот карточка: {не json", "```json\n" + json.dumps(make_draft(), ensure_ascii=False) + "\n```"])
    card = CardGenerator(llm).generate(manometer)
    assert card.status == "ok"
    assert "JSON" in llm.calls[1][-1]["content"]


def test_always_malformed_raises(manometer):
    llm = FakeLLM(['{"seo_title": "x"}'])
    with pytest.raises(LLMResponseError, match="не по схеме"):
        CardGenerator(llm, max_repair_attempts=1).generate(manometer)


def test_api_error_propagates(manometer):
    llm = FakeLLM([LLMRateLimitError("429")])
    with pytest.raises(LLMRateLimitError):
        CardGenerator(llm).generate(manometer)


def test_api_error_during_repair_keeps_best_draft(manometer):
    llm = FakeLLM([make_draft(seo_description="Слишком коротко."), LLMRateLimitError("429")])
    card = CardGenerator(llm).generate(manometer)
    assert card.status == "needs_review"
    assert card.validation.attempts == 1
    assert [i.field for i in card.validation.issues] == ["seo_description"]


def test_insufficient_data_skips_llm():
    parsed = parse_product({"name": "Манометр ДМ-02", "manufacturer": "Манотомь", "specs": {}, "description": ""})
    llm = FakeLLM([make_draft()])
    card = CardGenerator(llm).generate(parsed)
    assert card.status == "insufficient_data"
    assert llm.calls == []
    assert card.seo_title is None
    fields = [m.field for m in card.missing_data]
    assert "Характеристики (specs)" in fields and "Описание" in fields
    md = card_to_markdown(card)
    assert "Недостаточно данных" in md and NO_DATA in md


def test_characteristics_not_taken_from_llm(manometer):
    """Даже если модель «добавит» характеристики в notes, таблица строится только из входа."""
    llm = FakeLLM([make_draft(notes=["Степень защиты IP65"])])
    card = CardGenerator(llm).generate(manometer)
    values = {c.name: c.value for c in card.key_characteristics}
    assert values["Корпус / степень защиты"] == NO_DATA
    assert "IP65" not in json.dumps([c.model_dump() for c in card.key_characteristics], ensure_ascii=False)


def test_prompt_contains_data_and_missing_fields(manometer):
    llm = FakeLLM([make_draft()])
    CardGenerator(llm).generate(manometer)
    prompt = llm.calls[0][0]["content"]
    assert "<product_data>" in prompt and "0–1,6 МПа" in prompt
    assert "Корпус / степень защиты" in prompt


def test_parse_llm_json_rejects_wrong_schema():
    with pytest.raises(ValueError, match="commercial"):
        parse_llm_json(json.dumps({k: v for k, v in make_draft().items() if k != "commercial"}))

