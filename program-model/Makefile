# Makefile for program-model component

.PHONY: help all sync reformat lint test

# Default target
help:
	@echo "program-model component - Available Commands:"
	@echo ""
	@echo "  all        - Run sync, reformat, lint, and test"
	@echo "  sync       - Install dependencies with uv"
	@echo "  reformat   - Format code with ruff"
	@echo "  lint       - Check code formatting, linting, and types"
	@echo "  test       - Run pytest with integration tests"

all: sync reformat lint test

sync:
	uv sync --all-extras

reformat:
	uv run ruff format
	uv run ruff check --fix

lint:
	uv run ruff format --check
	uv run ruff check
	uv run mypy

test:
	# To debug
	# uv run pytest -svv --log-cli-level=DEBUG --runintegration

	# To save unit test results
	# PYTEST_DEBUG_TEMPROOT="/crs_scratch/" uv run pytest -svv --runintegration

	# To run tests
	uv run pytest -svv --runintegration tests/c/test_libpng.py
