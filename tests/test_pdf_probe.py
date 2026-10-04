from pathlib import Path

import pytest

from hwz_ocr.pdf_probe import (
    detect_vendor,
    has_text_layer,
    page_count,
    pick_vendor,
    render_page_png,
    sha256_of,
    vendor_from_filename,
)

SAMPLE_DIR = Path("downloads/2026-09")
FUWELL_PDF = SAMPLE_DIR / "fuwell_1YG84yiFPeZzEYqG9LzifoIBcNslLe9nA.pdf"
BIZGRAM_PDF = SAMPLE_DIR / "bizgram_14UCsN0b-blS0eHSv7kAv_RUgj3eZjd4U.pdf"
PC_THEMES_PDF = SAMPLE_DIR / "pc_themes_1gGXCe_QFiYktp9M-H0dFq7_gJab_1t4j.pdf"
TRADEPAC_PDF = SAMPLE_DIR / "tradepac_1NHO2XDvRI3UmrAaGR0YhgzHpGLQFb1Gn.pdf"
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


@pytest.mark.parametrize("pdf_path", [FUWELL_PDF, BIZGRAM_PDF])
def test_text_layer_vendors_have_text(pdf_path):
    assert has_text_layer(pdf_path) is True


@pytest.mark.parametrize("pdf_path", [PC_THEMES_PDF, TRADEPAC_PDF])
def test_scanned_vendors_have_no_text(pdf_path):
    assert has_text_layer(pdf_path) is False


def test_page_count():
    assert page_count(FUWELL_PDF) == 2


def test_render_page_png_returns_png_bytes():
    image = render_page_png(FUWELL_PDF, 1, dpi=50)
    assert image.startswith(PNG_SIGNATURE)


def test_sha256_of_is_stable_hex():
    digest = sha256_of(FUWELL_PDF)
    assert len(digest) == 64
    assert digest == sha256_of(FUWELL_PDF)


@pytest.mark.parametrize(
    ("name", "vendor"),
    [
        ("fuwell_abc.pdf", "fuwell"),
        ("pc_themes_1gGXCe_QFiYktp9M.pdf", "pc_themes"),
        ("downloads/2026-09/tradepac_x.pdf", "tradepac"),
        ("techdeals_1BWV9Sia73Q.pdf", "techdeals"),
    ],
)
def test_vendor_from_filename(name, vendor):
    assert vendor_from_filename(name) == vendor


@pytest.mark.parametrize("name", ["unknown_file.pdf", "pc_file.pdf", "fuwell.pdf"])
def test_vendor_from_filename_rejects_unknown(name):
    with pytest.raises(ValueError):
        vendor_from_filename(name)


@pytest.mark.parametrize(
    ("pdf_path", "vendor"),
    [
        (Path("downloads/2025-09/pc_themes_1gEHPU9so4bob7ut8dzoVwxmX_OLqZtnp.pdf"), "techdeals"),
        (Path("downloads/2025-07/pc_themes_1mn0Ky7UbY0Rq4vZBSZ2yR-OiFqFAP0O3.pdf"), "bizgram"),
        (Path("downloads/2025-08/pc_themes_1fSS30prSkimPHLDwNTvHc7aXPMTuivzv.pdf"), "laser"),
        (FUWELL_PDF, "fuwell"),
        (BIZGRAM_PDF, "bizgram"),
        (SAMPLE_DIR / "infinity_1DhfsitDgo6sop0tBc_qadk54ZO0QDl_G.pdf", "infinity"),
        (SAMPLE_DIR / "pc_themes_1ugWWft2FBxeVBDxYhu_nTsqvECMmGALH.pdf", "pc_themes"),
    ],
)
def test_detect_vendor_from_content(pdf_path, vendor):
    assert detect_vendor(pdf_path) == vendor


def test_detect_vendor_returns_none_for_scanned_pdf():
    assert detect_vendor(TRADEPAC_PDF) is None


def test_pick_vendor_requires_clear_winner():
    assert pick_vendor({"bizgram": 3, "infinity": 3, "fuwell": 0}) is None
    assert pick_vendor({"bizgram": 0, "infinity": 0}) is None
    assert pick_vendor({"bizgram": 4, "infinity": 3}) == "bizgram"
