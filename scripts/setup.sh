#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
speech_args=(--extra speech)
if [[ "${1:-}" == "--typed-only" ]]; then
  speech_args=()
fi

cd "$project_root/backend"
uv python install 3.11
uv sync --python 3.11 --extra dev "${speech_args[@]}"

mkdir -p "$project_root/data" "$project_root/.secrets"
if [[ ! -f "$project_root/.env" ]]; then
  cp "$project_root/.env.example" "$project_root/.env"
fi

echo "Setup complete. Run ./scripts/run.sh to start the voice runtime."
