import shutil
from pathlib import Path

from hwz_ocr.manifest import (
    load_manifest,
    pending_pages,
    record_page_status,
    save_manifest,
    scan_downloads,
)
from hwz_ocr.schema import PageStatus

SAMPLE_DIR = Path("downloads/2026-09")
FUWELL_NAME = "fuwell_1YG84yiFPeZzEYqG9LzifoIBcNslLe9nA.pdf"
INFINITY_NAME = "infinity_1DhfsitDgo6sop0tBc_qadk54ZO0QDl_G.pdf"


def build_downloads(root: Path) -> Path:
    downloads = root / "downloads"
    (downloads / "2026-08").mkdir(parents=True)
    (downloads / "2026-09").mkdir(parents=True)
    shutil.copy(SAMPLE_DIR / FUWELL_NAME, downloads / "2026-09" / FUWELL_NAME)
    shutil.copy(SAMPLE_DIR / FUWELL_NAME, downloads / "2026-08" / "fuwell_copy.pdf")
    shutil.copy(SAMPLE_DIR / INFINITY_NAME, downloads / "2026-09" / INFINITY_NAME)
    return downloads


def test_scan_dedupes_and_merges_paths(tmp_path):
    downloads = build_downloads(tmp_path)
    entries = scan_downloads(downloads, {})
    assert len(entries) == 2
    fuwell = next(entry for entry in entries.values() if entry.vendor == "fuwell")
    assert len(fuwell.paths) == 2
    assert fuwell.month == "2026-08"
    assert fuwell.has_text_layer
    assert fuwell.page_count == 2


def test_rescan_preserves_first_seen_and_progress(tmp_path):
    downloads = build_downloads(tmp_path)
    entries = scan_downloads(downloads, {})
    fuwell = next(entry for entry in entries.values() if entry.vendor == "fuwell")
    fuwell.pages_done = 1
    rescanned = scan_downloads(downloads, entries)
    assert rescanned[fuwell.sha256].pages_done == 1
    assert rescanned[fuwell.sha256].first_seen == fuwell.first_seen


def test_save_and_load_roundtrip_is_sorted_and_stable(tmp_path):
    entries = scan_downloads(build_downloads(tmp_path), {})
    manifest_path = tmp_path / "manifest.jsonl"
    save_manifest(entries, manifest_path)
    first_content = manifest_path.read_text()
    save_manifest(load_manifest(manifest_path), manifest_path)
    assert manifest_path.read_text() == first_content
    lines = first_content.splitlines()
    assert lines == sorted(lines)
    assert load_manifest(manifest_path) == entries


def test_load_missing_manifest_is_empty(tmp_path):
    assert load_manifest(tmp_path / "missing.jsonl") == {}


def test_pending_pages_tracks_page_states(tmp_path):
    entries = scan_downloads(build_downloads(tmp_path), {})
    fuwell = next(entry for entry in entries.values() if entry.vendor == "fuwell")
    state_path = tmp_path / "page_state.jsonl"
    assert pending_pages(fuwell, state_path) == [1, 2]
    record_page_status(fuwell, 1, PageStatus.DONE, state_path)
    assert pending_pages(fuwell, state_path) == [2]
    assert fuwell.pages_done == 1
    assert not fuwell.completed
    record_page_status(fuwell, 2, PageStatus.QUARANTINED, state_path)
    assert pending_pages(fuwell, state_path) == []
    assert fuwell.pages_quarantined == 1
    assert fuwell.completed


def test_pending_pages_can_include_quarantined(tmp_path):
    entries = scan_downloads(build_downloads(tmp_path), {})
    fuwell = next(entry for entry in entries.values() if entry.vendor == "fuwell")
    state_path = tmp_path / "page_state.jsonl"
    record_page_status(fuwell, 1, PageStatus.DONE, state_path)
    record_page_status(fuwell, 2, PageStatus.QUARANTINED, state_path)
    assert pending_pages(fuwell, state_path, include_quarantined=True) == [2]


def test_scan_corrects_vendor_from_content(tmp_path):
    downloads = tmp_path / "downloads"
    (downloads / "2025-09").mkdir(parents=True)
    mislabelled = "pc_themes_1gEHPU9so4bob7ut8dzoVwxmX_OLqZtnp.pdf"
    shutil.copy(Path("downloads/2025-09") / mislabelled, downloads / "2025-09" / mislabelled)
    entry = next(iter(scan_downloads(downloads, {}).values()))
    assert entry.vendor == "techdeals"
    assert entry.filename_vendor == "pc_themes"
    assert entry.vendor_source == "content"


def test_scan_resolves_vendor_for_legacy_entries(tmp_path):
    entries = scan_downloads(build_downloads(tmp_path), {})
    legacy = {
        sha256: entry.model_copy(update={"filename_vendor": None, "vendor_source": "filename"})
        for sha256, entry in entries.items()
    }
    rescanned = scan_downloads(tmp_path / "downloads", legacy)
    assert all(entry.filename_vendor is not None for entry in rescanned.values())
    assert all(entry.vendor_source == "content" for entry in rescanned.values())
