import io
import os
import time
from pathlib import Path

import pytest
from openai import OpenAIError

from hwz_ocr.llm.router import Router, RouterExhausted
from hwz_ocr.schema import ExtractionMethod, PageStatus
from hwz_ocr.structure import structure_page

VALID_ROWS_JSON = (
    '{"rows": [{"product": "ASUS TUF B850", "bundle_cpu": "7600X", "price_sgd": 881},'
    ' {"product": "RM750e", "brand": "Corsair", "price_sgd": 149}]}'
)


class FakeRouter:
    def __init__(self, responses: list):
        self.responses = list(responses)
        self.prompts: list[str] = []
        self.vision_flags: list[bool] = []
        self.images: list[bytes | None] = []
        self.preferences: list[list[str] | None] = []

    def complete(self, *, prompt, image_png, needs_vision, preferred=None):
        self.prompts.append(prompt)
        self.vision_flags.append(needs_vision)
        self.images.append(image_png)
        self.preferences.append(preferred)
        outcome = self.responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome, "fake", "fake-model"


def run(router, *, layout_text="TEXT", image_png=None, vendor="bizgram", **options):
    return structure_page(
        vendor=vendor,
        sha256="abc",
        page_number=2,
        layout_text=layout_text,
        image_png=image_png,
        numeric_tokens_in_source=42,
        router=router,
        **options,
    )


def test_plain_json_parses_rows():
    result = run(FakeRouter([VALID_ROWS_JSON]))
    assert result.status == PageStatus.DONE
    assert result.method == ExtractionMethod.TEXT_LAYER_LLM
    assert [row.price_sgd for row in result.rows] == [881, 149]
    assert (result.provider, result.model) == ("fake", "fake-model")
    assert result.numeric_tokens_in_source == 42
    assert result.raw_response == VALID_ROWS_JSON


def test_fenced_json_parses():
    result = run(FakeRouter([f"Here you go:\n```json\n{VALID_ROWS_JSON}\n```\nDone."]))
    assert len(result.rows) == 2


def test_trailing_prose_is_tolerated():
    result = run(FakeRouter([VALID_ROWS_JSON + "\n\nNote: two rows were extracted {sic}."]))
    assert len(result.rows) == 2


def test_invalid_rows_are_dropped():
    response = (
        '{"rows": [{"product": "Good", "price_sgd": 100}, {"product": "", "price_sgd": 5},'
        ' {"product": "NoPrice", "price_sgd": null}, {"product": "TooHigh", "price_sgd": 999999}]}'
    )
    result = run(FakeRouter([response]))
    assert result.status == PageStatus.DONE
    assert [row.product for row in result.rows] == ["Good"]


def test_image_uses_vision_method():
    router = FakeRouter([VALID_ROWS_JSON])
    result = run(router, layout_text=None, image_png=b"png", vendor="pc_themes")
    assert result.method == ExtractionMethod.VISION_LLM
    assert router.vision_flags == [True]


def test_retry_with_strict_suffix_recovers():
    router = FakeRouter(["sorry, I cannot", VALID_ROWS_JSON])
    result = run(router)
    assert result.status == PageStatus.DONE
    assert len(result.rows) == 2
    assert "ONLY the JSON" in router.prompts[1]
    assert "ONLY the JSON" not in router.prompts[0]


def test_second_failure_quarantines():
    result = run(FakeRouter(["not json", "still not json"]))
    assert result.status == PageStatus.QUARANTINED
    assert result.quarantine_reason.startswith("invalid_response")
    assert result.raw_response == "still not json"
    assert result.rows == []


def test_all_rows_invalid_counts_as_failure():
    bad = '{"rows": [{"product": "X", "price_sgd": "abc"}]}'
    result = run(FakeRouter([bad, bad]))
    assert result.status == PageStatus.QUARANTINED


def test_router_exhausted_quarantines():
    result = run(FakeRouter([RouterExhausted("none")]))
    assert result.status == PageStatus.QUARANTINED
    assert result.quarantine_reason == "router_exhausted"


def test_unexpected_router_error_does_not_raise():
    result = run(FakeRouter([OpenAIError("boom")]))
    assert result.status == PageStatus.QUARANTINED


