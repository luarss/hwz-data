from hwz_ocr.schema import MATRIX_VENDORS, SCANNED_VENDORS

STRICT_JSON_SUFFIX = (
    "\n\nYOUR PREVIOUS ANSWER WAS NOT VALID JSON. Return ONLY the JSON object "
    '{"rows": [...]} with no prose, no markdown, no code fences.'
)

BASE_INSTRUCTIONS = """You extract prices from one page of a Singapore computer-shop price list.

Return STRICT JSON only, exactly this shape:
{"rows": [{"category": str|null, "brand": str|null, "product": str, "variant": str|null, \
"bundle_cpu": str|null, "warranty": str|null, "price_sgd": number}]}

Field rules:
- product (required): the product name/model as printed, without the price.
- price_sgd (required): number in SGD, decimals allowed (e.g. 19.9); no currency symbol, no
  thousands separators, never a string.
- category: section heading the row sits under (e.g. "Motherboard", "Power Supply"), else null.
- brand: manufacturer if printed or obvious from the product name, else null.
- variant: capacity/size/colour/edition column or suffix that distinguishes prices of the same \
product (e.g. "16GB", "2TB", "White"), else null.
- bundle_cpu: only for CPU bundle prices, the CPU SKU of the bundle, else null.
- warranty: warranty as printed (e.g. "3Y"), else null.
- Omit nothing else; you may leave out keys whose value is null.

Coverage rules:
- Emit EVERY price visible on the page, one row per price. Do not summarise, do not skip rows.
- When a table has several price columns (capacities, sizes, bundles), emit one row per priced \
cell using the column header as variant or bundle_cpu.
- Cells containing "-", "#N/A", "N/A", "TBA", "call" or blanks are not prices; skip them.
- If a token clearly is a price but you cannot tell its product, still emit it with product \
"UNKNOWN".
- Never invent products or prices that are not on the page.
- Ignore phone numbers, addresses, dates, model numbers and part codes; they are not prices.
"""

MATRIX_RULES = """This vendor publishes a BUNDLE MATRIX:
- Each row is a motherboard. The column headers across the top are CPU SKUs \
(e.g. 7500F, 7600X, 9800X3D, 14400F, 265K).
- Each numeric cell is the price of that motherboard bundled with that column's CPU.
- Emit one row per (motherboard, CPU column) cell: product = motherboard name, \
bundle_cpu = column header CPU SKU, price_sgd = cell value.
- A board-only price exists ONLY when it is printed in brackets next to the name, e.g. "($596)": \
emit it as a separate row with bundle_cpu null. A bare number is never a board-only price. \
Words like "OFFER" between the name and the numbers are not prices. When the count of numbers \
on a line equals the count of CPU headers, every number is a bundle cell, starting with the \
first header.
- Keep the warranty marker like "(3Y)" in warranty, not in product.
- Emit exactly one row per visible CPU column header, in header order. If a product line has \
more numbers than headers, the extra numbers are hidden text: use the RIGHTMOST N numbers, where \
N is the number of headers.
- Rebuild headers split across two lines: "U5 250K" over "PLUS" is the single header "U5 250K PLUS".
- Also emit the row of standalone CPU prices printed under the header row, one row per CPU with \
product = the CPU name and bundle_cpu null.
- Side panels with other products (mini PCs, custom builds) are ordinary rows.
"""

MATRIX_EXAMPLE = """Example input:
  AMD Motherboard and CPU   7500F 7600X 9800X3D
  ASUS TUF GAMING X870-PLUS WIFI (3Y) ($568) 761 881 1453
Example output:
{"rows": [
 {"category": "Motherboard", "brand": "ASUS", "product": "ASUS TUF GAMING X870-PLUS WIFI", \
"warranty": "3Y", "price_sgd": 568},
 {"category": "Motherboard", "brand": "ASUS", "product": "ASUS TUF GAMING X870-PLUS WIFI", \
"bundle_cpu": "7500F", "warranty": "3Y", "price_sgd": 761},
 {"category": "Motherboard", "brand": "ASUS", "product": "ASUS TUF GAMING X870-PLUS WIFI", \
"bundle_cpu": "7600X", "warranty": "3Y", "price_sgd": 881},
 {"category": "Motherboard", "brand": "ASUS", "product": "ASUS TUF GAMING X870-PLUS WIFI", \
"bundle_cpu": "9800X3D", "warranty": "3Y", "price_sgd": 1453}
]}
"""

