from cardgen.input_parser import parse_product
from cardgen.schemas import NO_DATA
from cardgen.specs import build_specs_report, detect_profile, is_sufficient


def _profile(name, category=None):
    return detect_profile(parse_product({"name": name, "category": category})).code


def test_profile_detection():
    assert _profile("Манометр показывающий DM 02") == "pressure_gauge"
    assert _profile("Преобразователь давления ПД100") == "pressure_transmitter"
    assert _profile("ДТС035", category="Термопреобразователи сопротивления (ТСМ, ТСП)") == "temperature_sensor"
    assert _profile("Измеритель-регулятор ТРМ200") == "controller"
    assert _profile("Мультиметр цифровой") == "generic"


def test_characteristics_are_copied_verbatim(manometer):
    report = build_specs_report(manometer)
    from_input = {c.name: c.value for c in report.characteristics if c.source == "input"}
    assert from_input["диапазон измерений"] == "0–1,6 МПа"
    assert from_input["Производитель"] == "Манотомь"


def test_missing_standard_fields_marked_no_data(manometer):
    report = build_specs_report(manometer)
    missing = {c.name for c in report.characteristics if c.source == "missing"}
    # Для манометра нет только степени защиты/корпуса
    assert missing == {"Корпус / степень защиты"}
    assert all(c.value == NO_DATA for c in report.characteristics if c.source == "missing")
    assert [m.field for m in report.missing] == ["Корпус / степень защиты"]


def test_feature_mentioned_only_in_description_needs_clarification():
    parsed = parse_product({
        "name": "Датчик давления ПД100",
        "specs": {"диапазон измерений": "0…1 МПа"},
        "description": "Выходной сигнал 4…20 мА, питание 24 В.",
    })
    comments = {m.field: m.comment for m in build_specs_report(parsed).missing}
    assert "упоминается в описании" in comments["Питание"]
    assert "упоминается в описании" in comments["Интерфейсы / выходной сигнал"]
    assert "Нет во входных данных" in comments["Класс точности / погрешность"]


def test_prompt_allows_values_found_only_in_description():
    from cardgen.prompts import build_user_prompt

    parsed = parse_product({
        "name": "Датчик давления ПД100",
        "specs": {"диапазон измерений": "0…1 МПа"},
        "description": "Выходной сигнал 4…20 мА.",
    })
    prompt = build_user_prompt(parsed.product, build_specs_report(parsed))
    missing_line, description_line = prompt.splitlines()[1:3]
    assert "Интерфейсы / выходной сигнал" not in missing_line
    assert "Класс точности / погрешность" in missing_line
    assert "есть в description" in description_line and "Интерфейсы / выходной сигнал" in description_line


def test_empty_spec_not_duplicated_by_standard_field():
    parsed = parse_product({"name": "Датчик давления", "specs": {"Питание": "", "диапазон": "0…1 МПа"}})
    report = build_specs_report(parsed)
    assert [c.name for c in report.characteristics].count("Питание") == 1


def test_empty_spec_values_reported():
    parsed = parse_product({"name": "Манометр", "manufacturer": None, "specs": {"класс точности": ""},
                            "description": "Прибор для измерения избыточного давления в системах."})
    report = build_specs_report(parsed)
    fields = [m.field for m in report.missing]
    assert "Производитель" in fields and "класс точности" in fields


def test_sufficiency_gate():
    assert not is_sufficient(parse_product({"name": "Манометр ДМ-02", "manufacturer": "Манотомь"}))
    assert not is_sufficient(parse_product({"name": "Манометр", "description": "Короткий текст"}))
    assert is_sufficient(parse_product({"name": "Манометр", "specs": {"класс точности": "1,5"}}))
