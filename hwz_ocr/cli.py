import argparse
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from hwz_ocr.extract_text import SIMPLE_TEXT_VENDORS, extract_layout, parse_rows
from hwz_ocr.manifest import (
    PAGE_STATE_PATH,
    load_manifest,
    pending_pages,
    record_page_status,
    save_manifest,
    scan_downloads,
)
from hwz_ocr.output import (
    build_rollup,
    sha_prefix,
    subdir,
    write_page_rows,
    write_quarantine,
)
from hwz_ocr.pdf_probe import render_page_png
from hwz_ocr.schema import (
    DATA_DIR,
    DOWNLOADS_DIR,
    INTERMEDIATE_DIR,
    MANIFEST_PATH,
    MATRIX_VENDORS,
    MAX_PRICE_SGD,
    MIN_PRICE_SGD,
    ROLLUP_PATH,
    ExtractionMethod,
    ManifestEntry,
    PageResult,
    PageStatus,
)

INTEGER_TOKEN = re.compile(r"(?<![\d.])\d+(?![\d.])")
MIN_PAGE_TEXT_CHARS = 50


@dataclass
class PageSource:
    layout_text: str | None = None
    image_png: bytes | None = None


@dataclass
class ProcessTotals:
    statuses: Counter = field(default_factory=Counter)
    rows: int = 0


def manifest_path_for(data_dir: Path) -> Path:
    return subdir(data_dir, MANIFEST_PATH)


def page_state_path_for(data_dir: Path) -> Path:
    return subdir(data_dir, PAGE_STATE_PATH)


def count_numeric_tokens(text: str | None) -> int:
    if not text:
        return 0
    try:
        from hwz_ocr.qa import count_numeric_tokens as qa_count_numeric_tokens
    except ImportError:
        return sum(
            1
            for token in INTEGER_TOKEN.findall(text)
            if MIN_PRICE_SGD <= int(token) <= MAX_PRICE_SGD
        )
    return qa_count_numeric_tokens(text)


def intermediate_dir_for(entry: ManifestEntry, data_dir: Path) -> Path:
    return subdir(data_dir, INTERMEDIATE_DIR) / entry.vendor / sha_prefix(entry.sha256)


def write_intermediate(entry: ManifestEntry, data_dir: Path, filename: str, content: str) -> None:
    directory = intermediate_dir_for(entry, data_dir)
    directory.mkdir(parents=True, exist_ok=True)
    (directory / filename).write_text(content)


def has_usable_text(layout_text: str) -> bool:
    return sum(1 for character in layout_text if not character.isspace()) >= MIN_PAGE_TEXT_CHARS


def load_page_source(
    entry: ManifestEntry, page_number: int, data_dir: Path, use_llm: bool
) -> PageSource:
    pdf_path = Path(entry.paths[0])
    if entry.has_text_layer:
        layout_text = extract_layout(pdf_path, page_number, vendor=entry.vendor)
        if has_usable_text(layout_text):
            write_intermediate(entry, data_dir, f"p{page_number}.txt", layout_text)
            return PageSource(layout_text=layout_text)
    if not use_llm:
        return PageSource()
    return PageSource(image_png=render_page_png(pdf_path, page_number))


def call_llm(entry: ManifestEntry, page_number: int, source: PageSource) -> PageResult | None:
    try:
        from hwz_ocr.structure import structure_page
    except ImportError as error:
        print(f"  llm unavailable: {error}", file=sys.stderr)
        return None
    result = structure_page(
        vendor=entry.vendor,
        sha256=entry.sha256,
        page_number=page_number,
        layout_text=source.layout_text,
        image_png=source.image_png,
        numeric_tokens_in_source=count_numeric_tokens(source.layout_text),
    )
    if result.status == PageStatus.PENDING:
        return None
    return result


def try_text_parser(entry: ManifestEntry, page_number: int, layout_text: str) -> PageResult | None:
    rows = parse_rows(layout_text, entry.vendor)
    if not rows:
        return None
    return PageResult(
        sha256=entry.sha256,
        vendor=entry.vendor,
        page_number=page_number,
        method=ExtractionMethod.TEXT_LAYER,
        rows=rows,
        numeric_tokens_in_source=count_numeric_tokens(layout_text),
    )


