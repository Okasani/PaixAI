#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../backend"
exec uv run python -m app.diagnostics.cli "$@"
