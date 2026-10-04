from datetime import date
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

VENDORS = (
    "bizgram",
    "dynacore",
    "fuwell",
    "infinity",
    "laser",
    "pc_themes",
    "techdeals",
    "tradepac",
)

SCANNED_VENDORS = frozenset({"pc_themes", "tradepac"})
MATRIX_VENDORS = frozenset({"bizgram", "dynacore"})
IMAGE_COVERED_TEXT_VENDORS = frozenset({"dynacore"})

MIN_PRICE_SGD = 1
MAX_PRICE_SGD = 20000

DOWNLOADS_DIR = Path("downloads")
DATA_DIR = Path("data")
MANIFEST_PATH = DATA_DIR / "manifest.jsonl"
QUOTA_PATH = DATA_DIR / "quota.json"
ROLLUP_PATH = DATA_DIR / "prices.duckdb"
INTERMEDIATE_DIR = DATA_DIR / "intermediate"
ROWS_DIR = DATA_DIR / "rows"
PRICES_DIR = DATA_DIR / "prices"
QUARANTINE_DIR = DATA_DIR / "quarantine"


class ExtractionMethod(StrEnum):
    TEXT_LAYER = "text_layer"
    TEXT_LAYER_LLM = "text_layer_llm"
    VISION_LLM = "vision_llm"
    TESSERACT = "tesseract"


class PageStatus(StrEnum):
    PENDING = "pending"
    DONE = "done"
    QUARANTINED = "quarantined"


class PriceRow(BaseModel):
    category: str | None = None
    brand: str | None = None
    product: str = Field(min_length=1)
    variant: str | None = None
    bundle_cpu: str | None = None
    warranty: str | None = None
    price_sgd: float = Field(ge=MIN_PRICE_SGD, le=MAX_PRICE_SGD)

    @field_validator("price_sgd")
    @classmethod
    def round_to_cents(cls, value: float) -> float:
        rounded = round(value, 2)
        return int(rounded) if rounded == int(rounded) else rounded

    @property
    def item(self) -> str:
        parts = [self.product, self.variant]
        if self.bundle_cpu:
            parts.append(f"+ {self.bundle_cpu}")
        return " ".join(part for part in parts if part)

    @field_validator("product", "category", "brand", "variant", "bundle_cpu", "warranty")
    @classmethod
    def strip_whitespace(cls, value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = " ".join(value.split())
        return cleaned or None


class PageResult(BaseModel):
    sha256: str
    vendor: str
    page_number: int = Field(ge=1)
    method: ExtractionMethod
    provider: str | None = None
    model: str | None = None
    rows: list[PriceRow] = Field(default_factory=list)
    numeric_tokens_in_source: int = 0
    status: PageStatus = PageStatus.DONE
    quarantine_reason: str | None = None
    raw_response: str | None = None


class ManifestEntry(BaseModel):
    sha256: str
    vendor: str
    filename_vendor: str | None = None
    vendor_source: str = "filename"
    month: str
    paths: list[str]
    page_count: int
    has_text_layer: bool
    first_seen: date
    pages_done: int = 0
    pages_quarantined: int = 0
    completed: bool = False


class QaCheck(BaseModel):
    name: str
    passed: bool
    detail: str | None = None


class QaReport(BaseModel):
    sha256: str
    page_number: int
    checks: list[QaCheck]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)
