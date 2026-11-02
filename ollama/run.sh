#!/usr/bin/env bash
# ElektroCoach Ollama add-on entrypoint.
#
# Installs the Ollama binary on first start (arch aware), then starts the
# server and pulls the configured models. Model pulls happen in the background
# so the server is reachable immediately; the ElektroCoach app polls /api/tags
# until the model is present and reports progress in the setup wizard.
set -e

MODELS_FILE="/data/models.json"
OPTIONS_FILE="/data/options.json"

ARCH="$(uname -m)"
case "${ARCH}" in
  aarch64|arm64) OLLAMA_ARCH="arm64" ;;
  x86_64|amd64)  OLLAMA_ARCH="amd64" ;;
  *) echo "[ollama] unsupported architecture: ${ARCH}"; exit 1 ;;
esac

OLLAMA_BIN="/data/bin/ollama"
if [ ! -x "${OLLAMA_BIN}" ]; then
  echo "[ollama] installing ollama for ${OLLAMA_ARCH} (first start, may take a while)"
  mkdir -p /data/bin
  curl -fsSL -o /tmp/ollama.tgz \
    "https://github.com/ollama/ollama/releases/latest/download/ollama-linux-${OLLAMA_ARCH}.tgz"
  tar -xzf /tmp/ollama.tgz -C /data
  rm -f /tmp/ollama.tgz
  # The release archive extracts to /data/bin/ollama and /data/lib.
  if [ ! -x "${OLLAMA_BIN}" ]; then
    echo "[ollama] unexpected archive layout, searching for binary"
    FOUND="$(find /data -type f -name ollama -perm -u+x | head -n1)"
    if [ -z "${FOUND}" ]; then
      echo "[ollama] FATAL: ollama binary not found after extraction"
      exit 1
    fi
    OLLAMA_BIN="${FOUND}"
  fi
fi

export LD_LIBRARY_PATH="/data/lib:${LD_LIBRARY_PATH}"

# Read a value from the add-on options. Home Assistant writes options.json as a
# single-line JSON object, and the minimal Alpine base image has neither python
# nor jq, so a targeted sed extraction is used. Unknown or empty values fall
# back to the documented default.
read_opt() {
  key="$1"
  default="$2"
  value=""
  if [ -f "${OPTIONS_FILE}" ]; then
    value="$(sed -n "s/.*\"${key}\"[[:space:]]*:[[:space:]]*\"\{0,1\}\([^\",}]*\)\"\{0,1\}.*/\1/p" \
      "${OPTIONS_FILE}" | head -n 1)"
  fi
  if [ -z "${value}" ]; then
    value="${default}"
  fi
  printf '%s' "${value}"
}

# Every option in config.yaml is applied here, so none of them is decorative.
export OLLAMA_HOST="0.0.0.0:11434"
export OLLAMA_MODELS="${OLLAMA_MODELS:-/data/ollama/models}"
export OLLAMA_KEEP_ALIVE="$(read_opt keep_alive 5m)"
export OLLAMA_NUM_PARALLEL="$(read_opt num_parallel 1)"
export OLLAMA_MAX_LOADED_MODELS="$(read_opt max_loaded_models 1)"
export OLLAMA_CONTEXT_LENGTH="$(read_opt context_length 2048)"

echo "[ollama] keep_alive=${OLLAMA_KEEP_ALIVE} num_parallel=${OLLAMA_NUM_PARALLEL} max_loaded_models=${OLLAMA_MAX_LOADED_MODELS} context_length=${OLLAMA_CONTEXT_LENGTH}"

mkdir -p "${OLLAMA_MODELS}"

echo "[ollama] starting server on ${OLLAMA_HOST}"
"${OLLAMA_BIN}" serve &
OLLAMA_PID=$!

# Wait for the API to accept connections before pulling models.
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:11434/api/version" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

pull_models() {
  if [ ! -f "${OPTIONS_FILE}" ]; then
    return
  fi
  # Read the model list without depending on python or jq, which the minimal
  # Alpine base image does not provide. Home Assistant writes options.json as a
  # single-line JSON object, so a targeted sed extraction is sufficient.
  sed -n 's/.*"models"[[:space:]]*:[[:space:]]*\[\([^]]*\)\].*/\1/p' \
    "${OPTIONS_FILE}" \
    | tr ',' '\n' \
    | sed -n 's/.*"\([^"]*\)".*/\1/p' > "${MODELS_FILE}"
  if [ ! -s "${MODELS_FILE}" ]; then
    echo "qwen2.5:1.5b" > "${MODELS_FILE}"
  fi
  while read -r model; do
    [ -z "${model}" ] && continue
    echo "[ollama] ensuring model: ${model}"
    "${OLLAMA_BIN}" pull "${model}" || echo "[ollama] WARNING: pull failed for ${model}"
  done < "${MODELS_FILE}"
}

# Pull in the background; the HTTP API stays available during the download.
pull_models &

# Keep the container alive with the server process.
wait "${OLLAMA_PID}"
