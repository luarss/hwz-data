import csv
from pathlib import Path

import duckdb

from hwz_ocr.schema import (
    DATA_DIR,
    PRICES_DIR,
    QUARANTINE_DIR,
    ROLLUP_PATH,
    ROWS_DIR,
    ManifestEntry,
    PageResult,
)

ROW_COLUMNS = (
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
)
PRICE_COLUMNS = ("item", "price_sgd")
SHA_PREFIX_LENGTH = 8


def sha_prefix(sha256: str) -> str:
    return sha256[:SHA_PREFIX_LENGTH]


def subdir(data_dir: Path, default_dir: Path) -> Path:
    return data_dir / default_dir.relative_to(DATA_DIR)


def rows_csv_path(entry: ManifestEntry, data_dir: Path = DATA_DIR) -> Path:
    base = subdir(data_dir, ROWS_DIR)
    return base / entry.vendor / entry.month / f"{sha_prefix(entry.sha256)}.csv"


def prices_csv_path(entry: ManifestEntry, data_dir: Path = DATA_DIR) -> Path:
    base = subdir(data_dir, PRICES_DIR)
    return base / entry.vendor / entry.month / f"{sha_prefix(entry.sha256)}.csv"


def quarantine_path(entry: ManifestEntry, page_number: int, data_dir: Path = DATA_DIR) -> Path:
    base = subdir(data_dir, QUARANTINE_DIR)
    return base / entry.vendor / f"{sha_prefix(entry.sha256)}_p{page_number}.json"


def result_to_records(entry: ManifestEntry, result: PageResult) -> list[dict[str, str]]:
    records = []
    for row in result.rows:
        record = {
            "sha256": entry.sha256,
            "vendor": entry.vendor,
            "month": entry.month,
            "page_number": str(result.page_number),
            "item": row.item,
            "category": row.category or "",
            "brand": row.brand or "",
            "product": row.product,
            "variant": row.variant or "",
            "bundle_cpu": row.bundle_cpu or "",
            "warranty": row.warranty or "",
            "price_sgd": str(row.price_sgd),
            "method": str(result.method),
            "provider": result.provider or "",
            "model": result.model or "",
        }
        records.append(record)
    return records


def read_records(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle))


def write_records(path: Path, columns: tuple[str, ...], records: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        writer.writerows(
            {column: record.get(column, "") for column in columns} for record in records
        )


def replace_page_records(
    existing: list[dict[str, str]], page_number: int, new_records: list[dict[str, str]]
) -> list[dict[str, str]]:
    kept = [record for record in existing if int(record["page_number"]) != page_number]
    combined = kept + new_records
    return sorted(combined, key=lambda record: int(record["page_number"]))


def write_page_rows(entry: ManifestEntry, result: PageResult, data_dir: Path = DATA_DIR) -> Path:
    path = rows_csv_path(entry, data_dir)
    records = replace_page_records(
        read_records(path), result.page_number, result_to_records(entry, result)
    )
    write_records(path, ROW_COLUMNS, records)
    write_prices(entry, data_dir=data_dir)
    return path


def write_prices(
    entry: ManifestEntry,
    results_for_pdf: list[PageResult] | None = None,
    data_dir: Path = DATA_DIR,
) -> Path:
    if results_for_pdf is None:
        records = read_records(rows_csv_path(entry, data_dir))
    else:
        ordered_results = sorted(results_for_pdf, key=lambda result: result.page_number)
        records = [
            record for result in ordered_results for record in result_to_records(entry, result)
        ]
    path = prices_csv_path(entry, data_dir)
    write_records(path, PRICE_COLUMNS, records)
    return path


def remove_page_rows(entry: ManifestEntry, page_number: int, data_dir: Path = DATA_DIR) -> None:
    path = rows_csv_path(entry, data_dir)
    if not path.exists():
        return
    records = replace_page_records(read_records(path), page_number, [])
    write_records(path, ROW_COLUMNS, records)
    write_prices(entry, data_dir=data_dir)


def write_quarantine(entry: ManifestEntry, result: PageResult, data_dir: Path = DATA_DIR) -> Path:
    path = quarantine_path(entry, result.page_number, data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(indent=2) + "\n")
    remove_page_rows(entry, result.page_number, data_dir)
    return path


ROLLUP_COLUMN_TYPES = {
    "sha256": "VARCHAR",
    "vendor": "VARCHAR",
    "month": "VARCHAR",
    "page_number": "INTEGER",
    "item": "VARCHAR",
    "category": "VARCHAR",
    "brand": "VARCHAR",
    "product": "VARCHAR",
    "variant": "VARCHAR",
    "bundle_cpu": "VARCHAR",
    "warranty": "VARCHAR",
    "price_sgd": "DOUBLE",
    "method": "VARCHAR",
    "provider": "VARCHAR",
    "model": "VARCHAR",
}

LATEST_PRICES_VIEW = """
CREATE VIEW latest_prices AS
SELECT * EXCLUDE (latest_rank) FROM (
    SELECT *,
        row_number() OVER (
            PARTITION BY vendor, product, coalesce(variant, ''), coalesce(bundle_cpu, '')
            ORDER BY month DESC, sha256, page_number
        ) AS latest_rank
    FROM prices
) WHERE latest_rank = 1
"""


def create_prices_table(connection: duckdb.DuckDBPyConnection, csv_paths: list[Path]) -> None:
    column_definitions = ", ".join(
        f"{column} {column_type}" for column, column_type in ROLLUP_COLUMN_TYPES.items()
    )
    connection.execute(f"CREATE TABLE prices ({column_definitions})")
    if not csv_paths:
        return
    select_list = ", ".join(
        f"CAST(NULLIF({column}, '') AS {column_type}) AS {column}"
        for column, column_type in ROLLUP_COLUMN_TYPES.items()
    )
    connection.execute(
        f"INSERT INTO prices SELECT {select_list} "
        "FROM read_csv(?, header = true, all_varchar = true, union_by_name = true)",
        [[str(path) for path in csv_paths]],
    )


def build_rollup(data_dir: Path = DATA_DIR, rollup_path: Path = ROLLUP_PATH) -> Path:
    csv_paths = sorted(subdir(data_dir, ROWS_DIR).glob("**/*.csv"))
    rollup_path.parent.mkdir(parents=True, exist_ok=True)
    rollup_path.unlink(missing_ok=True)
    with duckdb.connect(str(rollup_path)) as connection:
        create_prices_table(connection, csv_paths)
        connection.execute(LATEST_PRICES_VIEW)
    return rollup_path
