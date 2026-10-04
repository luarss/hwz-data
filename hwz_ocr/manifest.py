import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from hwz_ocr.pdf_probe import (
    detect_vendor,
    has_text_layer,
    page_count,
    sha256_of,
    vendor_from_filename,
)
from hwz_ocr.schema import DATA_DIR, DOWNLOADS_DIR, MANIFEST_PATH, ManifestEntry, PageStatus

PAGE_STATE_PATH = DATA_DIR / "page_state.jsonl"
LOCAL_TIMEZONE = ZoneInfo("Asia/Singapore")
FINISHED_STATUSES = frozenset({PageStatus.DONE, PageStatus.QUARANTINED})


def load_manifest(path: Path = MANIFEST_PATH) -> dict[str, ManifestEntry]:
    if not path.exists():
        return {}
    entries: dict[str, ManifestEntry] = {}
    for line in path.read_text().splitlines():
        if line.strip():
            entry = ManifestEntry.model_validate_json(line)
            entries[entry.sha256] = entry
    return entries


def save_manifest(entries: dict[str, ManifestEntry], path: Path = MANIFEST_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [entries[sha256].model_dump_json() for sha256 in sorted(entries)]
    path.write_text("".join(f"{line}\n" for line in lines))


def today() -> date:
    return datetime.now(tz=LOCAL_TIMEZONE).date()


def month_of(pdf_path: Path) -> str:
    return pdf_path.parent.name


VENDOR_SOURCE_CONTENT = "content"
VENDOR_SOURCE_FILENAME = "filename"


def resolve_vendor(pdf_path: Path) -> dict[str, str]:
    filename_vendor = vendor_from_filename(pdf_path.name)
    detected = detect_vendor(pdf_path)
    if detected is None:
        return {
            "vendor": filename_vendor,
            "filename_vendor": filename_vendor,
            "vendor_source": VENDOR_SOURCE_FILENAME,
        }
    return {
        "vendor": detected,
        "filename_vendor": filename_vendor,
        "vendor_source": VENDOR_SOURCE_CONTENT,
    }


def new_entry(pdf_path: Path, sha256: str) -> ManifestEntry:
    return ManifestEntry(
        sha256=sha256,
        month=month_of(pdf_path),
        paths=[str(pdf_path)],
        page_count=page_count(pdf_path),
        has_text_layer=has_text_layer(pdf_path),
        first_seen=today(),
        **resolve_vendor(pdf_path),
    )


def ensure_vendor_resolved(entry: ManifestEntry, pdf_path: Path) -> ManifestEntry:
    if entry.filename_vendor is not None:
        return entry
    return entry.model_copy(update=resolve_vendor(pdf_path))


def merge_path(entry: ManifestEntry, pdf_path: Path) -> ManifestEntry:
    paths = sorted(set(entry.paths) | {str(pdf_path)})
    month = min(entry.month, month_of(pdf_path))
    return entry.model_copy(update={"paths": paths, "month": month})


def scan_downloads(
    downloads_dir: Path = DOWNLOADS_DIR,
    manifest: dict[str, ManifestEntry] | None = None,
) -> dict[str, ManifestEntry]:
    entries = dict(manifest or {})
    for pdf_path in sorted(downloads_dir.glob("*/*.pdf")):
        sha256 = sha256_of(pdf_path)
        if sha256 in entries:
            merged = merge_path(entries[sha256], pdf_path)
            entries[sha256] = ensure_vendor_resolved(merged, pdf_path)
        else:
            entries[sha256] = new_entry(pdf_path, sha256)
    return entries


def load_page_states(state_path: Path = PAGE_STATE_PATH) -> dict[str, dict[int, PageStatus]]:
    if not state_path.exists():
        return {}
    states: dict[str, dict[int, PageStatus]] = {}
    for line in state_path.read_text().splitlines():
        if line.strip():
            record = json.loads(line)
            pages = {int(page): PageStatus(status) for page, status in record["pages"].items()}
            states[record["sha256"]] = pages
    return states


def save_page_states(
    states: dict[str, dict[int, PageStatus]], state_path: Path = PAGE_STATE_PATH
) -> None:
    state_path.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for sha256 in sorted(states):
        pages = {str(page): str(status) for page, status in sorted(states[sha256].items())}
        lines.append(json.dumps({"sha256": sha256, "pages": pages}))
    state_path.write_text("".join(f"{line}\n" for line in lines))


def pending_pages(
    entry: ManifestEntry,
    state_path: Path = PAGE_STATE_PATH,
    include_quarantined: bool = False,
) -> list[int]:
    page_states = load_page_states(state_path).get(entry.sha256, {})
    finished = {PageStatus.DONE} if include_quarantined else FINISHED_STATUSES
    return [
        page for page in range(1, entry.page_count + 1) if page_states.get(page) not in finished
    ]


def apply_page_counters(entry: ManifestEntry, page_states: dict[int, PageStatus]) -> None:
    entry.pages_done = sum(1 for status in page_states.values() if status == PageStatus.DONE)
    entry.pages_quarantined = sum(
        1 for status in page_states.values() if status == PageStatus.QUARANTINED
    )
    entry.completed = entry.pages_done + entry.pages_quarantined >= entry.page_count


def record_page_status(
    entry: ManifestEntry,
    page_number: int,
    status: PageStatus,
    state_path: Path = PAGE_STATE_PATH,
) -> None:
    states = load_page_states(state_path)
    page_states = states.setdefault(entry.sha256, {})
    page_states[page_number] = status
    save_page_states(states, state_path)
    apply_page_counters(entry, page_states)
