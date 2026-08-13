FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    STATE_DIR=/data \
    SPOOL_DIR=/data/spool \
    WORKFLOW_CONFIG_PATH=/app/config/workflow_config.json \
    PUBLIC_BASE_URL=http://gateway:8787

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && adduser --disabled-password --gecos "" --uid 10001 gateway \
    && mkdir -p /data/spool \
    && chown -R gateway:gateway /data

COPY --chown=gateway:gateway app ./app
COPY --chown=gateway:gateway config ./config

USER gateway
EXPOSE 8787

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8787/healthz', timeout=5)"

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8787", "--workers", "1"]

