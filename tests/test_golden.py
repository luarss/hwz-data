import json
from pathlib import Path

import pytest

from hwz_ocr.schema import VENDORS, PriceRow

GOLDEN_DIR = Path(__file__).parent / "golden"
GOLDEN_FILES = sorted(GOLDEN_DIR.glob("*.json"))
MIN_ROWS = 10


def load_golden(path: Path) -> dict:
    return json.loads(path.read_text())


def test_every_vendor_has_a_golden_page():
    vendors = {path.stem.rsplit("_p", 1)[0] for path in GOLDEN_FILES}
    assert vendors == set(VENDORS)


@pytest.mark.parametrize("path", GOLDEN_FILES, ids=lambda path: path.stem)
def test_golden_file_is_valid(path: Path):
    payload = load_golden(path)
    vendor, page_suffix = path.stem.rsplit("_p", 1)
    assert payload["page_number"] == int(page_suffix)
    assert Path(payload["pdf"]).name.startswith(vendor + "_")
    rows = [PriceRow.model_validate(row) for row in payload["rows"]]
    assert len(rows) >= MIN_ROWS
    identities = [(row.product, row.variant, row.bundle_cpu, row.price_sgd) for row in rows]
    assert len(identities) == len(set(identities))
