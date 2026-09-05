#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root/stage"

if [[ ! -d node_modules ]]; then
  echo "Live2D stage dependencies are missing. Run ./scripts/setup-stage.sh first." >&2
  exit 2
fi

npm run start
