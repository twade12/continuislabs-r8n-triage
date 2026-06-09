#!/usr/bin/env bash
# start.sh — launch r8n-triage for local dev or direct-run
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Load .env if present
if [[ -f .env ]]; then
  set -o allexport
  source .env
  set +o allexport
fi

PORT="${PORT:-8000}"
VENV="${SCRIPT_DIR}/.venv"

if [[ -d "$VENV" ]]; then
  source "$VENV/bin/activate"
fi

exec uvicorn web.main:app \
  --host 0.0.0.0 \
  --port "$PORT" \
  --workers 1 \
  --log-level info
