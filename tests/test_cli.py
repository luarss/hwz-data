import csv
import shutil
import sys
import types
from pathlib import Path

import pytest

from hwz_ocr.cli import main
from hwz_ocr.extract_text import parse_rows
from hwz_ocr.manifest import load_manifest
from hwz_ocr.schema import ExtractionMethod, PageResult, PriceRow, QaCheck, QaReport

SAMPLE_DIR = Path("downloads/2026-09")
FUWELL_NAME = "fuwell_1YG84yiFPeZzEYqG9LzifoIBcNslLe9nA.pdf"


@pytest.fixture
def workspace(tmp_path):
    downloads = tmp_path / "downloads"
    (downloads / "2026-09").mkdir(parents=True)
    shutil.copy(SAMPLE_DIR / FUWELL_NAME, downloads / "2026-09" / FUWELL_NAME)
    data_dir = tmp_path / "data"
    common = ["--data-dir", str(data_dir), "--downloads-dir", str(downloads)]
    assert main([*common, "scan"]) == 0
    return data_dir, common


def fake_qa_module(passed: bool) -> types.ModuleType:
    module = types.ModuleType("hwz_ocr.qa")

    def check_page(result, layout_text, image_png):
        check = QaCheck(name="fake", passed=passed, detail=None if passed else "forced")
        return QaReport(sha256=result.sha256, page_number=result.page_number, checks=[check])

    module.check_page = check_page
    module.count_numeric_tokens = lambda text: 0
    return module


def only_entry(data_dir: Path):
    return next(iter(load_manifest(data_dir / "manifest.jsonl").values()))


def test_process_without_llm_writes_csv(workspace, monkeypatch, capsys):
    data_dir, common = workspace
    monkeypatch.setitem(sys.modules, "hwz_ocr.qa", fake_qa_module(passed=True))
    monkeypatch.setitem(sys.modules, "hwz_ocr.structure", None)

    assert main([*common, "process", "--vendor", "fuwell", "--no-llm"]) == 0

    entry = only_entry(data_dir)
    sha8 = entry.sha256[:8]
    rows_path = data_dir / "rows" / "fuwell" / "2026-09" / f"{sha8}.csv"
    prices_path = data_dir / "prices" / "fuwell" / "2026-09" / f"{sha8}.csv"
    with open(rows_path, newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) > 20
    assert {row["method"] for row in rows} == {"text_layer"}
    assert prices_path.read_text().startswith("item,price_sgd\n")
    assert (data_dir / "intermediate" / "fuwell" / sha8 / "p2.txt").exists()
    assert entry.pages_done == 2
    assert entry.completed

    assert "total pages=2 done=2" in capsys.readouterr().out
    assert main([*common, "stats"]) == 0
    stats_output = capsys.readouterr().out
    assert "fuwell" in stats_output
    assert stats_output.rstrip().splitlines()[-1] == "total_pending=0"
    assert main([*common, "rollup"]) == 0
    assert (data_dir / "prices.duckdb").exists()


def fake_structure_module(price: float) -> types.ModuleType:
    module = types.ModuleType("hwz_ocr.structure")

    def structure_page(*, vendor, sha256, page_number, layout_text, image_png, **kwargs):
        return PageResult(
            sha256=sha256,
            vendor=vendor,
            page_number=page_number,
            method=ExtractionMethod.TEXT_LAYER_LLM,
            provider="fake",
            model="fake-model",
            rows=[PriceRow(product="Fake Product", price_sgd=price)],
            raw_response='{"rows": []}',
        )

    module.structure_page = structure_page
    return module


def test_failed_qa_without_llm_stays_pending(workspace, monkeypatch, capsys):
    data_dir, common = workspace
    monkeypatch.setitem(sys.modules, "hwz_ocr.qa", fake_qa_module(passed=False))

    assert main([*common, "process", "--no-llm", "--max-pages", "1"]) == 0

    entry = only_entry(data_dir)
    assert entry.pages_quarantined == 0
    assert not (data_dir / "quarantine").exists()
    assert "total pages=2 done=0 quarantined=0 pending=2" in capsys.readouterr().out


def test_failed_qa_falls_back_to_llm_and_quarantines(workspace, monkeypatch, capsys):
    data_dir, common = workspace
    monkeypatch.setitem(sys.modules, "hwz_ocr.qa", fake_qa_module(passed=False))
    monkeypatch.setitem(sys.modules, "hwz_ocr.structure", fake_structure_module(19.9))

    assert main([*common, "process", "--max-pages", "1"]) == 0

    entry = only_entry(data_dir)
    sha8 = entry.sha256[:8]
    quarantined = PageResult.model_validate_json(
        (data_dir / "quarantine" / "fuwell" / f"{sha8}_p1.json").read_text()
    )
    assert quarantined.method == ExtractionMethod.TEXT_LAYER_LLM
    assert quarantined.quarantine_reason == "fake: forced"
    assert (data_dir / "intermediate" / "fuwell" / sha8 / "p1.llm.json").exists()
    assert not (data_dir / "rows" / "fuwell" / "2026-09" / f"{sha8}.csv").exists()
    assert entry.pages_quarantined == 1
    assert "total pages=1 done=0 quarantined=1" in capsys.readouterr().out


def test_llm_result_passing_qa_is_written(workspace, monkeypatch):
    data_dir, common = workspace
    monkeypatch.setitem(sys.modules, "hwz_ocr.qa", fake_qa_module(passed=True))
    monkeypatch.setitem(sys.modules, "hwz_ocr.structure", fake_structure_module(19.9))
    monkeypatch.setattr("hwz_ocr.cli.parse_rows", lambda layout_text, vendor: [])

    assert main([*common, "process", "--max-pages", "1"]) == 0

    sha8 = only_entry(data_dir).sha256[:8]
    prices_path = data_dir / "prices" / "fuwell" / "2026-09" / f"{sha8}.csv"
    assert prices_path.read_text() == "item,price_sgd\nFake Product,19.9\n"


def test_no_llm_budget_skips_pages_needing_llm(workspace, monkeypatch, capsys):
    data_dir, common = workspace
    monkeypatch.setitem(sys.modules, "hwz_ocr.qa", fake_qa_module(passed=True))
    real_parse_rows = parse_rows

    def parse_only_second_page(layout_text, vendor):
        rows = real_parse_rows(layout_text, vendor)
        return rows if len(rows) > 50 else []

    monkeypatch.setattr("hwz_ocr.cli.parse_rows", parse_only_second_page)

    assert main([*common, "process", "--no-llm", "--max-pages", "1"]) == 0

    output = capsys.readouterr().out
    assert "total pages=2 done=1 quarantined=0 pending=1" in output
    assert only_entry(data_dir).pages_done == 1
