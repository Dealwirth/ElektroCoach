ARG BUILD_FROM
FROM ${BUILD_FROM}

ENV OLLAMA_HOST=0.0.0.0:11434 \
    OLLAMA_MODELS=/data/ollama/models \
    OLLAMA_KEEP_ALIVE=5m \
    OLLAMA_NUM_PARALLEL=1 \
    OLLAMA_MAX_LOADED_MODELS=1 \
    OLLAMA_CONTEXT_LENGTH=2048 \
    OLLAMA_FLASH_ATTENTION=0

RUN apk add --no-cache curl ca-certificates bash

COPY run.sh /run.sh
RUN chmod +x /run.sh

EXPOSE 11434
CMD [ "/run.sh" ]
