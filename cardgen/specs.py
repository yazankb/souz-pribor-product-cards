"""Детерминированная часть карточки: тип прибора, список характеристик и отчёт о пробелах.

Характеристики собираются кодом напрямую из входных данных — LLM их не пишет и
поэтому не может исказить. Для каждого типа прибора задан набор «стандартных»
полей; если поле не найдено во входных specs, оно попадает в карточку со
значением «данных нет» и в список недостающих данных.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .input_parser import ParsedInput
from .schemas import NO_DATA, Characteristic, MissingField


@dataclass(frozen=True)
class StandardField:
    title: str
    patterns: tuple[str, ...]  # регулярные выражения, ищутся в «ключ: значение»

    def matches(self, text: str) -> bool:
        return any(re.search(p, text, flags=re.IGNORECASE) for p in self.patterns)


@dataclass(frozen=True)
class Profile:
    code: str
    title: str
    keywords: tuple[str, ...]
    fields: tuple[StandardField, ...]


RANGE = StandardField("Диапазон измерений", (r"диапазон", r"предел[а-я]* измерен", r"шкал"))
ACCURACY = StandardField("Класс точности / погрешность", (r"класс[а-я]* точност", r"погрешност", r"точност"))
POWER = StandardField("Питание", (r"питани", r"напряжени[ея] сети", r"батаре", r"аккумулятор"))
INTERFACES = StandardField(
    "Интерфейсы / выходной сигнал",
    (r"интерфейс", r"выходн[а-я]* сигнал", r"\bвыход", r"rs-?485", r"modbus", r"hart", r"usb", r"4\s*[-–…]\s*20\s*мА"),
)
HOUSING = StandardField(
    "Корпус / степень защиты",
    (r"^корпус", r"(?:тип|материал|исполнение)[а-я]* корпус", r"степень защиты", r"пылевлагозащ", r"\bip-?\s?\d{2}"),
)
CONNECTION = StandardField("Присоединение", (r"присоедин", r"резьб", r"штуцер"))
DIAMETER = StandardField("Диаметр корпуса", (r"диаметр",))
TEMP_RANGE = StandardField("Диапазон измеряемых температур", (r"диапазон", r"температур[а-я]* измер", r"предел"))
SENSOR_TYPE = StandardField("НСХ / тип чувствительного элемента", (r"нсх", r"\bтип\b", r"pt\s?\d{2,4}", r"\b\d{2,4}[мп]\b", r"чувствительн"))
TOLERANCE = StandardField("Класс допуска / точности", (r"класс[а-я]* допуска", r"класс[а-я]* точност", r"погрешност"))
LENGTH = StandardField("Длина монтажной (погружной) части", (r"длин",))
INPUTS = StandardField("Входы (тип и количество)", (r"\bвход", r"датчик"))
OUTPUTS = StandardField("Выходы", (r"\bвыход", r"реле"))

PROFILES: tuple[Profile, ...] = (
    Profile(
        "pressure_transmitter",
        "Датчик (преобразователь) давления",
        (r"датчик[а-я]* давлени", r"преобразовател[а-я]* давлени", r"датчик[а-я]* разност"),
        (RANGE, ACCURACY, INTERFACES, POWER, CONNECTION, HOUSING),
    ),
    Profile(
        "pressure_gauge",
        "Манометр / прибор давления показывающий",
        (r"манометр", r"вакуумметр", r"напоромер", r"тягомер", r"тягонапоромер"),
        (RANGE, ACCURACY, CONNECTION, DIAMETER, HOUSING),
    ),
    Profile(
        "temperature_sensor",
        "Термопреобразователь / датчик температуры",
        (r"термопреобразовател", r"термопар", r"термосопротивлен", r"датчик[а-я]* температур", r"\bтс[пмн]\b", r"\bтх[ак]\b"),
        (TEMP_RANGE, SENSOR_TYPE, TOLERANCE, LENGTH, CONNECTION),
    ),
    Profile(
        "thermometer",
        "Термометр",
        (r"термометр",),
        (TEMP_RANGE, ACCURACY, DIAMETER, LENGTH, CONNECTION),
    ),
    Profile(
        "controller",
        "Измеритель-регулятор / контроллер / модуль",
        (r"регулятор", r"контроллер", r"модул[ья] ввода", r"модул[ья] вывода", r"реле", r"индикатор", r"самопис", r"регистратор"),
        (INPUTS, OUTPUTS, ACCURACY, POWER, INTERFACES, HOUSING),
    ),
)

GENERIC = Profile(
    "generic",
    "Измерительный прибор",
    (),
    (RANGE, ACCURACY, POWER, INTERFACES, HOUSING),
)


def detect_profile(parsed: ParsedInput) -> Profile:
    """Определяет тип прибора по категории и названию (сначала более специфичные профили)."""
    product = parsed.product
    haystack = " ".join(filter(None, [product.category, product.name])).lower()
    for profile in PROFILES:
        if any(re.search(k, haystack) for k in profile.keywords):
            return profile
    return GENERIC


@dataclass
class SpecsReport:
    profile: Profile
    characteristics: list[Characteristic]
    missing: list[MissingField]


def build_specs_report(parsed: ParsedInput) -> SpecsReport:
    product = parsed.product
    profile = detect_profile(parsed)
    spec_lines = [f"{k}: {v}" for k, v in product.specs.items()]
    description = product.description or ""

    characteristics: list[Characteristic] = [
        Characteristic(name="Производитель", value=product.manufacturer or NO_DATA,
                       source="input" if product.manufacturer else "missing"),
    ]
    characteristics += [Characteristic(name=k, value=v, source="input") for k, v in product.specs.items()]

    missing: list[MissingField] = []

    if not product.manufacturer:
        missing.append(MissingField(field="Производитель", comment="Не указан производитель."))
    if not product.specs:
        missing.append(MissingField(field="Характеристики (specs)", comment="Не передано ни одной характеристики."))
    if not description:
        missing.append(MissingField(field="Описание", comment="Нет текстового описания или фрагмента паспорта."))

    for key in parsed.empty_specs:
        characteristics.append(Characteristic(name=key, value=NO_DATA, source="missing"))
        missing.append(MissingField(field=key, comment="Характеристика передана с пустым значением."))

    empty_lines = [f"{key}:" for key in parsed.empty_specs]
    for std in profile.fields:
        if any(std.matches(line) for line in spec_lines + empty_lines):
            continue  # поле заполнено или уже отмечено как пустое выше
        characteristics.append(Characteristic(name=std.title, value=NO_DATA, source="missing"))
        if description and std.matches(description):
            comment = "Нет в характеристиках, но упоминается в описании — проверьте и перенесите в таблицу."
        else:
            comment = "Нет во входных данных — уточните у производителя или по паспорту."
        missing.append(MissingField(field=std.title, comment=comment))

    return SpecsReport(profile=profile, characteristics=characteristics, missing=missing)


def is_sufficient(parsed: ParsedInput) -> bool:
    """Минимум для генерации: хотя бы одна характеристика или текстовое описание.

    Если есть только название и производитель, модель неизбежно начнёт
    «додумывать» — такой запрос не отправляется в LLM.
    """
    product = parsed.product
    return bool(product.specs) or bool(product.description and len(product.description) >= 40)
