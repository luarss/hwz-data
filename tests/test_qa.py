import pytest

from hwz_ocr.qa import (
    check_page,
    count_numeric_tokens,
    is_cover_page,
    price_only_recall,
    restrict_to_golden_products,
    row_f1,
)
from hwz_ocr.schema import ExtractionMethod, PageResult, PriceRow


def make_row(product: str, price: float, bundle_cpu: str | None = None, **extra) -> PriceRow:
    return PriceRow(product=product, price_sgd=price, bundle_cpu=bundle_cpu, **extra)


def make_result(rows: list[PriceRow], numeric_tokens: int) -> PageResult:
    return PageResult(
        sha256="abc",
        vendor="laser",
        page_number=2,
        method=ExtractionMethod.TEXT_LAYER,
        rows=rows,
        numeric_tokens_in_source=numeric_tokens,
    )


def check_named(report, name: str):
    return next(check for check in report.checks if check.name == name)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("$1,286", 1),
        ("S$ 908", 1),
        ("S$1,629", 1),
        ("ASUS PRIME B860M-K CSM 259", 1),
        ("BLACK $ 1 20.00", 1),
        ("240 $ 6 8.00", 2),
        ("$ 20.90", 1),
        ("X870E Z890 9800X3D", 0),
        ("DDR5-6000", 0),
        ("U5 245K U7 265KF", 0),
        ("Last Update 28 August 2026 10:46 AM", 0),
        ("Last Update 28 A u g u s t 2026", 0),
        ("Updated 19-Sep-26", 0),
        ("Date: 19/09/2026", 0),
        ("Tel : 6339 3901", 0),
        ("+65 8115 0505", 0),
        ("Whatsapp us @98168725", 0),
        ("Singapore 188504", 0),
        ("#04-69 Sim Lim Square", 0),
        ("50% discount", 0),
        ("Page 1 of 3", 0),
        ("30 Days 1 : 1 Exchange", 0),
        ("3 Years warranty", 0),
        ('16GB 650W 27" 144Hz', 0),
        ("2 x USB 3.2", 0),
        ("RTX 5060 TI 8GB 949", 1),
        ('AOC 24B36H 23.8" 117', 1),
        ("Asus Dual RTX5060 OC 8GB (White=$779) 729", 2),
        ("price 25000", 0),
        ("price 0", 0),
    ],
)
def test_count_numeric_tokens(text, expected):
    assert count_numeric_tokens(text) == expected


def test_count_numeric_tokens_counts_matrix_rows():
    line = "Gigabyte Z890 EAGLE WIFI 7 ($390) 707 814 811 1206 631 771 892"
    assert count_numeric_tokens(line) == 8


def test_cover_page_detection():
    cover_text = "Terms & Conditions\nOpening Hours: Mon-Sun 11am - 8pm\nAddress: Sim Lim Square"
    assert is_cover_page(cover_text)
    assert not is_cover_page("Warranty 3 years\n" + " ".join(str(n) for n in range(100, 120)))
    assert not is_cover_page("Graphics cards only")
    assert not is_cover_page(None)


def test_check_page_passes_good_page():
    rows = [make_row(f"Product {index}", 100 + index) for index in range(9)]
    report = check_page(make_result(rows, 10), "irrelevant", None)
    assert report.passed, report.checks


def test_check_page_fails_low_numeric_recall():
    rows = [make_row(f"Product {index}", 100 + index) for index in range(5)]
    report = check_page(make_result(rows, 10), "text", None)
    assert not check_named(report, "numeric_recall").passed
    assert not report.passed


def test_check_page_numeric_recall_threshold_is_sixty_percent():
    rows = [make_row(f"Product {index}", 100 + index) for index in range(6)]
    report = check_page(make_result(rows, 10), "text", None)
    assert check_named(report, "numeric_recall").passed


def test_check_page_fails_many_duplicates():
    rows = [make_row("Product A", 100), make_row("Product A", 100), make_row("Product B", 100)]
    report = check_page(make_result(rows, 3), "text", None)
    assert not check_named(report, "no_dupe_rows").passed
    assert check_named(report, "numeric_recall").passed


def test_check_page_tolerates_few_source_duplicates():
    rows = [make_row(f"Product {index}", 100 + index) for index in range(10)]
    rows.append(make_row("Product 0", 100))
    report = check_page(make_result(rows, 11), "text", None)
    assert check_named(report, "no_dupe_rows").passed


def test_check_page_fails_implausible_row_count():
    rows = [make_row(f"Product {index}", 100 + index) for index in range(26)]
    report = check_page(make_result(rows, 10), "text", None)
    assert not check_named(report, "row_count_plausible").passed


def test_check_page_row_count_plausible_at_limit_and_without_tokens():
    rows = [make_row(f"Product {index}", 100 + index) for index in range(25)]
    assert check_named(check_page(make_result(rows, 10), "t", None), "row_count_plausible").passed
    assert check_named(check_page(make_result(rows, 0), None, b"png"), "row_count_plausible").passed


def test_decimal_prices_supported_in_metrics():
    golden = [make_row("Cooler Master MP 511 SF6", 19.9), make_row("SanDisk Ultra 32GB", 20.90)]
    predicted = [make_row("cooler master mp511 sf6", 19.90), make_row("SanDisk Ultra 32GB", 20.9)]
    assert row_f1(predicted, golden)[1] == 0.5
    assert price_only_recall(predicted, golden) == 1.0


