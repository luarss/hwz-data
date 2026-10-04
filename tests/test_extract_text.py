from pathlib import Path

import pytest

from hwz_ocr.extract_text import extract_layout, parse_rows
from hwz_ocr.schema import MAX_PRICE_SGD, MIN_PRICE_SGD

SAMPLE_DIR = Path("downloads/2026-09")
FUWELL_PDF = SAMPLE_DIR / "fuwell_1YG84yiFPeZzEYqG9LzifoIBcNslLe9nA.pdf"
INFINITY_PDF = SAMPLE_DIR / "infinity_1DhfsitDgo6sop0tBc_qadk54ZO0QDl_G.pdf"


@pytest.fixture(scope="module")
def infinity_layout():
    return extract_layout(INFINITY_PDF, 2)


@pytest.fixture(scope="module")
def fuwell_layout():
    return extract_layout(FUWELL_PDF, 2)


def test_layout_keeps_product_and_price_on_same_line(infinity_layout):
    matching = [line for line in infinity_layout.splitlines() if "Asus GT730 LP 2GB GDDR5" in line]
    assert any("139" in line for line in matching)


@pytest.mark.parametrize(
    ("layout_name", "vendor"), [("infinity_layout", "infinity"), ("fuwell_layout", "fuwell")]
)
def test_parse_rows_yields_sane_rows(request, layout_name, vendor):
    rows = parse_rows(request.getfixturevalue(layout_name), vendor)
    assert len(rows) > 20
    assert all(MIN_PRICE_SGD <= row.price_sgd <= MAX_PRICE_SGD for row in rows)
    assert all(any(character.isalpha() for character in row.product) for row in rows)


def test_parse_rows_finds_known_infinity_price(infinity_layout):
    rows = parse_rows(infinity_layout, "infinity")
    prices = {row.product: row.price_sgd for row in rows}
    assert prices["Asus GT730 LP 2GB GDDR5"] == 139
    assert prices["Asus Dual RTX3060 12GB OC GDDR6"] == 729


def test_parse_rows_assigns_categories(infinity_layout):
    rows = parse_rows(infinity_layout, "infinity")
    assert any(row.category for row in rows)


@pytest.mark.parametrize("vendor", ["bizgram", "dynacore", "pc_themes", "tradepac"])
def test_parse_rows_skips_llm_vendors(infinity_layout, vendor):
    assert parse_rows(infinity_layout, vendor) == []


def test_parse_rows_rejects_matrix_lines():
    layout = "Seagate Ironwolf NAS        -     319    -     659\nWD Blue 1TB        79"
    rows = parse_rows(layout, "fuwell")
    assert [(row.product, row.price_sgd) for row in rows] == [("WD Blue 1TB", 79)]


def test_parse_rows_tracks_header_category():
    layout = "GRAPHICS CARD\nAsus Dual RTX5060        729\nAsus Prime RTX5070        1349"
    rows = parse_rows(layout, "laser")
    assert [row.category for row in rows] == ["GRAPHICS CARD", "GRAPHICS CARD"]


def test_parse_rows_rejects_out_of_range_price():
    assert parse_rows("Some Product Name        99999", "fuwell") == []


@pytest.mark.parametrize(
    ("layout", "price"),
    [
        ("Cruzer Blade USB 2.0        $ 13.50", 13.5),
        ("Arctic Freezer 36        19.9", 19.9),
        ("Freezer III Pro 240        $ 1 20.00", 120),
        ("Asus Prime RTX5080        $2,499", 2499),
        ("Asus Prime RTX5080        $        2,499.00", 2499),
    ],
)
def test_parse_rows_accepts_decimal_and_currency_prices(layout, price):
    rows = parse_rows(layout, "techdeals")
    assert [row.price_sgd for row in rows] == [price]


DYNACORE_PDF = SAMPLE_DIR / "dynacore_15tdWCJ_A5cRM49RAUlx7ea_7cZD1704W.pdf"


def test_dynacore_layout_drops_numbers_hidden_under_images():
    layout = extract_layout(DYNACORE_PDF, 2, vendor="dynacore")
    line = next(line for line in layout.splitlines() if "Z890-P" in line)
    tokens = line.split()
    assert "509" in tokens
    assert "1144" in tokens
    assert "555" not in tokens
    assert "851" not in tokens


def test_dynacore_hidden_numbers_present_without_vendor():
    layout = extract_layout(DYNACORE_PDF, 2)
    line = next(line for line in layout.splitlines() if "Z890-P" in line)
    assert "555" in line.split()


def test_fuwell_layout_unchanged_by_vendor(fuwell_layout):
    assert extract_layout(FUWELL_PDF, 2, vendor="fuwell") == fuwell_layout