DYNACORE_GUIDANCE = """Dynacore warning: the text layer contains HIDDEN numbers from product photos that are \
not visible on the page (typically about 6 extra numbers per matrix row). Only emit cells that \
align under a CPU column header. Ignore numeric runs that have no column header above them, and \
never shift values into a neighbouring column to make them fit. When the page image is \
provided, trust the image for which numbers are actually visible.
"""

SCANNED_GUIDANCE = """This page is a SCANNED IMAGE with several side-by-side tables.
- Read every table and every column block on the page, left to right, top to bottom.
- Transcribe every priced line. Do not skip any line, do not stop early, do not invent.
- Brand sub-headings (e.g. "CORSAIR", "ASUS") inside a table are the brand for the rows below.
- Table titles (e.g. "POWER SUPPLY", "CPU COOLER") are the category.
- Capacity-column tables (8GB/16GB/32GB, 1TB/2TB/4TB): one row per priced cell, \
variant = column header.

Example image line:  CORSAIR RM 750E GEN 3.1 PLATINUM POWER SUPPLY [BLACK]   149
Example output:
{"rows": [{"category": "Power Supply", "brand": "CORSAIR", \
"product": "CORSAIR RM 750E GEN 3.1 PLATINUM POWER SUPPLY", "variant": "BLACK", "price_sgd": 149}]}
"""

SIMPLE_GUIDANCE = """This page is a product list: each line is a product followed by its price.
- A product may have several prices for different variants or warranty terms; emit one row each.

Example input:
  PROCESSOR
  AMD Ryzen 7 9800X3D (3Y)            $729
  Samsung 990 PRO 1TB / 2TB           159 / 269
Example output:
{"rows": [
 {"category": "Processor", "brand": "AMD", "product": "AMD Ryzen 7 9800X3D", "warranty": "3Y", \
"price_sgd": 729},
 {"category": null, "brand": "Samsung", "product": "Samsung 990 PRO", "variant": "1TB", \
"price_sgd": 159},
 {"category": null, "brand": "Samsung", "product": "Samsung 990 PRO", "variant": "2TB", \
"price_sgd": 269}
]}
"""


def vendor_guidance(vendor: str) -> str:
    if vendor == "dynacore":
        return f"{MATRIX_RULES}\n{DYNACORE_GUIDANCE}\n{MATRIX_EXAMPLE}"
    if vendor in MATRIX_VENDORS:
        return f"{MATRIX_RULES}\n{MATRIX_EXAMPLE}"
    if vendor in SCANNED_VENDORS:
        return SCANNED_GUIDANCE
    return SIMPLE_GUIDANCE


IMAGE_ONLY_NOTE = "The page is provided as an image. Read it carefully."
IMAGE_AND_TEXT_NOTE = (
    "The page image is attached AND its text layer is given below. Use the image to decide "
    "which numbers are visible and which column each belongs to; use the text to read names and "
    "digits exactly."
)


def source_section(layout_text: str | None, has_image: bool) -> str:
    if layout_text is None:
        return IMAGE_ONLY_NOTE
    text_block = (
        "Page text extracted with layout preserved (columns are aligned by spaces):\n"
        "<<<PAGE\n" + layout_text + "\nPAGE>>>"
    )
    if has_image:
        return IMAGE_AND_TEXT_NOTE + "\n" + text_block
    return text_block


def build_prompt(vendor: str, layout_text: str | None, *, has_image: bool = False) -> str:
    return "\n".join(
        [
            BASE_INSTRUCTIONS,
            f"Vendor: {vendor}",
            vendor_guidance(vendor),
            source_section(layout_text, has_image),
            'Return only the JSON object {"rows": [...]}.',
        ]
    )
