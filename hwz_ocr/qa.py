import re
import string
from collections import Counter

from hwz_ocr.schema import MAX_PRICE_SGD, MIN_PRICE_SGD, PageResult, PriceRow, QaCheck, QaReport

NUMERIC_RECALL_THRESHOLD = 0.6
DUPLICATE_RATIO_LIMIT = 0.10
ROW_COUNT_TOKEN_MULTIPLIER = 2
ROW_COUNT_SLACK = 5
UNKNOWN_PRODUCT_RATIO_LIMIT = 0.20
MIN_PRODUCT_LENGTH = 3
COVER_PAGE_MAX_TOKENS = 5
COVER_PAGE_KEYWORDS = ("terms", "warranty", "opening hours", "address")

MONTH_NAMES = (
    r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|jun(?:e)?|jul(?:y)?|aug(?:ust)?"
    r"|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)"
)
YEAR = r"20(?:19|2[0-7])"
SPLIT_DIGIT_PRICE = re.compile(r"(\$\s*\d{1,2}) (\d{1,2}\.\d{2})\b")
SPACED_MONTH = re.compile(r"\b((?:[a-z] ){2,}[a-z])\b", re.IGNORECASE)
NON_PRICE_SPANS = [
    re.compile(r"\b\d{1,2}[/.\-]\d{1,2}[/.\-]\d{2,4}\b"),
    re.compile(
        rf"\b\d{{1,2}}(?:st|nd|rd|th)?[\s\-]*{MONTH_NAMES}\b[\s\-,]*(?:{YEAR}|\d{{2}})?",
        re.IGNORECASE,
    ),
    re.compile(rf"\b{MONTH_NAMES}\b[\s\-,]*(?:\d{{1,2}})?[\s\-,]*{YEAR}\b", re.IGNORECASE),
    re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b"),
    re.compile(
        r"(?:\+65|\btel\b|\bphone\b|\bwhatsapp\b|\bhp\b|\bcall\b|\bfax\b|\bmobile\b)"
        r"[\s:.\-()/+65]*\d{4}[\s\-]?\d{4}\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b[3689]\d{7}\b"),
    re.compile(r"\b65[\s\-]?[3689]\d{3}[\s\-]?\d{4}\b"),
    re.compile(r"#\s?\d{1,3}\s?-\s?\d{1,4}"),
    re.compile(r"\bpage\s+\d+\s*(?:of\s+\d+)?\b", re.IGNORECASE),
    re.compile(r"\bpg\.?\s*\d+\b", re.IGNORECASE),
    re.compile(r"\b\d+\s*:\s*\d+\b"),
    re.compile(r"\b\d+(?:\.\d+)?\s*%"),
]
MODEL_FAMILY_PREFIX = re.compile(
    r"(?:\b(?:rtx|gtx|rx|gt|radeon|ryzen(?:\s[3579])?|ultra(?:\s[3579])?|core|i[3579]|ddr\d"
    r"|gen|usb|hdmi|displayport|wi-?fi|pcie|bluetooth|cat\.?|type|series|socket|lga|am[45]|no\.?|model|version|v)\s?)$",
    re.IGNORECASE,
)
UNIT_SUFFIX = re.compile(
    r"\s?(?:years?|yrs?|months?|mths?|days?|pcs|pack|ports?|bays?|fans?|mm|cm|m|gb|tb|mb|kb"
    r"|w|hz|ghz|mhz|inch|in|cores?|threads?|channels?|outlets?|sockets?|mp|k|nm|v|va|x)\b",
    re.IGNORECASE,
)
PRICE_CANDIDATE = re.compile(
    r"(?P<prefix>S\$|\$)?\s?(?P<number>\d{1,3}(?:,\d{3})+|\d+)(?P<decimals>\.\d+)?"
)
CPU_BRAND_WORDS = frozenset(
    {"intel", "core", "ultra", "amd", "ryzen", "processor", "cpu", "gen", "series"}
)
CPU_TIER_TOKEN = re.compile(r"(?:[uir]\d|\d)")
PUNCTUATION_TABLE = str.maketrans({character: " " for character in string.punctuation})


def collapse_spaced_letters(match: re.Match) -> str:
    return match.group(1).replace(" ", "")


def blank_out(text: str, pattern: re.Pattern) -> str:
    return pattern.sub(lambda match: " " * len(match.group()), text)


