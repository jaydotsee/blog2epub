UV ?= uv

.PHONY: setup test lint format typecheck check list detect sync build run status epubcheck cover docs about clean

# `uv sync` creates .venv from uv.lock with every extra and the dev group; idempotent and fast.
setup:
	$(UV) sync --all-extras

lock:
	$(UV) lock

test: setup
	$(UV) run pytest -q

lint: setup
	$(UV) run ruff check src tests scripts
	$(UV) run ruff format --check src tests scripts

format: setup
	$(UV) run ruff check --fix src tests scripts
	$(UV) run ruff format src tests scripts

typecheck: setup
	$(UV) run mypy src

check: lint typecheck test

list: setup
	$(UV) run blog2epub list

# make detect URL=https://example.com/blog
detect: setup
	$(UV) run blog2epub detect $(URL)

# IDS="tyk api-management" make sync   (defaults to everything)
sync: setup
	$(UV) run blog2epub sync $(IDS)

build: setup
	$(UV) run blog2epub build $(IDS)

run: setup
	$(UV) run blog2epub -v run $(IDS)

status: setup
	$(UV) run blog2epub status

# Validate every generated book with the W3C checker (needs Java).
EPUBCHECK_VERSION ?= 5.2.1
epubcheck: build
	@test -f .tools/epubcheck-$(EPUBCHECK_VERSION)/epubcheck.jar || ( \
	  mkdir -p .tools && cd .tools && \
	  curl -sSL -o epubcheck.zip https://github.com/w3c/epubcheck/releases/download/v$(EPUBCHECK_VERSION)/epubcheck-$(EPUBCHECK_VERSION).zip && \
	  unzip -q -o epubcheck.zip && rm epubcheck.zip )
	@for f in output/*.epub; do echo "== $$f"; java -jar .tools/epubcheck-$(EPUBCHECK_VERSION)/epubcheck.jar "$$f" | grep -E 'Messages|ERROR|WARNING'; done

# Re-render the cover previews in covers/ from the cache. Needs a Chromium once:
# `uv run playwright install chromium`, or set CHROMIUM_PATH. `make build` renders the real
# covers itself, one per volume.
cover: setup
	$(UV) run python scripts/render_cover.py --all

# Re-render the README's reader screenshots and the repository social preview from the newest
# book in output/. Needs a Chromium, as `make cover` does.
docs: setup
	$(UV) run python scripts/render_docs.py

# Fill in the repository's About sidebar on GitHub (description, website, topics). Needs the gh
# CLI logged in; the values live in the script. The social preview image is uploaded by hand.
about:
	scripts/set_github_about.sh

clean:
	rm -rf output .pytest_cache .mypy_cache .ruff_cache
