# HardwareZone Price List scraper and extractor

Scrapes the [HardwareZone price lists](https://hardwarezone.com.sg/priceLists/) nightly and extracts structured prices from the downloaded PDFs.

- `scrape.py`: downloads PDFs into `downloads/YYYY-MM/` (production, no login).
- `selenium_automation.py`: earlier login-based approach, kept for reference.
- `hwz_ocr/`: extraction pipeline that turns PDFs into CSV and DuckDB.

## Corpus

- 8 vendors: bizgram, dynacore, fuwell, infinity, laser, pc_themes, techdeals, tradepac.
- Some PDFs carry a usable text layer; others are scanned images and need OCR (tesseract). The layer is detected per page.
- The same PDF is often re-published under different names, months, or vendors. Files are deduplicated by sha256 before processing.

## Architecture

PDF -> intermediate text/structure -> validated rows -> flat prices.

```text
downloads/YYYY-MM/*.pdf
  -> scan: hash files, register new ones in data/manifest.jsonl
  -> extract: layout text via poppler, OCR fallback via tesseract -> data/intermediate/.../p{N}.txt
  -> structure: LLM turns page text into rows (provider fallback, quota in data/quota.json) -> p{N}.llm.json
  -> QA: numeric-token recall, price range, duplicates
       pass -> data/rows/{vendor}/{month}/{sha8}.csv -> data/prices/{vendor}/{month}/{sha8}.csv
       fail -> data/quarantine/
  -> rollup: data/prices.duckdb
```

## Data layout

| Path | Contents |
| --- | --- |
| `downloads/YYYY-MM/` | Raw PDFs from the nightly scrape |
| `data/prices/{vendor}/{month}/{sha8}.csv` | Deliverable: flat `item,price_sgd` pairs |
| `data/rows/{vendor}/{month}/{sha8}.csv` | Rich per-row table with all extracted fields |
| `data/intermediate/{vendor}/{sha8}/p{N}.txt` | Layout text per page |
| `data/intermediate/{vendor}/{sha8}/p{N}.llm.json` | Raw LLM response per page |
| `data/quarantine/` | Pages that failed QA |
| `data/manifest.jsonl` | One record per unique PDF (sha256) with per-page status |
| `data/quota.json` | Provider usage counters |
| `data/prices.duckdb` | Rolled-up price table |
| `data/bakeoff.md` | Provider comparison report |
| `tests/golden/` | Hand-labelled pages for F1 scoring |

## Running locally

```bash
make install-deps
uv sync --group dev
cp .env.sample .env

make scan
make process ARGS="--vendor fuwell --max-pages 10"
make process ARGS="--no-llm"
make rollup
make stats
make bakeoff
make lint
make test
RUN_LIVE=1 uv run pytest -q -m live
```

## Workflows

| Workflow | Trigger | What it does |
| --- | --- | --- |
| `dl.yaml` (Nightly HWZ download) | Daily cron, manual | Runs `scrape.py`, commits new PDFs |
| `ocr.yaml` (OCR price extraction) | After a successful download run, manual | scan, process, rollup, stats, commits `data/**` |
| `ci.yaml` | PRs and pushes to master touching code, tests, deps, workflows | `ruff check`, `pytest` |

`dl.yaml` and `ocr.yaml` share the `hwz-commits` concurrency group so they never push at the same time. Scheduled OCR runs use `--max-pages 60`.

## Providers

| Provider | Credential | Notes |
| --- | --- | --- |
| Google Gemini | `GEMINI_API_KEY` | Primary. Vision model is capped at 20 requests/day on the free tier; flash-lite handles text |
| Groq | `GROQ_API_KEY` | Second choice for scanned pages. 8k tokens/min, so large text pages fail |
| NVIDIA NIM | `NVIDIA_API_KEY` | Text fallback, best on dynacore matrices. Vision disabled, it times out |
| Z.AI (GLM) | `ZAI_API_KEY` | Text fallback and third choice for scans, thinking disabled |
| Ollama Cloud | `OLLAMA_API_KEY` | Optional text fallback, no key seeded yet |

Routing order is set in `hwz_ocr/llm/router.py`: text pages try Gemini, NVIDIA, Z.AI, Groq, Ollama; scanned pages try Gemini, Groq, Z.AI. Bundle-matrix pages (bizgram, dynacore) are sent as text only. Dynacore text has hidden numbers under product photos, which the extractor removes by dropping words inside image boxes. Bake-off scores against `tests/golden/` are in `data/bakeoff.md`.

Locally, put the keys in `.env`. Missing keys disable that provider.

## QA checks

- Numeric-token recall: every price-like number in the source page must appear in the extracted rows.
- Price range: prices outside a plausible range are flagged.
- Duplicates: repeated rows within a page are flagged.
- Golden set F1: `tests/golden/` pages are scored against labelled rows in the test suite.

Pages failing QA go to `data/quarantine/` instead of `data/rows/` and `data/prices/`.

## Backfill

Each run processes at most `max_pages` pages. To work through the full history:

```bash
gh workflow run ocr.yaml -f backfill=true -f max_pages=60
gh workflow run ocr.yaml -f backfill=true -f max_pages=60 -f vendor=tradepac
```

After committing, a backfill run re-dispatches itself with the same inputs until no pages are pending. Cancel the latest run to stop the chain.

### Pending check assumption

The workflow decides whether to continue by grepping the output of `python -m hwz_ocr stats` for a line that is exactly `total_pending=0`.
