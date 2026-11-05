#!/usr/bin/env bash
# Run every check, and report all failures.
cd "$(dirname "$0")/.."

status=0
uv run ruff check . || status=1
uv run ruff format --check . || status=1
uv run pyright || status=1
uv run pytest -q || status=1
exit "$status"
