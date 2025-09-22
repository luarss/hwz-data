.PHONY: install install-deps sync reqs

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
