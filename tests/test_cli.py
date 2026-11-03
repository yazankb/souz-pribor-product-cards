import json
from pathlib import Path

from cardgen.cli import EXIT_INPUT, EXIT_NEEDS_REVIEW, EXIT_OK, main

from .conftest import MANOMETER


def test_generate_mock_writes_md_and_json(tmp_path: Path):
    src = tmp_path / "manometer.json"
    src.write_text(json.dumps(MANOMETER, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out"
    assert main(["generate", str(tmp_path / "*.json"), "--mock", "--out", str(out)]) == EXIT_OK
    card = json.loads((out / "manometer.json").read_text(encoding="utf-8"))
    assert card["status"] == "ok"
    assert (out / "manometer.md").read_text(encoding="utf-8").startswith("# Черновик карточки")


def test_insufficient_data_exit_code(tmp_path: Path, capsys):
    src = tmp_path / "feed_only.json"
    src.write_text('{"name": "Манометр ТМ-510", "manufacturer": "РОСМА", "specs": {}}', encoding="utf-8")
    assert main(["generate", str(src), "--mock"]) == EXIT_NEEDS_REVIEW
    assert "Недостаточно данных" in capsys.readouterr().out


def test_invalid_input_exit_code(tmp_path: Path, capsys):
    src = tmp_path / "broken.json"
    src.write_text('{"name": ', encoding="utf-8")
    assert main(["generate", str(src), str(tmp_path / "missing.json"), "--mock"]) == EXIT_INPUT
    err = capsys.readouterr().err
    assert "Невалидный JSON" in err and "Файл не найден" in err
