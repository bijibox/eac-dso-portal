#!/usr/bin/env bash
# Build and publish eac-dso-portal to PyPI. Reads PYPI_TOKEN from .env.
# Run lint + tests first to avoid shipping anything broken.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV_FILE="$ROOT/.env"

if [ -f "$ENV_FILE" ]; then
  set -a; . "$ENV_FILE"; set +a
fi

: "${PYPI_TOKEN:?set PYPI_TOKEN in .env (PyPI project-scoped API token, pypi-...)}"

cd "$ROOT"

echo "--- pytest (offline) ---"
.venv/bin/pytest tests/ -m 'not smoke' -q

echo "--- ruff check ---"
.venv/bin/ruff check src tests
.venv/bin/ruff format --check src tests

echo "--- mypy ---"
.venv/bin/mypy src

echo "--- build ---"
rm -rf dist/
uv build --package eac-dso-portal

echo "--- publish ---"
uv publish dist/* --token "$PYPI_TOKEN"
