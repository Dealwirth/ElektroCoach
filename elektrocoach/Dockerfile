ARG BUILD_FROM
FROM ${BUILD_FROM}

ENV LANG=C.UTF-8 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    ELEKTROCOACH_ROOT=/app

# The Home Assistant base image is Alpine Linux, so packages come from apk.
# OCR (tesseract) and PDF rasterisation (poppler) are installed so the default
# image can import scanned documents. The application detects their absence at
# runtime and reports it in the diagnostics instead of failing, so the add-on
# still works if a package is ever unavailable.
RUN apk add --no-cache \
        tesseract-ocr \
        tesseract-ocr-data-deu \
        tesseract-ocr-data-eng \
        poppler-utils \
        curl \
        ca-certificates

WORKDIR /app
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY elektrocoach /app/elektrocoach

COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 8099
CMD [ "/run.sh" ]
