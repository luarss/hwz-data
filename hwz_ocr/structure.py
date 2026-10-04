import json
import logging
import re
from dataclasses import dataclass, field

from openai import OpenAIError
from pydantic import ValidationError

from hwz_ocr.llm.prompts import STRICT_JSON_SUFFIX, build_prompt
from hwz_ocr.llm.router import Router, RouterExhausted
from hwz_ocr.schema import (
    MATRIX_VENDORS,
    ExtractionMethod,
    PageResult,
    PageStatus,
    PriceRow,
)

logger = logging.getLogger(__name__)

CODE_FENCE_PATTERN = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)
FLAT_OBJECT_PATTERN = re.compile(r"\{[^{}\[\]]*\}")

_default_router: Router | None = None


class ResponseFormatError(ValueError):
    pass


@dataclass
class ParsedRows:
    rows: list[PriceRow] = field(default_factory=list)
    invalid_count: int = 0


def default_router() -> Router:
    global _default_router
    if _default_router is None:
        _default_router = Router.from_env()
    return _default_router


def strip_code_fences(text: str) -> str:
    match = CODE_FENCE_PATTERN.search(text)
    return match.group(1) if match else text


def decode_first_json_value(text: str) -> object:
    starts = [index for index in (text.find("{"), text.find("[")) if index >= 0]
    if not starts:
        raise ResponseFormatError("no JSON value found")
    try:
        value, _ = json.JSONDecoder().raw_decode(text, min(starts))
    except json.JSONDecodeError as error:
        raise ResponseFormatError(f"malformed JSON: {error.msg}") from error
    return value


def salvage_row_objects(text: str) -> list[dict]:
    salvaged = []
    for match in FLAT_OBJECT_PATTERN.finditer(text):
        try:
            candidate = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict) and "price_sgd" in candidate:
            salvaged.append(candidate)
    return salvaged


def extract_raw_rows(response_text: str) -> list:
    body = strip_code_fences(response_text)
    try:
        payload = decode_first_json_value(body)
    except ResponseFormatError:
        salvaged = salvage_row_objects(body)
        if salvaged:
            return salvaged
        raise
    if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
        return payload["rows"]
    if isinstance(payload, list):
        return payload
    raise ResponseFormatError("JSON does not contain a rows list")


def validate_rows(raw_rows: list) -> ParsedRows:
    parsed = ParsedRows()
    for raw_row in raw_rows:
        try:
            parsed.rows.append(PriceRow.model_validate(raw_row))
        except ValidationError:
            parsed.invalid_count += 1
    return parsed


def parse_response(response_text: str, numeric_tokens_in_source: int) -> ParsedRows:
    raw_rows = extract_raw_rows(response_text)
    parsed = validate_rows(raw_rows)
    if raw_rows and not parsed.rows:
        raise ResponseFormatError(f"all {parsed.invalid_count} rows failed validation")
    if not parsed.rows and numeric_tokens_in_source > 0:
        raise ResponseFormatError("no rows returned for a page with numbers")
    return parsed


def choose_image(
    vendor: str, layout_text: str | None, image_png: bytes | None, use_image_for_matrix: bool
) -> bytes | None:
    if vendor in MATRIX_VENDORS and layout_text is not None and not use_image_for_matrix:
        return None
    return image_png


def choose_method(image_png: bytes | None) -> ExtractionMethod:
    if image_png is not None:
        return ExtractionMethod.VISION_LLM
    return ExtractionMethod.TEXT_LAYER_LLM


@dataclass(frozen=True)
class PageRequest:
    vendor: str
    sha256: str
    page_number: int
    layout_text: str | None
    numeric_tokens_in_source: int
    preferred: list[str] | None


def structure_page(
    *,
    vendor: str,
    sha256: str,
    page_number: int,
    layout_text: str | None,
    image_png: bytes | None,
    numeric_tokens_in_source: int,
    router: Router | None = None,
    preferred: list[str] | None = None,
    use_image_for_matrix: bool = False,
) -> PageResult:
    active_router = router or default_router()
    request = PageRequest(
        vendor, sha256, page_number, layout_text, numeric_tokens_in_source, preferred
    )
    image_png = choose_image(vendor, layout_text, image_png, use_image_for_matrix)
    result = run_attempts(active_router, request, image_png)
    can_fall_back_to_text = image_png is not None and layout_text is not None
    if result.quarantine_reason == "router_exhausted" and can_fall_back_to_text:
        result = run_attempts(active_router, request, None)
    return result


def run_attempts(router: Router, request: PageRequest, image_png: bytes | None) -> PageResult:
    method = choose_method(image_png)
    result = PageResult(
        sha256=request.sha256,
        vendor=request.vendor,
        page_number=request.page_number,
        method=method,
        numeric_tokens_in_source=request.numeric_tokens_in_source,
    )
    prompt = build_prompt(request.vendor, request.layout_text, has_image=image_png is not None)
    failure_reason = "no_attempt"
    for attempt_prompt in (prompt, prompt + STRICT_JSON_SUFFIX):
        try:
            response_text, provider_name, model = router.complete(
                prompt=attempt_prompt,
                image_png=image_png,
                needs_vision=method == ExtractionMethod.VISION_LLM,
                preferred=request.preferred,
            )
        except RouterExhausted:
            return quarantine(result, "router_exhausted")
        except OpenAIError as error:
            return quarantine(result, f"router_error: {error}")
        result.provider, result.model, result.raw_response = provider_name, model, response_text
        try:
            parsed = parse_response(response_text, request.numeric_tokens_in_source)
        except ResponseFormatError as error:
            failure_reason = f"invalid_response: {error}"
            continue
        log_dropped_rows(result, parsed.invalid_count)
        result.rows = parsed.rows
        return result
    return quarantine(result, failure_reason)


def log_dropped_rows(result: PageResult, invalid_count: int) -> None:
    if invalid_count:
        logger.warning(
            "%s page %d: dropped %d invalid rows", result.sha256, result.page_number, invalid_count
        )


def quarantine(result: PageResult, reason: str) -> PageResult:
    result.status = PageStatus.QUARANTINED
    result.quarantine_reason = reason
    return result
