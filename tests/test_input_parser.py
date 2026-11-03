import pytest

from cardgen.input_parser import InputError, parse_product, parse_raw


def test_invalid_json_reports_position():
    with pytest.raises(InputError) as exc:
        parse_raw('{"name": "Манометр",\n "specs": {"класс": "1,5",}}')
    assert "Невалидный JSON" in exc.value.errors[0]
    assert "строка 2" in exc.value.errors[0]


@pytest.mark.parametrize("raw", ["", "   ", b""])
def test_empty_input(raw):
    with pytest.raises(InputError, match="Пустой ввод"):
        parse_raw(raw)


def test_non_object_json():
    with pytest.raises(InputError, match="JSON-объект"):
        parse_raw("[1, 2, 3]")


def test_missing_and_empty_name_collects_all_errors():
    with pytest.raises(InputError) as exc:
        parse_product({"name": "  ", "specs": "строка вместо объекта"})
    errors = " ".join(exc.value.errors)
    assert "name" in errors and "specs" in errors


def test_name_required():
    with pytest.raises(InputError, match="обязательно"):
        parse_product({"manufacturer": "ОВЕН"})


def test_normalization_and_empty_specs():
    parsed = parse_product({
        "name": "  Датчик   давления ",
        "manufacturer": "",
        "specs": {"класс точности": 0.5, "питание": None, "диапазон": "  ", "интерфейс": ["RS-485", "Modbus"],
                  "индикация": True},
        "description": None,
    })
    p = parsed.product
    assert p.name == "Датчик давления"
    assert p.manufacturer is None
    assert p.specs == {"класс точности": "0,5", "интерфейс": "RS-485; Modbus", "индикация": "да"}
    assert parsed.empty_specs == ["питание", "диапазон"]


def test_specs_as_list_of_pairs():
    parsed = parse_product({"name": "X", "specs": [{"name": "класс точности", "value": "1"}]})
    assert parsed.product.specs == {"класс точности": "1"}


def test_nested_spec_value_rejected():
    with pytest.raises(InputError, match="класс"):
        parse_product({"name": "X", "specs": {"класс": {"a": 1}}})


def test_duplicate_keys_and_unknown_fields_warn():
    parsed = parse_raw('{"name": "A", "name": "B", "price": 100}')
    assert parsed.product.name == "B"
    assert any("несколько раз" in w for w in parsed.warnings)
    assert any("price" in w for w in parsed.warnings)


def test_utf8_bom_accepted():
    parsed = parse_raw("﻿{\"name\": \"Манометр\"}".encode("utf-8"))
    assert parsed.product.name == "Манометр"
