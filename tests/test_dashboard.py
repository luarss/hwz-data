import json
import math

import duckdb
import pytest

from hwz_ocr.dashboard import (
    brand_key,
    build_dashboard,
    classify_component,
    select_movers,
    summarize,
)
from hwz_ocr.output import LATEST_PRICES_VIEW, create_prices_table


@pytest.mark.parametrize(
    ("product", "category", "has_bundle", "expected"),
    [
        ("MSI RTX5070 Shadow 3X OC 12GB GDDR7", None, False, "GPU"),
        ("ASUS PRIME B650M-A WIFI", "AMD Ryzen 7xxx/9xxx Series", False, "Motherboard"),
        ("ASUS PRIME B650M-A WIFI", None, True, "CPU + Board Bundle"),
        ("Intel Core i7-14700KF", None, False, "CPU"),
        ("CORSAIR VENGEANCE RGB DDR5 6000MT/s CL30 Kit", None, False, "Memory"),
        ("Crucial BX500 2TB", None, False, "SSD"),
        ("Seagate Ironwolf Pro", None, False, "HDD"),
        ("SYNOLOGY DS224+ 2 BAY", None, False, "NAS"),
        ("Corsair RMx 850W ATX3.1 Pcie5.1 80+ Gold Full Modular Psu", None, False, "Power Supply"),
        ("ASUS RYUO III 360 ARGB AIO CPU", "CPU Coolers", False, "Cooling"),
        ("TR Peerless Assassin 120 SE Black", "CPU AIR COOLER", False, "Cooling"),
        ("Phanteks G360 Air White Argb TG Atx Casing", "ATX/E-ATX CPU CASINGS", False, "Case"),
        ("Samsung 27\" LS27C330GAE 100Hz 1080P IPS", "MONITORS", False, "Monitor"),
        ("Archer AX10 AX1500 Wi-Fi 6 Router", None, False, "Networking"),
        ("Razer Deathadder Essential Mouse", None, False, "Peripherals"),
        ("Dell Lati 5340|i5-1345U|16GB|512GB SSD|W11 Win 11 Pro", None, False, "Systems & Laptops"),
        ("Apple iPhone 14 Pro Max Silicone Case with MagSafe", None, False, "Other"),
        ("Bizgram ARU4", "Fortune PC", False, "Other"),
    ],
)
def test_classify_component(product, category, has_bundle, expected):
    assert classify_component(product, category, has_bundle) == expected


def test_brand_key_normalizes_case_punctuation_and_aliases():
    assert brand_key("TP-LINK") == brand_key("Tp-Link") == "tplink"
    assert brand_key("CM") == brand_key("Cooler Master") == "coolermaster"
    assert brand_key("WD") == "westerndigital"
    assert brand_key("  ") is None
    assert brand_key(None) is None


def test_summarize_chains_index_from_item_ratios():
    buckets = [
        {"prices": [], "ratios": []},
        {"prices": [100.0] * 5, "ratios": []},
        {"prices": [110.0] * 5, "ratios": [math.log(1.1)] * 5},
        {"prices": [120.0] * 2, "ratios": [math.log(2)] * 2},
    ]
    summary = summarize(buckets)
    assert summary["index"] == [None, 100.0, 110.0, 110.0]
    assert summary["n"] == [0, 5, 5, 2]
    assert summary["up"] == [0, 0, 5, 2]


def test_select_movers_keeps_top_per_group():
    ranked = [
        {"vendor": "a", "component": "GPU", "brand": "X"} for _ in range(30)
    ] + [{"vendor": "b", "component": "SSD", "brand": "Y"}]
    selected = select_movers(ranked)
    assert len(selected) == 16
    assert selected[-1]["component"] == "SSD"


def test_build_dashboard_writes_json(tmp_path):
    rows_dir = tmp_path / "rows"
    rows_dir.mkdir()
    csv_path = rows_dir / "sample.csv"
    header = (
        "sha256,vendor,month,page_number,item,category,brand,product,variant,bundle_cpu,"
        "warranty,price_sgd,method,provider,model"
    )
    lines = [header]
    for month, price in (("2026-01", 500), ("2026-02", 550), ("2026-03", 600)):
        for number in range(6):
            product = f"MSI RTX5070 Card {number}"
            lines.append(
                f"abc,fuwell,{month},1,{product},,MSI,{product},,,,{price + number},text_layer,,"
            )
    csv_path.write_text("\n".join(lines) + "\n")
    rollup_path = tmp_path / "prices.duckdb"
    with duckdb.connect(str(rollup_path)) as connection:
        create_prices_table(connection, [csv_path])
        connection.execute(LATEST_PRICES_VIEW)
    output_dir = tmp_path / "site"
    meta = build_dashboard(rollup_path, output_dir)
    assert meta["months"] == ["2026-01", "2026-02", "2026-03"]
    assert meta["components"] == ["GPU"]
    series = json.loads((output_dir / "series.json").read_text())
    assert series["component:GPU"]["index"][0] == 100.0
    assert series["component:GPU"]["index"][-1] > 115
    assert series["brand:MSI"]["n"] == [6, 6, 6]
    items = json.loads((output_dir / "items.json").read_text())
    assert len(items) == 6
    movers = json.loads((output_dir / "movers.json").read_text())
    assert len(movers["rises"]) == 6