def prepare_text(text: str) -> str:
    prepared = SPLIT_DIGIT_PRICE.sub(r"\1\2", text)
    prepared = SPACED_MONTH.sub(collapse_spaced_letters, prepared)
    for pattern in NON_PRICE_SPANS:
        prepared = blank_out(prepared, pattern)
    return prepared


def glued_to_word(text: str, start: int, end: int) -> bool:
    before = text[start - 1] if start > 0 else " "
    after = text[end] if end < len(text) else " "
    if before.isalnum() or before in "-/._×*+'\"”" or after in "%\"”'″":
        return True
    if after.isalpha() or after in "-/×*+":
        return True
    return after == "." and end + 1 < len(text) and text[end + 1].isalnum()


def preceded_by_multiplier(text: str, start: int) -> bool:
    return re.search(r"[x×*]\s?$", text[max(0, start - 2) : start], re.IGNORECASE) is not None


def candidate_is_price(text: str, match: re.Match) -> bool:
    has_prefix = match.group("prefix") is not None
    start = match.start("prefix") if has_prefix else match.start("number")
    if glued_to_word(text, start, match.end()):
        return False
    decimals = match.group("decimals")
    if decimals and not has_prefix and len(decimals) != 3:
        return False
    if not has_prefix:
        if preceded_by_multiplier(text, start):
            return False
        if MODEL_FAMILY_PREFIX.search(text[max(0, start - 16) : start]):
            return False
        if UNIT_SUFFIX.match(text, match.end()):
            return False
    value = int(match.group("number").replace(",", ""))
    return MIN_PRICE_SGD <= value <= MAX_PRICE_SGD


def count_numeric_tokens(text: str) -> int:
    prepared = prepare_text(text)
    return sum(
        1 for match in PRICE_CANDIDATE.finditer(prepared) if candidate_is_price(prepared, match)
    )


def is_cover_page(layout_text: str | None) -> bool:
    if not layout_text:
        return False
    lowered = layout_text.lower()
    has_keyword = any(keyword in lowered for keyword in COVER_PAGE_KEYWORDS)
    return has_keyword and count_numeric_tokens(layout_text) < COVER_PAGE_MAX_TOKENS


def check_numeric_recall(result: PageResult, cover: bool) -> QaCheck:
    source_tokens = result.numeric_tokens_in_source
    if source_tokens == 0:
        detail = "cover page" if cover else "no numeric tokens in source"
        return QaCheck(name="numeric_recall", passed=True, detail=detail)
    recall = len(result.rows) / max(source_tokens, 1)
    return QaCheck(
        name="numeric_recall",
        passed=recall >= NUMERIC_RECALL_THRESHOLD,
        detail=f"{len(result.rows)}/{source_tokens} = {recall:.2f}",
    )


def check_price_range(result: PageResult) -> QaCheck:
    out_of_range = [
        row.price_sgd for row in result.rows if not MIN_PRICE_SGD <= row.price_sgd <= MAX_PRICE_SGD
    ]
    detail = f"out of range: {out_of_range[:5]}" if out_of_range else None
    return QaCheck(name="price_range", passed=not out_of_range, detail=detail)


def row_identity(row: PriceRow) -> tuple:
    return (row.product, row.variant, row.bundle_cpu, row.price_sgd)


def check_no_dupe_rows(result: PageResult) -> QaCheck:
    counts = Counter(row_identity(row) for row in result.rows)
    duplicated = [identity for identity, count in counts.items() if count > 1]
    extra_rows = sum(count - 1 for count in counts.values())
    ratio = extra_rows / len(result.rows) if result.rows else 0.0
    detail = f"{extra_rows} extra rows ({ratio:.0%}): {duplicated[:3]}" if duplicated else None
    return QaCheck(name="no_dupe_rows", passed=ratio <= DUPLICATE_RATIO_LIMIT, detail=detail)


def check_row_count_plausible(result: PageResult) -> QaCheck:
    source_tokens = result.numeric_tokens_in_source
    if source_tokens == 0:
        return QaCheck(name="row_count_plausible", passed=True, detail="no numeric tokens")
    limit = ROW_COUNT_TOKEN_MULTIPLIER * source_tokens + ROW_COUNT_SLACK
    return QaCheck(
        name="row_count_plausible",
        passed=len(result.rows) <= limit,
        detail=f"{len(result.rows)} rows, limit {limit}",
    )


