#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync --frozen --extra dev
uv run ruff check src/world_engine tests examples/*.py
uv run pytest -q
uv run python examples/sdk_world.py
