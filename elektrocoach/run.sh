#!/usr/bin/env bash
# ElektroCoach add-on entrypoint.
#
# Responsibilities:
#   1. Read the add-on options that Home Assistant writes to /data/options.json.
#   2. Export them as ELEKTROCOACH_* environment variables.
#   3. Start the backend (uvicorn) on the ingress port.
#
# The process is started with `exec` so that the supervisor receives the
# signals it needs to stop the add-on cleanly.
set -e

OPTIONS_FILE="/data/options.json"
export ELEKTROCOACH_OPTIONS_FILE="${OPTIONS_FILE}"

# Defaults are also defined in the application itself; this only forwards the
# file path. The application validates the values and falls back on invalid
# input, so a broken options file can never keep the add-on from starting.
export ELEKTROCOACH_PORT="${ELEKTROCOACH_PORT:-8099}"
export ELEKTROCOACH_DATA_DIR="${ELEKTROCOACH_DATA_DIR:-/data}"
export ELEKTROCOACH_SHARE_DIR="${ELEKTROCOACH_SHARE_DIR:-/share}"
export ELEKTROCOACH_ROOT="${ELEKTROCOACH_ROOT:-/app}"

echo "[elektrocoach] starting on port ${ELEKTROCOACH_PORT}, data dir ${ELEKTROCOACH_DATA_DIR}"

cd /app
exec python3 -m elektrocoach.backend.main