def deterministic_result(
    entry: ManifestEntry, page_number: int, source: PageSource
) -> PageResult | None:
    if source.layout_text is None or entry.vendor in MATRIX_VENDORS:
        return None
    return try_text_parser(entry, page_number, source.layout_text)


def llm_result(
    entry: ManifestEntry, page_number: int, source: PageSource, use_llm: bool
) -> PageResult | None:
    if not use_llm:
        return None
    result = call_llm(entry, page_number, source)
    if result is None:
        return None
    return apply_qa(result, source)


def extract_page(
    entry: ManifestEntry, page_number: int, source: PageSource, use_llm: bool
) -> PageResult | None:
    parsed = deterministic_result(entry, page_number, source)
    if parsed is None:
        return llm_result(entry, page_number, source, use_llm)
    parsed = apply_qa(parsed, source)
    if parsed.status != PageStatus.QUARANTINED:
        return parsed
    return llm_result(entry, page_number, source, use_llm)


def failed_checks_reason(report) -> str:
    failures = [check for check in report.checks if not check.passed]
    return "; ".join(
        f"{check.name}: {check.detail}" if check.detail else check.name for check in failures
    )


def apply_qa(result: PageResult, source: PageSource) -> PageResult:
    try:
        from hwz_ocr.qa import check_page
    except ImportError:
        return result
    report = check_page(result, source.layout_text, source.image_png)
    if report.passed:
        return result
    return result.model_copy(
        update={
            "status": PageStatus.QUARANTINED,
            "quarantine_reason": failed_checks_reason(report),
        }
    )


def persist_result(entry: ManifestEntry, result: PageResult, data_dir: Path) -> None:
    if result.raw_response is not None:
        write_intermediate(entry, data_dir, f"p{result.page_number}.llm.json", result.raw_response)
    if result.status == PageStatus.QUARANTINED:
        write_quarantine(entry, result, data_dir)
    else:
        write_page_rows(entry, result, data_dir)


def describe_page(entry: ManifestEntry, page_number: int, result: PageResult | None) -> str:
    prefix = f"{entry.vendor:<10} {entry.month} {sha_prefix(entry.sha256)} p{page_number:<3}"
    if result is None:
        return f"{prefix} pending"
    line = f"{prefix} {result.status} {result.method} rows={len(result.rows)}"
    if result.quarantine_reason:
        line += f" reason={result.quarantine_reason}"
    return line


def process_page(
    entry: ManifestEntry, page_number: int, data_dir: Path, use_llm: bool
) -> PageResult | None:
    source = load_page_source(entry, page_number, data_dir, use_llm)
    result = extract_page(entry, page_number, source, use_llm)
    if result is None:
        return None
    persist_result(entry, result, data_dir)
    record_page_status(entry, page_number, result.status, page_state_path_for(data_dir))
    return result


def parseable_without_llm(entry: ManifestEntry) -> bool:
    return entry.has_text_layer and entry.vendor in SIMPLE_TEXT_VENDORS


def select_entries(
    manifest: dict[str, ManifestEntry], vendor: str | None, sha: str | None, use_llm: bool
) -> list[ManifestEntry]:
    selected = [
        entry
        for entry in manifest.values()
        if (vendor is None or entry.vendor == vendor)
        and (sha is None or entry.sha256.startswith(sha))
        and (use_llm or parseable_without_llm(entry))
    ]
    return sorted(selected, key=lambda entry: (entry.vendor, entry.month, entry.sha256))


def run_scan(arguments: argparse.Namespace) -> int:
    manifest_path = manifest_path_for(arguments.data_dir)
    manifest = scan_downloads(arguments.downloads_dir, load_manifest(manifest_path))
    save_manifest(manifest, manifest_path)
    file_count = sum(len(entry.paths) for entry in manifest.values())
    print(f"scanned {file_count} files, {len(manifest)} unique pdfs")
    return 0


