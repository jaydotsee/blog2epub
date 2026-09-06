PYTHON ?= python3
VENV   ?= .venv
BIN    := $(VENV)/bin

.PHONY: setup test lint format typecheck check list detect sync build run status epubcheck cover clean

setup: $(VENV)/.ok
$(VENV)/.ok: pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -q -e ".[dev,svg]"
	touch $@

test: setup
	$(BIN)/pytest -q

lint: setup
	$(BIN)/ruff check src tests
	$(BIN)/ruff format --check src tests

format: setup
	$(BIN)/ruff check --fix src tests
	$(BIN)/ruff format src tests

typecheck: setup
	$(BIN)/mypy src

check: lint typecheck test

list: setup
	$(BIN)/blog2epub list

# make detect URL=https://example.com/blog
detect: setup
	$(BIN)/blog2epub detect $(URL)

# IDS="tyk api-management" make sync   (defaults to everything)
sync: setup
	$(BIN)/blog2epub sync $(IDS)

build: setup
	$(BIN)/blog2epub build $(IDS)

run: setup
	$(BIN)/blog2epub -v run $(IDS)

status: setup
	$(BIN)/blog2epub status

# Validate every generated book with the W3C checker (needs Java).
EPUBCHECK_VERSION ?= 5.2.1
epubcheck: build
	@test -f .tools/epubcheck-$(EPUBCHECK_VERSION)/epubcheck.jar || ( \
	  mkdir -p .tools && cd .tools && \
	  curl -sSL -o epubcheck.zip https://github.com/w3c/epubcheck/releases/download/v$(EPUBCHECK_VERSION)/epubcheck-$(EPUBCHECK_VERSION).zip && \
	  unzip -q -o epubcheck.zip && rm epubcheck.zip )
	@for f in output/*.epub; do echo "== $$f"; java -jar .tools/epubcheck-$(EPUBCHECK_VERSION)/epubcheck.jar "$$f" | grep -E 'Messages|ERROR|WARNING'; done

# Re-render the cover previews in covers/ from the cache (needs the `covers` extra and a
# Chromium: `pip install -e ".[covers]" && playwright install chromium`, or set CHROMIUM_PATH).
# `make build` renders the real covers itself, one per volume.
cover: setup
	$(BIN)/pip install -q -e ".[covers]"
	$(BIN)/python scripts/render_cover.py --all

clean:
	rm -rf output .pytest_cache .mypy_cache .ruff_cache
