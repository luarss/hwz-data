import argparse
import json
import math
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

import duckdb

from hwz_ocr.schema import ROLLUP_PATH

SITE_DATA_DIR = Path("site/data")
MAX_LOG_RATIO = math.log(2)
MIN_PAIRS_FOR_INDEX = 5
TOP_BRAND_COUNT = 40
MOVER_COUNT = 15
MOVER_MIN_PRICE = 30
ITEM_MIN_OBSERVATIONS = 3

COMPONENT_ORDER = (
    "GPU",
    "CPU",
    "Motherboard",
    "CPU + Board Bundle",
    "Systems & Laptops",
    "Memory",
    "SSD",
    "HDD",
    "NAS",
    "Power Supply",
    "Cooling",
    "Case",
    "Monitor",
    "Networking",
    "Peripherals",
    "Other",
)

CHIPSETS = (
    "a320 a520 a620 b350 b450 b550 b650 b650e b660 b760 b840 b850 b860 h510 h610 h670 h770 "
    "h810 x370 x470 x570 x670 x670e x870 x870e z590 z690 z790 z890 w680 w790 trx50 x299"
)

COMPONENT_PATTERNS = (
    ("Other", r"iphone|ipad|airpods|airtag|\bwatch\b|kettle|toothbrush|printer"),
    (
        "Systems & Laptops",
        r"laptop|notebook(?! (cooler|ram|memory))|thinkpad|thinkbook|elitebook|zbook|latitude"
        r"|\blati\b|surface (pro|laptop)|macbook|\bnuc\b|mini pc|\bmini pn|\bpn\d{2}"
        r"|\+ ?(rtx|rx) ?\d|\|i[3579]-|elite (mini|tower|desk)|optiplex|\bopti \d|\d+gb ?/ ?\d+",
    ),
    ("Motherboard", rf"\b({CHIPSETS.replace(' ', '|')})[a-z]?\b|mother ?board|mainboard"),
    ("Cooling", r"\baio\b(?! printer)|liquid cool|ryujin|ryuo|cpu cooler"),
    (
        "CPU",
        r"\bryzen [3579]\b|\bryzen threadripper|core i[3579]\b|core ultra|\bi[3579]-\d{4,5}"
        r"|celeron|pentium|\bxeon\b|processor|\bi[3579] \d{4,5}[a-z]*\b",
    ),
    (
        "GPU",
        r"\b(rtx|gtx) ?a?\d{3,4}|\brx ?\d{3,4}|radeon|geforce|\bquadro\b|\barc [ab]\d{3}"
        r"|\bgv[- ]?n\d|graphics? card|\bgt ?\d{3,4}\b",
    ),
    ("Memory", r"\bddr[345]\b|\bpc[345]-?\d{4}|\bmemory\b|\bram\b|\budimm|\bso-?dimm"),
    (
        "SSD",
        r"\bssd\b|\bnvme\b|\bm\.2\b|\bsn\d{3}\b|\b9[789]0 (evo|pro)\b|\b(mx|bx)500\b|\bt[79]\b"
        r"|\b8[67]0 evo\b|exceria|\bp[35][1-9]0\b",
    ),
    (
        "HDD",
        r"\bhdd\b|hard (disk|drive)|ironwolf|barracuda|b/cuda|skyhawk|\bexos\b|ultrastar"
        r"|\bwd (red|purple|gold)\b|\d{4} ?rpm",
    ),
    ("NAS", r"synology|\bqnap\b|asustor|\bnas\b|diskstation|\d-bays?\b"),
    (
        "Power Supply",
        r"\bpsu\b|(?<!uninterruptible )power supply|80 ?\+|\b\d{3,4} ?w\b.*\b(gold|bronze"
        r"|platinum|titanium|atx ?3)",
    ),
    (
        "Peripherals",
        r"mouse|keyboard|headset|headphone|webcam|speaker|controller|gamepad|\bkb\b|keycap"
        r"|soundbar",
    ),
    (
        "Cooling",
        r"thermalright|id-? ?cooling|cooler|heatsink|thermal (paste|compound)|\bfans?\b"
        r"|radiator",
    ),
    ("Case", r"casing|chassis|\bcase\b|tower|\bm-?atx\b"),
    ("Monitor", r"monitor|\b\d{2}(\.\d)? ?(\"|”|''|inch)|\b\d{2,3} ?hz\b"),
    (
        "Networking",
        r"router|\bswitch\b|wi-?fi|access ?point|\bmesh\b|ethernet|\blan\b|ubiquiti|unifi"
        r"|\bdeco\b|archer|cisco|netgear|aruba|\bpoe\b|ip-? ?cam|wireless|network adapter"
        r"|\btl-[a-z]|\bdgs-|\beap\d|\bport\b|\bnms\b",
    ),
)

