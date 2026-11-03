from cardgen.schemas import LLMDraft
from cardgen.validation import check_format, check_grounding, numbers_in

from .conftest import make_draft


def test_numbers_normalized():
    assert numbers_in("0–1,6 МПа, 100 мм, DM 02") >= {"0", "1.6", "100", "2"}
    assert "10000" in numbers_in("до 10 000 Па")
    assert "1.6" in numbers_in("1.60")


def test_valid_draft_passes(manometer):
    draft = LLMDraft.model_validate(make_draft())
    assert check_format(draft) == []
    assert check_grounding(draft, manometer.product) == []


def test_invented_number_detected(manometer):
    draft = LLMDraft.model_validate(make_draft(seo_title="Манометр DM 02, 0–2,5 МПа, IP65"))
    issues = check_grounding(draft, manometer.product)
    messages = " ".join(i.message for i in issues)
    assert "2,5" in messages and "65" in messages
    assert any(i.code == "ungrounded_term" and "IP" in i.message for i in issues)


def test_invented_term_detected(manometer):
    commercial = make_draft()["commercial"] | {"summary": "Поставляется с поверкой, интерфейс RS-485."}
    draft = LLMDraft.model_validate(make_draft(commercial=commercial))
    issues = check_grounding(draft, manometer.product)
    labels = {i.message for i in issues if i.field == "commercial.summary"}
    assert any("поверка" in m for m in labels)
    assert any("RS-485" in m for m in labels)


def test_term_allowed_when_in_input(manometer):
    product = manometer.product.model_copy(update={"specs": {**manometer.product.specs, "интерфейс": "RS-485"}})
    commercial = make_draft()["commercial"] | {"summary": "Есть интерфейс RS-485."}
    draft = LLMDraft.model_validate(make_draft(commercial=commercial))
    assert check_grounding(draft, product) == []


def test_number_format_variants_accepted(manometer):
    # «1.6» во входе записано как «1,6» — это то же число.
    draft = LLMDraft.model_validate(make_draft(seo_title="Манометр DM 02 на 1.6 МПа"))
    assert check_grounding(draft, manometer.product) == []


def test_length_and_count_checks():
    draft = LLMDraft.model_validate(make_draft(
        seo_title="М" * 71, seo_description="коротко", search_queries=["a", "a", "b"],
    ))
    fields = {i.field for i in check_format(draft)}
    assert fields == {"seo_title", "seo_description", "search_queries"}


def test_too_many_queries():
    draft = LLMDraft.model_validate(make_draft(search_queries=[f"запрос {c}" for c in "абвгде"]))
    assert [i.code for i in check_format(draft)] == ["count"]
