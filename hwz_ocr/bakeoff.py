import argparse
import hashlib
import inspect
import io
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from hwz_ocr.extract_text import extract_layout
from hwz_ocr.qa import (
    count_numeric_tokens,
    price_only_recall,
    restrict_to_golden_products,
    row_f1,
)
from hwz_ocr.schema import DATA_DIR, MAX_PRICE_SGD, MIN_PRICE_SGD, SCANNED_VENDORS, PriceRow

GOLDEN_DIR = Path("tests/golden")
DEFAULT_PROVIDERS = ("gemini", "nvidia", "groq")
DEFAULT_OUTPUT = DATA_DIR / "bakeoff.md"
RENDER_DPI = 200
RECOVERABLE_ERRORS = (RuntimeError, ValueError, OSError, KeyError, TypeError, AttributeError)
TABLE_HEADER = (
    "| vendor | method | precision | recall | f1 | price_only_recall | latency "
    "| rows (pred/golden) | note |"
)
PARTIAL_GOLDEN_FOOTNOTE = (
    "On 'partial golden' pages only part of the page is labelled, so precision and f1 are "
    "computed on predicted rows whose product matches a labelled product; rows column shows "
    "all predicted rows."
)
TRAILING_PRICE = re.compile(r"^(?P<product>.*[A-Za-z].*?)[\s.:]*(?:S?\$\s?)?(?P<price>\d[\d,]*)$")


@dataclass
class GoldenPage:
    vendor: str
    pdf_path: Path
    page_number: int
    complete: bool
    rows: list[PriceRow]


@dataclass
class PageInput:
    sha256: str
    layout_text: str
    image_png: bytes | None
    numeric_tokens: int


@dataclass
class MethodOutcome:
    vendor: str
    method: str
    rows: list[PriceRow]
    latency_seconds: float
    error: str | None = None


def load_golden_pages(vendors: set[str] | None) -> list[GoldenPage]:
    pages = []
    for path in sorted(GOLDEN_DIR.glob("*.json")):
        payload = json.loads(path.read_text())
        vendor = path.stem.rsplit("_p", 1)[0]
        if vendors and vendor not in vendors:
            continue
        pages.append(
            GoldenPage(
                vendor=vendor,
                pdf_path=Path(payload["pdf"]),
                page_number=payload["page_number"],
                complete=payload.get("complete", True),
                rows=[PriceRow.model_validate(row) for row in payload["rows"]],
            )
        )
    return pages


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_layout_text(pdf_path: Path, page_number: int, vendor: str) -> str:
    return extract_layout(pdf_path, page_number, vendor=vendor)


def render_png(pdf_path: Path, page_number: int) -> bytes:
    from pdf2image import convert_from_path

    images = convert_from_path(
        pdf_path, dpi=RENDER_DPI, first_page=page_number, last_page=page_number
    )
    buffer = io.BytesIO()
    images[0].save(buffer, format="PNG")
    return buffer.getvalue()


def prepare_input(page: GoldenPage) -> PageInput:
    layout_text = read_layout_text(page.pdf_path, page.page_number, page.vendor)
    is_scanned = page.vendor in SCANNED_VENDORS
    image_png = render_png(page.pdf_path, page.page_number) if is_scanned else None
    return PageInput(
        sha256=file_sha256(page.pdf_path),
        layout_text=layout_text,
        image_png=image_png,
        numeric_tokens=count_numeric_tokens(layout_text),
    )


def parse_naive_line(line: str) -> PriceRow | None:
    match = TRAILING_PRICE.match(line.strip())
    if not match:
        return None
    price = int(match.group("price").replace(",", ""))
    product = match.group("product").strip(" .:-")
    if not MIN_PRICE_SGD <= price <= MAX_PRICE_SGD or len(product) < 3:
        return None
    return PriceRow(product=product, price_sgd=price)


def naive_parse(text: str) -> list[PriceRow]:
    parsed = (parse_naive_line(line) for line in text.splitlines())
    return [row for row in parsed if row is not None]


def tesseract_rows(image_png: bytes) -> list[PriceRow]:
    try:
        import pytesseract
        from PIL import Image
    except ImportError as error:
        raise RuntimeError(f"pytesseract unavailable: {error}") from error
    try:
        text = pytesseract.image_to_string(Image.open(io.BytesIO(image_png)), config="--psm 6")
    except pytesseract.TesseractNotFoundError as error:
        raise RuntimeError("tesseract binary not installed") from error
    return naive_parse(text)


def text_layer_rows(page: GoldenPage, layout_text: str) -> list[PriceRow]:
    try:
        from hwz_ocr.extract_text import extract_layout, parse_rows
    except ImportError:
        return naive_parse(layout_text)
    return parse_rows(extract_layout(page.pdf_path, page.page_number), page.vendor)


