#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root/stage"
npm ci

echo "Live2D stage dependencies installed."
echo "Run ./scripts/run-stage.sh, then ./scripts/run.sh --stage in another terminal."