def test_truncated_json_salvages_complete_rows():
    truncated = (
        '{"rows": [{"product": "A", "price_sgd": 10}, {"product": "B", "price_sgd": 20}, {"pro'
    )
    result = run(FakeRouter([truncated]))
    assert result.status == PageStatus.DONE
    assert [row.product for row in result.rows] == ["A", "B"]


def test_decimal_prices_are_kept():
    result = run(FakeRouter(['{"rows": [{"product": "Cable", "price_sgd": 19.9}]}']))
    assert result.rows[0].price_sgd == 19.9


def test_empty_rows_for_numeric_page_retries_then_quarantines():
    router = FakeRouter(['{"rows": []}', '{"rows": []}'])
    result = run(router)
    assert result.status == PageStatus.QUARANTINED
    assert len(router.prompts) == 2


def test_preferred_is_passed_to_router():
    router = FakeRouter([VALID_ROWS_JSON])
    run(router, preferred=["groq"])
    assert router.preferences == [["groq"]]


def test_matrix_page_is_text_only_by_default():
    router = FakeRouter([VALID_ROWS_JSON])
    result = run(router, layout_text="MATRIX TEXT", image_png=b"png", vendor="dynacore")
    assert result.method == ExtractionMethod.TEXT_LAYER_LLM
    assert router.images == [None]
    assert "MATRIX TEXT" in router.prompts[0]
    assert "HIDDEN numbers" in router.prompts[0]


def test_matrix_image_can_be_enabled():
    router = FakeRouter([VALID_ROWS_JSON])
    result = run(router, image_png=b"png", vendor="bizgram", use_image_for_matrix=True)
    assert result.method == ExtractionMethod.VISION_LLM
    assert router.images == [b"png"]
    assert router.vision_flags == [True]


def test_vision_exhaustion_falls_back_to_text():
    router = FakeRouter([RouterExhausted("no vision"), VALID_ROWS_JSON])
    result = run(router, image_png=b"png", vendor="bizgram", use_image_for_matrix=True)
    assert result.status == PageStatus.DONE
    assert result.method == ExtractionMethod.TEXT_LAYER_LLM
    assert router.images == [b"png", None]


BIZGRAM_PDF = Path("downloads/2026-09/bizgram_14UCsN0b-blS0eHSv7kAv_RUgj3eZjd4U.pdf")
PC_THEMES_PDF = Path("downloads/2026-09/pc_themes_1gGXCe_QFiYktp9M-H0dFq7_gJab_1t4j.pdf")


def bizgram_layout_text() -> str:
    import pdfplumber

    with pdfplumber.open(BIZGRAM_PDF) as pdf:
        return pdf.pages[1].extract_text(layout=True)


def pc_themes_png() -> bytes:
    from pdf2image import convert_from_path

    image = convert_from_path(PC_THEMES_PDF, dpi=150, first_page=1, last_page=1)[0]
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def live_provider_names() -> list[str]:
    from dotenv import load_dotenv

    from hwz_ocr.llm.providers import build_providers

    load_dotenv()
    return [provider.name for provider in build_providers()]


@pytest.mark.live
@pytest.mark.skipif(os.environ.get("RUN_LIVE") != "1", reason="set RUN_LIVE=1")
@pytest.mark.parametrize("page_kind", ["bizgram_text", "pc_themes_image"])
@pytest.mark.parametrize("provider_name", ["gemini", "nvidia", "groq", "github"])
def test_live_structure_page(provider_name, page_kind, tmp_path):
    if provider_name not in live_provider_names():
        pytest.skip(f"{provider_name} not configured")
    router = Router.from_env(quota_path=tmp_path / "quota.json")
    router.providers = {provider_name: router.providers[provider_name]}
    if page_kind == "bizgram_text":
        source = {"vendor": "bizgram", "layout_text": bizgram_layout_text(), "image_png": None}
    else:
        source = {"vendor": "pc_themes", "layout_text": None, "image_png": pc_themes_png()}
    started = time.monotonic()
    result = structure_page(
        sha256="live", page_number=1, numeric_tokens_in_source=0, router=router, **source
    )
    elapsed = time.monotonic() - started
    print(
        f"\nLIVE {provider_name} {page_kind}: model={result.model} status={result.status} "
        f"rows={len(result.rows)} seconds={elapsed:.1f} reason={result.quarantine_reason}"
    )
    assert len(result.rows) > 5
