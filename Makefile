.PHONY: install install-deps sync reqs test lint scan process rollup stats bakeoff

install: install-deps sync

install-deps:
	@echo "Installing system dependencies"
	@sudo apt-get update
	@sudo apt-get install -y \
		tesseract-ocr \
		tesseract-ocr-eng \
		poppler-utils \
		ghostscript

sync:
	@echo "Syncing Python dependencies"
	@uv sync

reqs:
	@echo "Generating locked requirements"
	@uv pip compile pyproject.toml -o requirements.txt
	@uv lock

test:
	@uv run pytest -q

lint:
	@uv run ruff check .

scan:
	@uv run python -m hwz_ocr scan

process:
	@uv run python -m hwz_ocr process $(ARGS)

rollup:
	@uv run python -m hwz_ocr rollup

stats:
	@uv run python -m hwz_ocr stats

bakeoff:
	@uv run python -m hwz_ocr.bakeoff