CATEGORY_PRIORITY = ("Cooling", "Case", "Power Supply", "Peripherals")

COMPILED_PATTERNS = tuple((name, re.compile(pattern)) for name, pattern in COMPONENT_PATTERNS)
CATEGORY_PATTERNS = tuple(
    sorted(COMPILED_PATTERNS, key=lambda entry: entry[0] not in CATEGORY_PRIORITY)
)

BRAND_ALIASES = {
    "cm": "coolermaster",
    "wd": "westerndigital",
    "wdc": "westerndigital",
    "teamgroup": "team",
    "be quiet": "bequiet",
}

BRAND_DISPLAY = {
    "asus": "ASUS",
    "gigabyte": "Gigabyte",
    "msi": "MSI",
    "tplink": "TP-Link",
    "coolermaster": "Cooler Master",
    "dlink": "D-Link",
    "asrock": "ASRock",
    "westerndigital": "Western Digital",
    "gskill": "G.Skill",
    "lianli": "Lian Li",
    "nzxt": "NZXT",
    "amd": "AMD",
    "aoc": "AOC",
    "hp": "HP",
    "lg": "LG",
    "benq": "BenQ",
    "j5create": "j5create",
    "bequiet": "be quiet!",
    "idcooling": "ID-Cooling",
    "adata": "ADATA",
    "qnap": "QNAP",
    "kioxia": "KIOXIA",
    "klevv": "KLEVV",
    "ugreen": "UGREEN",
}


def classify_text(text: str | None, patterns=COMPILED_PATTERNS) -> str | None:
    if not text:
        return None
    lowered = text.lower()
    for name, pattern in patterns:
        if pattern.search(lowered):
            return name
    return None


def classify_component(product: str | None, category: str | None, has_bundle_cpu: bool) -> str:
    if has_bundle_cpu:
        return "CPU + Board Bundle"
    return classify_text(product) or classify_text(category, CATEGORY_PATTERNS) or "Other"


def brand_key(brand: str | None) -> str | None:
    if not brand:
        return None
    key = re.sub(r"[^a-z0-9]", "", brand.lower())
    if not key:
        return None
    return BRAND_ALIASES.get(key, key)


def item_key(item: str) -> str:
    return " ".join(item.lower().split())


def month_ordinal(month: str) -> int:
    year, month_number = month.split("-")
    return int(year) * 12 + int(month_number)


def load_observations(connection: duckdb.DuckDBPyConnection) -> list[dict]:
    rows = connection.execute(
        """
        SELECT vendor, month, item, product, category, brand, bundle_cpu IS NOT NULL, price_sgd
        FROM prices
        WHERE price_sgd IS NOT NULL AND item IS NOT NULL
        """
    ).fetchall()
    brand_counts = Counter(brand_key(row[5]) for row in rows if row[5])
    known_brands = {
        key for key, count in brand_counts.items() if key and count >= 50 and len(key) >= 2
    }
    display_votes: dict[str, Counter] = defaultdict(Counter)
    grouped: dict[tuple, dict] = {}
    for vendor, month, item, product, category, brand, has_bundle, price in rows:
        key = brand_key(brand) or infer_brand(product, known_brands)
        if brand and key:
            display_votes[key][brand.strip()] += 1
        group_key = (vendor, month, item_key(item))
        entry = grouped.setdefault(
            group_key,
            {"item": item, "prices": [], "components": Counter(), "brands": Counter()},
        )
        entry["prices"].append(price)
        entry["components"][classify_component(product, category, has_bundle)] += 1
        if key:
            entry["brands"][key] += 1
    observations = []
    for (vendor, month, key), entry in grouped.items():
        observations.append(
            {
                "vendor": vendor,
                "month": month,
                "key": key,
                "item": entry["item"],
                "price": median(entry["prices"]),
                "component": entry["components"].most_common(1)[0][0],
                "brand": entry["brands"].most_common(1)[0][0] if entry["brands"] else None,
            }
        )
    brand_names = {key: display_name(key, votes) for key, votes in display_votes.items()}
    for observation in observations:
        if observation["brand"]:
            observation["brand"] = brand_names.get(observation["brand"], observation["brand"])
    return observations