def check_not_empty(result: PageResult, cover: bool) -> QaCheck:
    if result.rows:
        return QaCheck(name="not_empty", passed=True, detail=f"{len(result.rows)} rows")
    detail = "cover page" if cover else "no rows extracted"
    return QaCheck(name="not_empty", passed=cover, detail=detail)


def is_insane_product(product: str) -> bool:
    return product.strip().upper() == "UNKNOWN" or len(product.strip()) < MIN_PRODUCT_LENGTH


def check_product_names_sane(result: PageResult) -> QaCheck:
    if not result.rows:
        return QaCheck(name="product_names_sane", passed=True, detail="no rows")
    insane = sum(1 for row in result.rows if is_insane_product(row.product))
    ratio = insane / len(result.rows)
    return QaCheck(
        name="product_names_sane",
        passed=ratio < UNKNOWN_PRODUCT_RATIO_LIMIT,
        detail=f"{insane}/{len(result.rows)} unknown or short",
    )


def check_page(result: PageResult, layout_text: str | None, image_png: bytes | None) -> QaReport:
    cover = is_cover_page(layout_text)
    checks = [
        check_numeric_recall(result, cover),
        check_price_range(result),
        check_no_dupe_rows(result),
        check_row_count_plausible(result),
        check_not_empty(result, cover),
        check_product_names_sane(result),
    ]
    return QaReport(sha256=result.sha256, page_number=result.page_number, checks=checks)


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    spelled = value.lower().replace("+", " plus ")
    return " ".join(spelled.translate(PUNCTUATION_TABLE).split())


def descriptive_tokens(row: PriceRow) -> set[str]:
    combined = " ".join(part for part in (row.brand, row.product, row.variant) if part)
    return set(normalize_text(combined).split())


def products_match(predicted: PriceRow, golden: PriceRow) -> bool:
    predicted_product = normalize_text(predicted.product)
    golden_product = normalize_text(golden.product)
    if predicted_product == golden_product:
        return True
    golden_core = set(golden_product.split())
    predicted_core = set(predicted_product.split())
    if not golden_core or not predicted_core:
        return False
    return golden_core <= descriptive_tokens(predicted) or predicted_core <= descriptive_tokens(
        golden
    )


def is_cpu_noise_token(token: str) -> bool:
    return token in CPU_BRAND_WORDS or CPU_TIER_TOKEN.fullmatch(token) is not None


def cpu_key(bundle_cpu: str | None) -> str:
    tokens = normalize_text(bundle_cpu).split()
    return " ".join(token for token in tokens if not is_cpu_noise_token(token))


def rows_match(predicted: PriceRow, golden: PriceRow) -> bool:
    if predicted.price_sgd != golden.price_sgd:
        return False
    if cpu_key(predicted.bundle_cpu) != cpu_key(golden.bundle_cpu):
        return False
    return products_match(predicted, golden)


def restrict_to_golden_products(
    predicted: list[PriceRow], golden: list[PriceRow]
) -> list[PriceRow]:
    return [row for row in predicted if any(products_match(row, gold) for gold in golden)]


def count_matches(predicted: list[PriceRow], golden: list[PriceRow]) -> int:
    unmatched = list(predicted)
    matched = 0
    for golden_row in golden:
        for index, predicted_row in enumerate(unmatched):
            if rows_match(predicted_row, golden_row):
                del unmatched[index]
                matched += 1
                break
    return matched


def safe_ratio(numerator: int, denominator: int, empty_value: float) -> float:
    return numerator / denominator if denominator else empty_value


def row_f1(predicted: list[PriceRow], golden: list[PriceRow]) -> tuple[float, float, float]:
    matched = count_matches(predicted, golden)
    both_empty = 1.0 if not predicted and not golden else 0.0
    precision = safe_ratio(matched, len(predicted), both_empty)
    recall = safe_ratio(matched, len(golden), both_empty)
    if precision + recall == 0:
        return precision, recall, 0.0
    return precision, recall, 2 * precision * recall / (precision + recall)


def price_only_recall(predicted: list[PriceRow], golden: list[PriceRow]) -> float:
    if not golden:
        return 1.0
    available = Counter(row.price_sgd for row in predicted)
    found = 0
    for row in golden:
        if available[row.price_sgd] > 0:
            available[row.price_sgd] -= 1
            found += 1
    return found / len(golden)
