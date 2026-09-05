PYTHON ?= python3
VENV   ?= .venv
BIN    := $(VENV)/bin

.PHONY: setup test list detect sync build run status clean

setup: $(VENV)/.ok
$(VENV)/.ok: pyproject.toml
	$(PYTHON) -m venv $(VENV)
	$(BIN)/pip install -q -e ".[dev]"
	touch $@

test: setup
	$(BIN)/pytest -q

list: setup
	$(BIN)/blog2epub list

# make detect URL=https://example.com/blog
detect: setup
	$(BIN)/blog2epub detect $(URL)

# BLOG=tyk make sync   (defaults to every configured blog)
sync: setup
	$(BIN)/blog2epub sync $(BLOG)

build: setup
	$(BIN)/blog2epub build $(BLOG)

run: setup
	$(BIN)/blog2epub run $(BLOG)

status: setup
	$(BIN)/blog2epub status

clean:
	rm -rf output
