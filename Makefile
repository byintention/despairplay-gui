PYTHON ?= $(if $(wildcard .venv/bin/python),.venv/bin/python,python3)
VENV ?= .venv

.PHONY: help install-dev lint format typecheck test check run

help:
	@echo "install-dev  Create .venv --system-site-packages and install [dev]"
	@echo "lint         Ruff check + format --check"
	@echo "format       Ruff check --fix + format"
	@echo "typecheck    mypy --strict on src/despairplay"
	@echo "test         pytest (offline; no speakers)"
	@echo "check        lint + typecheck + test"
	@echo "run          python -m despairplay"

install-dev:
	$(PYTHON) -m venv --system-site-packages $(VENV)
	$(VENV)/bin/python -m pip install -U pip
	$(VENV)/bin/python -m pip install -e '.[dev]'

lint:
	$(PYTHON) -m ruff check src tests
	$(PYTHON) -m ruff format --check src tests

format:
	$(PYTHON) -m ruff check --fix src tests
	$(PYTHON) -m ruff format src tests

typecheck:
	$(PYTHON) -m mypy src/despairplay

test:
	$(PYTHON) -m pytest

check: lint typecheck test

run:
	$(PYTHON) -m despairplay