def test_check_page_same_price_different_cpu_is_not_duplicate():
    rows = [make_row("Board", 500, "U5 245K"), make_row("Board", 500, "U7 265K")]
    report = check_page(make_result(rows, 2), "text", None)
    assert check_named(report, "no_dupe_rows").passed


def test_check_page_fails_insane_product_names():
    rows = [make_row("UNKNOWN", 100), make_row("ab", 120)] + [
        make_row(f"Good product {index}", 150 + index) for index in range(3)
    ]
    report = check_page(make_result(rows, 5), "text", None)
    assert not check_named(report, "product_names_sane").passed


def test_check_page_empty_content_page_fails():
    report = check_page(make_result([], 40), "lots of 100 200 300 prices", None)
    assert not check_named(report, "not_empty").passed
    assert not check_named(report, "numeric_recall").passed


def test_check_page_empty_cover_page_passes():
    cover_text = "Terms: All prices are nett. Opening Hours 11am. Address: 1 Rochor Canal Road"
    report = check_page(make_result([], 0), cover_text, None)
    assert report.passed, report.checks


def test_check_page_empty_scanned_page_fails_not_empty():
    report = check_page(make_result([], 0), None, b"png")
    assert check_named(report, "numeric_recall").passed
    assert not check_named(report, "not_empty").passed


def test_row_f1_exact_match():
    golden = [make_row("ASUS TUF B860M", 399), make_row("MSI PRO Z890-P", 459)]
    assert row_f1(list(golden), golden) == (1.0, 1.0, 1.0)


def test_row_f1_normalizes_case_punctuation_and_whitespace():
    golden = [make_row("ASUS TUF-Gaming  B860M", 399)]
    predicted = [make_row("asus tuf gaming b860m", 399)]
    assert row_f1(predicted, golden) == (1.0, 1.0, 1.0)


def test_row_f1_accepts_brand_or_variant_split_differently():
    golden = [make_row("FREEZER III PRO 240", 120, brand="Arctic", variant="BLACK")]
    predicted = [make_row("Arctic Freezer III Pro 240 Black", 120)]
    assert row_f1(predicted, golden)[2] == 1.0


def test_row_f1_requires_matching_bundle_cpu_and_price():
    golden = [make_row("Board", 500, "U5 245K"), make_row("Board", 600, "U7 265K")]
    predicted = [make_row("Board", 500, "U7 265K"), make_row("Board", 600, "U7 265K")]
    precision, recall, f1 = row_f1(predicted, golden)
    assert precision == 0.5
    assert recall == 0.5
    assert f1 == pytest.approx(0.5)


def test_row_f1_bundle_cpu_plus_spelling():
    golden = [make_row("Board", 500, "U7 270K PLUS")]
    predicted = [make_row("Board", 500, "U7 270K+")]
    assert row_f1(predicted, golden)[2] == 1.0


def test_row_f1_counts_each_prediction_once():
    golden = [make_row("Board", 500), make_row("Board", 500, variant="WHITE")]
    predicted = [make_row("Board", 500)]
    precision, recall, _ = row_f1(predicted, golden)
    assert precision == 1.0
    assert recall == 0.5


def test_row_f1_empty_inputs():
    assert row_f1([], []) == (1.0, 1.0, 1.0)
    assert row_f1([], [make_row("Board", 500)]) == (0.0, 0.0, 0.0)
    assert row_f1([make_row("Board", 500)], []) == (0.0, 0.0, 0.0)


def test_price_only_recall_uses_multiset():
    golden = [make_row("A", 100), make_row("B", 100), make_row("C", 200)]
    predicted = [make_row("X", 100), make_row("Y", 200), make_row("Z", 300)]
    assert price_only_recall(predicted, golden) == pytest.approx(2 / 3)
    assert price_only_recall([], []) == 1.0


@pytest.mark.parametrize(
    ("predicted_cpu", "golden_cpu"),
    [
        ("Intel Core Ultra 5 225F", "U5 225F"),
        ("U7 270K+", "U7 270K PLUS"),
        ("i5-14400F", "Intel Core i5 14400F"),
        ("AMD Ryzen 7 9800X3D", "9800X3D"),
        ("Ryzen 5 5500", "5500"),
    ],
)
def test_row_f1_matches_bundle_cpu_on_sku(predicted_cpu, golden_cpu):
    golden = [make_row("Board", 500, golden_cpu)]
    predicted = [make_row("Board", 500, predicted_cpu)]
    assert row_f1(predicted, golden)[2] == 1.0


@pytest.mark.parametrize(
    ("predicted_cpu", "golden_cpu"),
    [("U5 225F", "U5 225"), ("U7 270K", "U7 270K PLUS"), ("9800X3D", None)],
)
def test_row_f1_rejects_different_cpu_sku(predicted_cpu, golden_cpu):
    golden = [make_row("Board", 500, golden_cpu)]
    predicted = [make_row("Board", 500, predicted_cpu)]
    assert row_f1(predicted, golden)[2] == 0.0


def test_restrict_to_golden_products_drops_unlabelled_products():
    golden = [make_row("Gigabyte Z890 AORUS MASTER", 1035, "U5 245K")]
    predicted = [
        make_row("Gigabyte Z890 AORUS MASTER", 1142, "U7 265K"),
        make_row("MSI MAG B860 TOMAHAWK", 700, "U5 245K"),
    ]
    restricted = restrict_to_golden_products(predicted, golden)
    assert [row.product for row in restricted] == ["Gigabyte Z890 AORUS MASTER"]
