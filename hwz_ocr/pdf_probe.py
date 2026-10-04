import hashlib
import io
import unicodedata
from pathlib import Path

import pdfplumber
from pdf2image import convert_from_path

from hwz_ocr.schema import VENDORS

TEXT_LAYER_PROBE_PAGES = 2
TEXT_LAYER_MIN_CHARS = 50
HASH_CHUNK_SIZE = 1 << 20
VENDOR_PROBE_PAGES = 2
NAME_MARKER_WEIGHT = 1
DOMAIN_MARKER_WEIGHT = 3
VENDOR_MARKERS = {
    "bizgram": {"bizgram": NAME_MARKER_WEIGHT, "sales@bizgram": DOMAIN_MARKER_WEIGHT},
    "dynacore": {"dynacore": NAME_MARKER_WEIGHT},
    "fuwell": {"fuwell": NAME_MARKER_WEIGHT},
    "infinity": {
        "infinity computer": NAME_MARKER_WEIGHT,
        "infinitycomputer": DOMAIN_MARKER_WEIGHT,
    },
    "laser": {"laser distributor": NAME_MARKER_WEIGHT, "ldplsl@singnet": DOMAIN_MARKER_WEIGHT},
    "techdeals": {"techdeals": NAME_MARKER_WEIGHT},
    "tradepac": {"tradepac": NAME_MARKER_WEIGHT},
    "pc_themes": {"pc themes": NAME_MARKER_WEIGHT, "pcthemes": DOMAIN_MARKER_WEIGHT},
}


def page_count(pdf_path: Path) -> int:
    with pdfplumber.open(pdf_path) as pdf:
        return len(pdf.pages)


def has_text_layer(pdf_path: Path) -> bool:
    non_whitespace = 0
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages[:TEXT_LAYER_PROBE_PAGES]:
            non_whitespace += count_visible_chars(page)
            if non_whitespace > TEXT_LAYER_MIN_CHARS:
                return True
    return False


def count_visible_chars(page) -> int:
    return sum(1 for char in page.chars if not char["text"].isspace())


def render_page_png(pdf_path: Path, page_number: int, dpi: int = 200) -> bytes:
    images = convert_from_path(
        str(pdf_path), dpi=dpi, first_page=page_number, last_page=page_number
    )
    if not images:
        raise ValueError(f"page {page_number} not found in {pdf_path}")
    buffer = io.BytesIO()
    images[0].save(buffer, format="PNG")
    return buffer.getvalue()


def sha256_of(pdf_path: Path) -> str:
    digest = hashlib.sha256()
    with open(pdf_path, "rb") as handle:
        while chunk := handle.read(HASH_CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def vendor_from_filename(name: str) -> str:
    stem = Path(name).name
    for vendor in sorted(VENDORS, key=len, reverse=True):
        if stem.startswith(f"{vendor}_"):
            return vendor
    raise ValueError(f"unknown vendor for file {name!r}")


def probe_text(pdf_path: Path, page_limit: int = VENDOR_PROBE_PAGES) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        return "\n".join(page.extract_text_simple() or "" for page in pdf.pages[:page_limit])


def vendor_scores(text: str) -> dict[str, int]:
    lowered = unicodedata.normalize("NFKC", text).lower()
    return {
        vendor: sum(lowered.count(marker) * weight for marker, weight in markers.items())
        for vendor, markers in VENDOR_MARKERS.items()
    }


def pick_vendor(scores: dict[str, int]) -> str | None:
    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    (winner, best), (_, runner_up) = ranked[0], ranked[1]
    if best == 0 or best == runner_up:
        return None
    return winner


def detect_vendor(pdf_path: Path) -> str | None:
    return pick_vendor(vendor_scores(probe_text(pdf_path)))
