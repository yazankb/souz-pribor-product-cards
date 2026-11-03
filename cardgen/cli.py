"""Командная строка.

    python -m cardgen generate examples/input/manometer.json --out examples/output
    python -m cardgen generate - < product.json            # чтение из stdin
    python -m cardgen yml-list feed.xml --search манометр
    python -m cardgen yml-convert feed.xml --offer-id 12345 --out examples/input/x.json
    python -m cardgen serve --port 8000
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

from .config import ConfigError, load_settings
from .generator import CardGenerator
from .input_parser import InputError, parse_raw
from .llm import LLMError, create_client
from .render import card_to_markdown

EXIT_OK, EXIT_NEEDS_REVIEW, EXIT_INPUT, EXIT_LLM, EXIT_CONFIG = 0, 1, 2, 3, 4


def _read_input(source: str) -> bytes:
    if source == "-":
        return sys.stdin.buffer.read()
    return Path(source).read_bytes()


def _expand(inputs: list[str]) -> list[str]:
    """Раскрывает маски вида examples/input/*.json (PowerShell и cmd этого не делают сами)."""
    result: list[str] = []
    for item in inputs:
        matches = sorted(glob.glob(item)) if any(ch in item for ch in "*?[") else []
        result.extend(matches or [item])
    return result


def cmd_generate(args: argparse.Namespace) -> int:
    try:
        settings = load_settings(provider_override="mock" if args.mock else None)
    except ConfigError as exc:
        print(f"Ошибка конфигурации: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    try:
        generator = CardGenerator(create_client(settings), max_repair_attempts=settings.max_repair_attempts)
    except LLMError as exc:
        print(f"Ошибка LLM: {exc}", file=sys.stderr)
        return EXIT_CONFIG

    worst = EXIT_OK
    for source in _expand(args.inputs):
        label = "stdin" if source == "-" else source
        try:
            parsed = parse_raw(_read_input(source))
        except FileNotFoundError:
            print(f"[{label}] Файл не найден.", file=sys.stderr)
            worst = max(worst, EXIT_INPUT)
            continue
        except InputError as exc:
            print(f"[{label}] Ошибка входных данных:", file=sys.stderr)
            for err in exc.errors:
                print(f"  - {err}", file=sys.stderr)
            worst = max(worst, EXIT_INPUT)
            continue

        print(f"[{label}] Генерация: {parsed.product.name} ({settings.provider}/{settings.model})…", file=sys.stderr)
        try:
            card = generator.generate(parsed)
        except LLMError as exc:
            print(f"[{label}] Ошибка LLM: {exc}", file=sys.stderr)
            worst = max(worst, EXIT_LLM)
            continue

        markdown = card_to_markdown(card)
        card_json = json.dumps(card.model_dump(), ensure_ascii=False, indent=2)
        if args.out:
            out_dir = Path(args.out)
            out_dir.mkdir(parents=True, exist_ok=True)
            stem = Path(source).stem if source != "-" else "card"
            if args.format in ("md", "both"):
                (out_dir / f"{stem}.md").write_text(markdown, encoding="utf-8")
            if args.format in ("json", "both"):
                (out_dir / f"{stem}.json").write_text(card_json + "\n", encoding="utf-8")
            print(f"[{label}] Статус: {card.status}. Сохранено в {out_dir}", file=sys.stderr)
        else:
            print(card_json if args.format == "json" else markdown)
        if card.status != "ok":
            worst = max(worst, EXIT_NEEDS_REVIEW)
    return worst


def cmd_yml_list(args: argparse.Namespace) -> int:
    from .yml import iter_feed, technical_params

    categories, offers = iter_feed(args.feed)
    needle = (args.search or "").lower()
    shown = 0
    for offer in offers:
        tech = technical_params(offer)
        haystack = f"{offer.type_prefix or ''} {offer.name} {categories.get(offer.category_id or '', '')}".lower()
        if needle and needle not in haystack:
            continue
        if len(tech) < args.min_params:
            continue
        desc_len = len(offer.description or "")
        print(f"{offer.id}\tparams={len(tech)}\tdesc={desc_len}\t{offer.vendor or '-'}\t"
              f"{offer.type_prefix or ''} {offer.name}\t[{categories.get(offer.category_id or '', '')}]")
        shown += 1
        if shown >= args.limit:
            break
    if not shown:
        print("Ничего не найдено.", file=sys.stderr)
    return EXIT_OK


def cmd_yml_convert(args: argparse.Namespace) -> int:
    from .yml import find_offer, offer_to_input

    try:
        offer, categories = find_offer(args.feed, args.offer_id)
    except KeyError as exc:
        print(exc.args[0], file=sys.stderr)
        return EXIT_INPUT
    text = json.dumps(offer_to_input(offer, categories), ensure_ascii=False, indent=2) + "\n"
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"Сохранено: {args.out}", file=sys.stderr)
    else:
        print(text, end="")
    return EXIT_OK


def cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("cardgen.web:app", host=args.host, port=args.port)
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cardgen", description="Черновики товарных карточек КИП с помощью LLM")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="Сгенерировать карточку из JSON-файла(ов)")
    gen.add_argument("inputs", nargs="+", help="Путь к JSON или «-» для stdin")
    gen.add_argument("--out", help="Папка для сохранения .md/.json (по умолчанию — вывод в консоль)")
    gen.add_argument("--format", choices=("md", "json", "both"), default="both",
                     help="Формат результата (для консоли «both» = Markdown)")
    gen.add_argument("--mock", action="store_true", help="Офлайн-режим без LLM (шаблонный ответ)")
    gen.set_defaults(func=cmd_generate)

    yl = sub.add_parser("yml-list", help="Показать офферы фида с количеством характеристик")
    yl.add_argument("feed")
    yl.add_argument("--search", help="Подстрока в названии/категории")
    yl.add_argument("--min-params", type=int, default=0, help="Минимум технических параметров")
    yl.add_argument("--limit", type=int, default=30)
    yl.set_defaults(func=cmd_yml_list)

    yc = sub.add_parser("yml-convert", help="Конвертировать оффер фида во входной JSON")
    yc.add_argument("feed")
    yc.add_argument("--offer-id", required=True)
    yc.add_argument("--out")
    yc.set_defaults(func=cmd_yml_convert)

    sv = sub.add_parser("serve", help="Запустить веб-форму")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8000)
    sv.set_defaults(func=cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    return args.func(args)
