import re
import statistics
from dataclasses import dataclass
from pathlib import Path

import pdfplumber

from hwz_ocr.schema import IMAGE_COVERED_TEXT_VENDORS, MAX_PRICE_SGD, MIN_PRICE_SGD, PriceRow

SIMPLE_TEXT_VENDORS = frozenset({"fuwell", "infinity", "laser", "techdeals"})

WORD_X_TOLERANCE = 1.5
LINE_Y_TOLERANCE = 2.0
WORD_GAP_FACTOR = 0.6
DEFAULT_CHAR_WIDTH = 3.0
MIN_COLUMN_GAP = 2
CELL_PATTERN = re.compile(r"\S+(?: \S+)*")
PRICE_PATTERN = re.compile(r"^\$?(\d{1,3}(?:,\d{3})+|\d{1,5})(\.\d{1,2})?$")
CURRENCY_SYMBOL = "$"
INNER_WHITESPACE = re.compile(r"\s+")
DASH_PATTERN = re.compile(r"^[-–—]+$")
MIN_PRODUCT_LETTERS = 3
MAX_HEADER_WORDS = 6
HEADER_COLUMN_SLACK = 4
IGNORED_HEADERS = frozenset({"price", "prices", "price list", "m/b", "alone"})


@dataclass(frozen=True)
class Cell:
    column: int
    text: str


def extract_layout(pdf_path: Path, page_number: int, vendor: str | None = None) -> str:
    with pdfplumber.open(pdf_path) as pdf:
        page = pdf.pages[page_number - 1]
        words = page.extract_words(x_tolerance=WORD_X_TOLERANCE, extra_attrs=["size"])
        if vendor in IMAGE_COVERED_TEXT_VENDORS:
            words = drop_image_covered_words(words, page.images)
    if not words:
        return ""
    char_width = median_char_width(words)
    lines = cluster_lines(words)
    return "\n".join(render_line(line, char_width) for line in lines)


def word_center(word: dict) -> tuple[float, float]:
    return (word["x0"] + word["x1"]) / 2, (word["top"] + word["bottom"]) / 2


def is_inside_image(point: tuple[float, float], image: dict) -> bool:
    x, y = point
    return image["x0"] <= x <= image["x1"] and image["top"] <= y <= image["bottom"]


def drop_image_covered_words(words: list[dict], images: list[dict]) -> list[dict]:
    return [
        word
        for word in words
        if not any(is_inside_image(word_center(word), image) for image in images)
    ]


def median_char_width(words: list[dict]) -> float:
    widths = [(word["x1"] - word["x0"]) / len(word["text"]) for word in words if word["text"]]
    positive_widths = [width for width in widths if width > 0]
    if not positive_widths:
        return DEFAULT_CHAR_WIDTH
    return statistics.median(positive_widths)


def word_center_y(word: dict) -> float:
    return (word["top"] + word["bottom"]) / 2


def cluster_lines(words: list[dict]) -> list[list[dict]]:
    lines: list[list[dict]] = []
    line_centers: list[float] = []
    for word in sorted(words, key=word_center_y):
        center = word_center_y(word)
        if line_centers and center - line_centers[-1] <= LINE_Y_TOLERANCE:
            lines[-1].append(word)
            continue
        lines.append([word])
        line_centers.append(center)
    return [sorted(line, key=lambda word: word["x0"]) for line in lines]


def is_tight_gap(previous: dict, current: dict) -> bool:
    font_size = max(previous.get("size", 6.0), current.get("size", 6.0), 1.0)
    return current["x0"] - previous["x1"] <= font_size * WORD_GAP_FACTOR


def render_line(line: list[dict], char_width: float) -> str:
    text = ""
    previous = None
    for word in line:
        if previous is not None and is_tight_gap(previous, word):
            text += " "
        elif previous is not None:
            target_column = round(word["x0"] / char_width)
            padding = max(MIN_COLUMN_GAP, target_column - len(text))
            text += " " * padding
        else:
            text += " " * round(word["x0"] / char_width)
        text += word["text"]
        previous = word
    return text.rstrip()


def split_cells(line: str) -> list[Cell]:
    cells = [Cell(match.start(), match.group()) for match in CELL_PATTERN.finditer(line)]
    return merge_currency_cells(cells)


def merge_currency_cells(cells: list[Cell]) -> list[Cell]:
    merged: list[Cell] = []
    for cell in cells:
        if merged and merged[-1].text == CURRENCY_SYMBOL:
            merged[-1] = Cell(merged[-1].column, f"{CURRENCY_SYMBOL}{cell.text}")
        else:
            merged.append(cell)
    return merged


def compact_price_text(text: str) -> str:
    if text.startswith(CURRENCY_SYMBOL):
        return INNER_WHITESPACE.sub("", text)
    return text


def parse_price(text: str) -> float | None:
    match = PRICE_PATTERN.match(compact_price_text(text))
    if not match:
        return None
    whole, fraction = match.group(1), match.group(2) or ""
    value = float(whole.replace(",", "") + fraction)
    if MIN_PRICE_SGD <= value <= MAX_PRICE_SGD:
        return value
    return None


def is_numeric_cell(text: str) -> bool:
    compact = compact_price_text(text)
    return PRICE_PATTERN.match(compact) is not None or DASH_PATTERN.match(compact) is not None


def is_name_cell(text: str) -> bool:
    return sum(character.isalpha() for character in text) >= MIN_PRODUCT_LETTERS


def group_cells(cells: list[Cell]) -> list[tuple[Cell, list[Cell]]]:
    groups: list[tuple[Cell, list[Cell]]] = []
    for cell in cells:
        if is_name_cell(cell.text):
            groups.append((cell, []))
        elif groups:
            groups[-1][1].append(cell)
    return groups


def is_header_like(name: Cell) -> bool:
    lowered = name.text.lower()
    return lowered not in IGNORED_HEADERS and len(name.text.split()) <= MAX_HEADER_WORDS


def remember_header(headers: dict[int, str], name: Cell) -> None:
    for column in list(headers):
        if abs(column - name.column) <= HEADER_COLUMN_SLACK:
            del headers[column]
    headers[name.column] = name.text


def category_for(headers: dict[int, str], column: int) -> str | None:
    candidates = [start for start in headers if start <= column + HEADER_COLUMN_SLACK]
    if not candidates:
        return None
    return headers[max(candidates)]


def row_from_group(name: Cell, values: list[Cell], category: str | None) -> PriceRow | None:
    if len(values) != 1:
        return None
    price = parse_price(values[0].text)
    if price is None:
        return None
    return PriceRow(category=category, product=name.text, price_sgd=price)


def parse_line(line: str, headers: dict[int, str]) -> list[PriceRow]:
    rows: list[PriceRow] = []
    for name, values in group_cells(split_cells(line)):
        if not values:
            if is_header_like(name):
                remember_header(headers, name)
            continue
        row = row_from_group(name, values, category_for(headers, name.column))
        if row is not None:
            rows.append(row)
    return rows


def parse_rows(layout_text: str, vendor: str) -> list[PriceRow]:
    if vendor not in SIMPLE_TEXT_VENDORS:
        return []
    headers: dict[int, str] = {}
    rows: list[PriceRow] = []
    for line in layout_text.splitlines():
        rows.extend(parse_line(line, headers))
    return rows
