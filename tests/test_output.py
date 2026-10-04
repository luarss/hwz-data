import csv
from datetime import date

import duckdb

from hwz_ocr.output import build_rollup, write_page_rows, write_prices, write_quarantine
from hwz_ocr.schema import ExtractionMethod, ManifestEntry, PageResult, PageStatus, PriceRow

SHA = "abcdef0123456789" * 4
ROW_HEADER = [
    "sha256",
    "vendor",
    "month",
    "page_number",
    "item",
    "category",
    "brand",
    "product",
    "variant",
    "bundle_cpu",
    "warranty",
    "price_sgd",
    "method",
    "provider",
    "model",
]


def make_entry(month: str = "2026-09", sha256: str = SHA) -> ManifestEntry:
    return ManifestEntry(
        sha256=sha256,
        vendor="fuwell",
        month=month,
        paths=["downloads/x.pdf"],
        page_count=2,
        has_text_layer=True,
        first_seen=date(2026, 10, 1),
    )


def make_result(page_number: int, prices: list[int], product: str = "Widget") -> PageResult:
    rows = [
        PriceRow(
            product=f"{product} {index}", bundle_cpu="i5" if index == 0 else None, price_sgd=price
        )
        for index, price in enumerate(prices)
    ]
    return PageResult(
        sha256=SHA,
        vendor="fuwell",
        page_number=page_number,
        method=ExtractionMethod.TEXT_LAYER,
        rows=rows,
    )


def read_csv(path):
    with open(path, newline="") as handle:
        return list(csv.reader(handle))


def test_write_page_rows_creates_rows_and_prices(tmp_path):
    path = write_page_rows(make_entry(), make_result(1, [100, 200]), tmp_path)
    assert path == tmp_path / "rows" / "fuwell" / "2026-09" / "abcdef01.csv"
    content = read_csv(path)
    assert content[0] == ROW_HEADER
    assert len(content) == 3
    prices = read_csv(tmp_path / "prices" / "fuwell" / "2026-09" / "abcdef01.csv")
    assert prices == [["item", "price_sgd"], ["Widget 0 + i5", "100"], ["Widget 1", "200"]]


def test_write_page_rows_is_idempotent_per_page(tmp_path):
    entry = make_entry()
    write_page_rows(entry, make_result(2, [300]), tmp_path)
    write_page_rows(entry, make_result(1, [100, 200]), tmp_path)
    first = (tmp_path / "rows" / "fuwell" / "2026-09" / "abcdef01.csv").read_text()
    write_page_rows(entry, make_result(1, [100, 200]), tmp_path)
    path = write_page_rows(entry, make_result(2, [300]), tmp_path)
    assert path.read_text() == first
    pages = [row[3] for row in read_csv(path)[1:]]
    assert pages == ["1", "1", "2"]
    write_page_rows(entry, make_result(1, [150]), tmp_path)
    assert [row[11] for row in read_csv(path)[1:]] == ["150", "300"]
    prices = read_csv(tmp_path / "prices" / "fuwell" / "2026-09" / "abcdef01.csv")
    assert [row[1] for row in prices[1:]] == ["150", "300"]


def test_write_prices_from_results_orders_by_page(tmp_path):
    entry = make_entry()
    path = write_prices(entry, [make_result(2, [5]), make_result(1, [7])], data_dir=tmp_path)
    assert read_csv(path) == [["item", "price_sgd"], ["Widget 0 + i5", "7"], ["Widget 0 + i5", "5"]]


def test_write_quarantine_removes_page_rows(tmp_path):
    entry = make_entry()
    write_page_rows(entry, make_result(1, [100]), tmp_path)
    result = make_result(1, [100]).model_copy(
        update={"status": PageStatus.QUARANTINED, "quarantine_reason": "bad"}
    )
    path = write_quarantine(entry, result, tmp_path)
    assert path == tmp_path / "quarantine" / "fuwell" / "abcdef01_p1.json"
    assert PageResult.model_validate_json(path.read_text()).quarantine_reason == "bad"
    assert len(read_csv(tmp_path / "rows" / "fuwell" / "2026-09" / "abcdef01.csv")) == 1


def test_build_rollup_latest_prices(tmp_path):
    other_sha = "12345678" * 8
    write_page_rows(make_entry("2026-08", other_sha), make_result(1, [100, 200]), tmp_path)
    write_page_rows(make_entry("2026-09"), make_result(1, [89.9]), tmp_path)
    rollup_path = tmp_path / "prices.duckdb"
    build_rollup(tmp_path, rollup_path)
    with duckdb.connect(str(rollup_path), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM prices").fetchone()[0] == 3
        latest = connection.execute(
            "SELECT product, month, price_sgd FROM latest_prices ORDER BY product"
        ).fetchall()
    assert latest == [("Widget 0", "2026-09", 89.9), ("Widget 1", "2026-08", 200)]


def test_build_rollup_without_csvs(tmp_path):
    rollup_path = tmp_path / "prices.duckdb"
    build_rollup(tmp_path, rollup_path)
    with duckdb.connect(str(rollup_path), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM latest_prices").fetchone()[0] == 0