def infer_brand(product: str | None, known_brands: set[str]) -> str | None:
    if not product:
        return None
    words = product.split()
    for length in (2, 1):
        candidate = brand_key(" ".join(words[:length]))
        if candidate in known_brands:
            return candidate
    return None


def display_name(key: str, votes: Counter) -> str:
    if key in BRAND_DISPLAY:
        return BRAND_DISPLAY[key]
    mixed_case = [name for name, _ in votes.most_common() if not name.isupper()]
    return mixed_case[0] if mixed_case else votes.most_common(1)[0][0]


def median(values: list[float]) -> float:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def attach_price_changes(observations: list[dict]) -> None:
    vendor_months: dict[str, list[str]] = defaultdict(list)
    for month_list_vendor, month in {(o["vendor"], o["month"]) for o in observations}:
        vendor_months[month_list_vendor].append(month)
    previous_month = {}
    for vendor, months in vendor_months.items():
        ordered = sorted(months)
        for earlier, later in zip(ordered, ordered[1:]):
            previous_month[(vendor, later)] = earlier
    by_key = {(o["vendor"], o["month"], o["key"]): o for o in observations}
    for observation in observations:
        earlier = previous_month.get((observation["vendor"], observation["month"]))
        previous = by_key.get((observation["vendor"], earlier, observation["key"]))
        observation["log_ratio"] = None
        observation["previous_price"] = None
        if not previous:
            continue
        log_ratio = math.log(observation["price"] / previous["price"])
        if abs(log_ratio) <= MAX_LOG_RATIO:
            observation["log_ratio"] = log_ratio
            observation["previous_price"] = previous["price"]


def dimension_keys(observation: dict, top_brands: set[str]) -> list[str]:
    vendor = observation["vendor"]
    component = observation["component"]
    brand = observation["brand"]
    keys = ["all", f"vendor:{vendor}", f"component:{component}", f"vendor:{vendor}|{component}"]
    if brand in top_brands:
        keys += [f"brand:{brand}", f"brand:{brand}|{component}"]
    return keys


def build_series(observations: list[dict], months: list[str], top_brands: set[str]) -> dict:
    month_index = {month: position for position, month in enumerate(months)}
    buckets: dict[str, list[dict]] = defaultdict(lambda: [new_bucket() for _ in months])
    for observation in observations:
        position = month_index[observation["month"]]
        for key in dimension_keys(observation, top_brands):
            bucket = buckets[key][position]
            bucket["prices"].append(observation["price"])
            if observation["log_ratio"] is not None:
                bucket["ratios"].append(observation["log_ratio"])
    return {key: summarize(month_buckets) for key, month_buckets in buckets.items()}


def new_bucket() -> dict:
    return {"prices": [], "ratios": []}


def summarize(month_buckets: list[dict]) -> dict:
    counts, medians, index, ups, downs = [], [], [], [], []
    level = None
    for bucket in month_buckets:
        prices, ratios = bucket["prices"], bucket["ratios"]
        counts.append(len(prices))
        medians.append(round(median(prices), 2) if prices else None)
        ups.append(sum(1 for ratio in ratios if ratio > 0.005))
        downs.append(sum(1 for ratio in ratios if ratio < -0.005))
        if prices and level is None:
            level = 100.0
        elif level is not None and len(ratios) >= MIN_PAIRS_FOR_INDEX:
            level *= math.exp(sum(ratios) / len(ratios))
        index.append(round(level, 2) if level is not None and prices else None)
    return {"n": counts, "median": medians, "index": index, "up": ups, "down": downs}


