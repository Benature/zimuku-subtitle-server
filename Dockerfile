FROM python:3.12-alpine AS python-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

FROM python-base AS builder-base

WORKDIR /build

RUN python -m venv "$VIRTUAL_ENV"

FROM builder-base AS deps-prod

COPY requirements.prod.txt .
RUN pip install --no-compile -r requirements.prod.txt && \
    find "$VIRTUAL_ENV" -type d -name '__pycache__' -prune -exec rm -rf {} + && \
    find "$VIRTUAL_ENV" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete && \
    find "$VIRTUAL_ENV" -type d \( -name 'tests' -o -name 'test' \) -prune -exec rm -rf {} + && \
    rm -rf \
        "$VIRTUAL_ENV"/bin/pip* \
        "$VIRTUAL_ENV"/lib/python3.12/site-packages/pip* \
        "$VIRTUAL_ENV"/lib/python3.12/site-packages/setuptools* \
        "$VIRTUAL_ENV"/lib/python3.12/site-packages/wheel*

FROM builder-base AS deps-develop

COPY requirements.prod.txt requirements.txt ./
RUN pip install -r requirements.txt

FROM python-base AS runtime-base

# ffmpeg 用于音轨对齐；libarchive-tools（bsdtar）用于 RAR 字幕包解压
RUN apk add --no-cache ffmpeg libarchive-tools

# 音轨对齐引擎：alass 静态二进制（仅 x86_64；其他架构可通过 ZIMUKU_ALASS_PATH 外挂）
COPY docker/binaries/alass /usr/local/bin/alass
RUN chmod +x /usr/local/bin/alass

RUN addgroup -g 1000 -S appgroup && \
    adduser -u 1000 -S -D -h /home/appuser -s /sbin/nologin -G appgroup appuser

WORKDIR /app

COPY app ./app

RUN mkdir -p /app/storage && chown -R appuser:appgroup /app

EXPOSE 8000 8001

FROM runtime-base AS runtime

COPY --from=deps-prod /opt/venv /opt/venv

USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime-base AS develop

COPY --from=deps-develop /opt/venv /opt/venv

USER appuser

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