def page_queue(arguments: argparse.Namespace, manifest: dict[str, ManifestEntry]):
    state_path = page_state_path_for(arguments.data_dir)
    entries = select_entries(manifest, arguments.vendor, arguments.sha, not arguments.no_llm)
    for entry in entries:
        for page_number in pending_pages(entry, state_path, arguments.retry_quarantined):
            yield entry, page_number


def counted_toward_budget(totals: ProcessTotals, use_llm: bool) -> int:
    if use_llm:
        return sum(totals.statuses.values())
    return totals.statuses[PageStatus.DONE] + totals.statuses[PageStatus.QUARANTINED]


def budget_exhausted(totals: ProcessTotals, use_llm: bool, max_pages: int | None) -> bool:
    return max_pages is not None and counted_toward_budget(totals, use_llm) >= max_pages


def run_process(arguments: argparse.Namespace) -> int:
    manifest_path = manifest_path_for(arguments.data_dir)
    manifest = load_manifest(manifest_path)
    use_llm = not arguments.no_llm
    totals = ProcessTotals()
    for entry, page_number in page_queue(arguments, manifest):
        if budget_exhausted(totals, use_llm, arguments.max_pages):
            break
        result = process_page(entry, page_number, arguments.data_dir, use_llm)
        print(describe_page(entry, page_number, result), flush=True)
        totals.statuses[result.status if result else PageStatus.PENDING] += 1
        totals.rows += len(result.rows) if result else 0
        save_manifest(manifest, manifest_path)
    print(
        f"total pages={sum(totals.statuses.values())} "
        f"done={totals.statuses[PageStatus.DONE]} "
        f"quarantined={totals.statuses[PageStatus.QUARANTINED]} "
        f"pending={totals.statuses[PageStatus.PENDING]} rows={totals.rows}"
    )
    return 0


def run_rollup(arguments: argparse.Namespace) -> int:
    rollup_path = subdir(arguments.data_dir, ROLLUP_PATH)
    build_rollup(arguments.data_dir, rollup_path)
    print(f"rollup written to {rollup_path}")
    return 0


def pages_todo(entry: ManifestEntry) -> int:
    return max(0, entry.page_count - entry.pages_done - entry.pages_quarantined)


def summarize(entries: list[ManifestEntry]) -> str:
    files = sum(len(entry.paths) for entry in entries)
    pages = sum(entry.page_count for entry in entries)
    done = sum(entry.pages_done for entry in entries)
    quarantined = sum(entry.pages_quarantined for entry in entries)
    todo = sum(pages_todo(entry) for entry in entries)
    completed = sum(1 for entry in entries if entry.completed)
    return (
        f"files={files} unique={len(entries)} pages={pages} done={done} "
        f"quarantined={quarantined} todo={todo} completed_pdfs={completed}"
    )


def run_stats(arguments: argparse.Namespace) -> int:
    manifest = load_manifest(manifest_path_for(arguments.data_dir))
    entries = list(manifest.values())
    print(f"{'total':<10} {summarize(entries)}")
    for vendor in sorted({entry.vendor for entry in entries}):
        vendor_entries = [entry for entry in entries if entry.vendor == vendor]
        print(f"{vendor:<10} {summarize(vendor_entries)}")
    print(f"total_pending={sum(pages_todo(entry) for entry in entries)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="hwz_ocr")
    parser.add_argument("--data-dir", type=Path, default=DATA_DIR)
    parser.add_argument("--downloads-dir", type=Path, default=DOWNLOADS_DIR)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("scan").set_defaults(handler=run_scan)
    process = commands.add_parser("process")
    process.add_argument("--vendor")
    process.add_argument("--sha")
    process.add_argument("--max-pages", type=int)
    process.add_argument("--no-llm", action="store_true")
    process.add_argument("--retry-quarantined", action="store_true")
    process.set_defaults(handler=run_process)
    commands.add_parser("rollup").set_defaults(handler=run_rollup)
    commands.add_parser("stats").set_defaults(handler=run_stats)
    return parser


def main(argv: list[str] | None = None) -> int:
    arguments = build_parser().parse_args(argv)
    return arguments.handler(arguments)
