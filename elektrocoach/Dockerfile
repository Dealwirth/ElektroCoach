ARG BUILD_FROM=ghcr.io/home-assistant/base:3.24

# ---------------------------------------------------------------------------
# Stage 1: build the frontend SPA (Vite + React + TypeScript + Tailwind)
# ---------------------------------------------------------------------------
FROM node:22-alpine AS frontend

WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------------------------------------------------------------------------
# Stage 2: final Home Assistant app image
# ---------------------------------------------------------------------------
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8 \
    ELEKTROCOACH_DATA=/data \
    ELEKTROCOACH_HOST=0.0.0.0 \
    ELEKTROCOACH_PORT=8099 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    ELEKTROCOACH_BUILD="1.0.15"

RUN apk add --no-cache \
        python3 \
        py3-pip \
        py3-numpy \
        py3-onnxruntime \
        build-base \
        libffi-dev \
        openssl-dev \
        jpeg-dev \
        zlib-dev \
        freetype-dev \
        tesseract-ocr \
        tesseract-ocr-data-deu \
        tesseract-ocr-data-eng \
        tesseract-ocr-data-equ \
        poppler-utils \
        font-dejavu \
        jq

WORKDIR /app

# onnxruntime und numpy kommen als musl-Pakete aus Alpine (es gibt keine
# musllinux-Wheels auf PyPI). tokenizers bringt nur native musl-Wheels; die
# Python-Abhaengigkeiten sind hier unnoetig und wuerden Ballast laden.
COPY requirements.txt requirements-handwriting.txt /app/
RUN pip install --no-cache-dir --break-system-packages -r /app/requirements.txt \
 && pip install --no-cache-dir --break-system-packages --no-deps -r /app/requirements-handwriting.txt

COPY app /app/app
# Lokales Handschrift-Modell (TrOCR, int8-ONNX). Offline und ohne Download.
COPY models /app/models
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Frontend build output is served by the backend at /app/app/static
COPY --from=frontend /build/dist /app/app/static

LABEL \
    io.hass.name="ElektroCoach" \
    io.hass.description="KI-Lernplattform für Elektroniker Energie- und Gebäudetechnik" \
    io.hass.type="app" \
    io.hass.version="1.0.15" \
    io.hass.arch="aarch64|amd64"

CMD [ "/run.sh" ]