def build_movers(observations: list[dict]) -> dict:
    latest_month = defaultdict(str)
    for observation in observations:
        vendor = observation["vendor"]
        latest_month[vendor] = max(latest_month[vendor], observation["month"])
    candidates = [
        o
        for o in observations
        if o["month"] == latest_month[o["vendor"]]
        and o["log_ratio"] is not None
        and abs(o["log_ratio"]) > 0.005
        and o["price"] >= MOVER_MIN_PRICE
    ]
    candidates.sort(key=lambda o: o["log_ratio"])
    return {
        "drops": [mover_row(o) for o in select_movers(candidates)],
        "rises": [mover_row(o) for o in select_movers(list(reversed(candidates)))],
    }


def select_movers(ranked: list[dict]) -> list[dict]:
    selected_ids = set()
    group_counts: Counter = Counter()
    for position, observation in enumerate(ranked):
        groups = (
            "all",
            f"vendor:{observation['vendor']}",
            f"component:{observation['component']}",
            f"brand:{observation['brand']}",
        )
        if any(group_counts[group] < MOVER_COUNT for group in groups):
            selected_ids.add(position)
        for group in groups:
            group_counts[group] += 1
    return [ranked[position] for position in sorted(selected_ids)]


def mover_row(observation: dict) -> dict:
    return {
        "item": observation["item"],
        "vendor": observation["vendor"],
        "component": observation["component"],
        "brand": observation["brand"],
        "month": observation["month"],
        "price": observation["price"],
        "previous": observation["previous_price"],
    }


def build_items(observations: list[dict], months: list[str], lookups: dict) -> list[list]:
    month_index = {month: position for position, month in enumerate(months)}
    histories: dict[tuple, list[dict]] = defaultdict(list)
    for observation in observations:
        histories[(observation["vendor"], observation["key"])].append(observation)
    items = []
    for (vendor, _), history in histories.items():
        if len(history) < ITEM_MIN_OBSERVATIONS:
            continue
        history.sort(key=lambda o: o["month"])
        latest = history[-1]
        brand = latest["brand"]
        points = [[month_index[o["month"]], o["price"]] for o in history]
        items.append(
            [
                latest["item"],
                lookups["vendors"].index(vendor),
                lookups["components"].index(latest["component"]),
                lookups["brands"].index(brand) if brand in lookups["brands"] else -1,
                points,
            ]
        )
    items.sort(key=lambda row: (-len(row[4]), row[0]))
    return items


def write_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, separators=(",", ":"), ensure_ascii=False))


def build_dashboard(rollup_path: Path = ROLLUP_PATH, output_dir: Path = SITE_DATA_DIR) -> dict:
    with duckdb.connect(str(rollup_path), read_only=True) as connection:
        observations = load_observations(connection)
    attach_price_changes(observations)
    months = sorted({o["month"] for o in observations})
    vendors = sorted({o["vendor"] for o in observations})
    present_components = {o["component"] for o in observations}
    components = [name for name in COMPONENT_ORDER if name in present_components]
    brand_item_counts = Counter(o["brand"] for o in observations if o["brand"])
    brands = [name for name, _ in brand_item_counts.most_common(TOP_BRAND_COUNT)]
    lookups = {"vendors": vendors, "components": components, "brands": sorted(brands)}
    series = build_series(observations, months, set(brands))
    items = build_items(observations, months, lookups)
    meta = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "months": months,
        "vendors": vendors,
        "components": components,
        "brands": lookups["brands"],
        "vendor_latest_month": {
            vendor: max(o["month"] for o in observations if o["vendor"] == vendor)
            for vendor in vendors
        },
        "totals": {
            "observations": len(observations),
            "items": len({o["key"] for o in observations}),
            "tracked_items": len(items),
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    write_json(output_dir / "meta.json", meta)
    write_json(output_dir / "series.json", series)
    write_json(output_dir / "movers.json", build_movers(observations))
    write_json(output_dir / "items.json", items)
    return meta


def main() -> int:
    parser = argparse.ArgumentParser(description="Build dashboard JSON from the price rollup")
    parser.add_argument("--rollup", type=Path, default=ROLLUP_PATH)
    parser.add_argument("--out", type=Path, default=SITE_DATA_DIR)
    arguments = parser.parse_args()
    meta = build_dashboard(arguments.rollup, arguments.out)
    print(f"months={len(meta['months'])} vendors={len(meta['vendors'])} {meta['totals']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