def run_baseline(page: GoldenPage, page_input: PageInput) -> list[PriceRow]:
    if page_input.image_png is not None:
        return tesseract_rows(page_input.image_png)
    return text_layer_rows(page, page_input.layout_text)


def build_single_provider_router(provider_name: str):
    try:
        from dotenv import load_dotenv

        from hwz_ocr.llm.providers import build_providers
        from hwz_ocr.llm.router import Router
    except ImportError as error:
        raise RuntimeError(f"LLM router not available: {error}") from error
    load_dotenv()
    providers = [provider for provider in build_providers() if provider.name == provider_name]
    if not providers:
        raise RuntimeError(f"provider {provider_name!r} not configured (missing API key?)")
    return Router(providers)


def run_provider(page: GoldenPage, page_input: PageInput, provider_name: str) -> list[PriceRow]:
    try:
        from hwz_ocr.structure import structure_page
    except ImportError as error:
        raise RuntimeError(f"hwz_ocr.structure.structure_page not available: {error}") from error
    result = structure_page(
        vendor=page.vendor,
        sha256=page_input.sha256,
        page_number=page.page_number,
        layout_text=page_input.layout_text or None,
        image_png=page_input.image_png,
        numeric_tokens_in_source=page_input.numeric_tokens,
        **routing_arguments(structure_page, provider_name),
    )
    if result.status == "quarantined" and not result.rows:
        raise RuntimeError(f"quarantined: {result.quarantine_reason}")
    if result.provider and result.provider != provider_name:
        raise RuntimeError(f"fell back to provider {result.provider}")
    return result.rows


def supports_preferred(structure_page: Callable) -> bool:
    return "preferred" in inspect.signature(structure_page).parameters


def routing_arguments(structure_page: Callable, provider_name: str) -> dict:
    if not supports_preferred(structure_page):
        return {"router": build_single_provider_router(provider_name)}
    try:
        from hwz_ocr.llm.router import Router
    except ImportError as error:
        raise RuntimeError(f"LLM router not available: {error}") from error
    return {"router": Router.from_env(), "preferred": [provider_name]}


def timed(vendor: str, method: str, action: Callable[[], list[PriceRow]]) -> MethodOutcome:
    started = time.perf_counter()
    try:
        rows = action()
        error = None
    except RECOVERABLE_ERRORS as failure:
        rows, error = [], f"{type(failure).__name__}: {failure}"
    return MethodOutcome(vendor, method, rows, time.perf_counter() - started, error)


def baseline_label(page: GoldenPage) -> str:
    return "baseline_tesseract" if page.vendor in SCANNED_VENDORS else "baseline_text"


def evaluate_page(page: GoldenPage, providers: list[str]) -> list[MethodOutcome]:
    page_input = prepare_input(page)
    outcomes = [timed(page.vendor, baseline_label(page), lambda: run_baseline(page, page_input))]
    for provider_name in providers:
        outcomes.append(
            timed(
                page.vendor,
                provider_name,
                lambda name=provider_name: run_provider(page, page_input, name),
            )
        )
    return outcomes


def scored_rows(page: GoldenPage, outcome: MethodOutcome) -> list[PriceRow]:
    if page.complete:
        return outcome.rows
    return restrict_to_golden_products(outcome.rows, page.rows)


def format_row(page: GoldenPage, outcome: MethodOutcome) -> str:
    precision, recall, f1 = row_f1(scored_rows(page, outcome), page.rows)
    price_recall = price_only_recall(outcome.rows, page.rows)
    note = outcome.error or ("" if page.complete else "partial golden")
    cells = [
        f"{page.vendor} p{page.page_number}",
        outcome.method,
        f"{precision:.2f}",
        f"{recall:.2f}",
        f"{f1:.2f}",
        f"{price_recall:.2f}",
        f"{outcome.latency_seconds:.1f}s",
        f"{len(outcome.rows)}/{len(page.rows)}",
        note.replace("|", "/")[:120],
    ]
    return "| " + " | ".join(cells) + " |"


def render_table(results: list[tuple[GoldenPage, MethodOutcome]]) -> str:
    header = [
        TABLE_HEADER,
        "|---|---|---|---|---|---|---|---|---|",
    ]
    body = [format_row(page, outcome) for page, outcome in results]
    footer = ["", PARTIAL_GOLDEN_FOOTNOTE]
    return "\n".join(header + body + footer) + "\n"


def parse_list(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip() and item.strip() != "none"]


def parse_arguments(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare extraction methods on golden pages")
    parser.add_argument("--providers", default=",".join(DEFAULT_PROVIDERS))
    parser.add_argument("--vendors", default="")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    arguments = parse_arguments(argv)
    providers = parse_list(arguments.providers)
    vendors = set(parse_list(arguments.vendors)) or None
    results = []
    for page in load_golden_pages(vendors):
        for outcome in evaluate_page(page, providers):
            results.append((page, outcome))
    table = render_table(results)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(table)
    print(table)


if __name__ == "__main__":
    main()
