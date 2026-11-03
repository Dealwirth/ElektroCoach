#!/usr/bin/env bash
set -euo pipefail

echo "[ElektroCoach] Starting..."

export ELEKTROCOACH_DATA="${ELEKTROCOACH_DATA:-/data}"
export ELEKTROCOACH_HOST="${ELEKTROCOACH_HOST:-0.0.0.0}"
export ELEKTROCOACH_PORT="${ELEKTROCOACH_PORT:-8099}"

mkdir -p "${ELEKTROCOACH_DATA}"

cd /app
exec python -m uvicorn app.main:app \
  --host "${ELEKTROCOACH_HOST}" \
  --port "${ELEKTROCOACH_PORT}" \
  --proxy-headers \
  --no-server-header \
  --timeout-keep-alive 75 \
  --log-level info
