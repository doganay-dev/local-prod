FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN addgroup --system --gid 10001 app \
    && adduser --system --uid 10001 --ingroup app --home /nonexistent --no-create-home app

COPY requirements.txt ./
RUN pip install --no-cache-dir --requirement requirements.txt

COPY --chown=app:app app.py ./app.py

FROM base AS test

COPY requirements-dev.txt ./
RUN pip install --no-cache-dir --requirement requirements-dev.txt
COPY tests ./tests
CMD ["pytest", "-q", "tests"]

FROM base AS runtime

USER 10001:10001
EXPOSE 8080

CMD ["gunicorn", "--bind=0.0.0.0:8080", "--workers=1", "--threads=2", "--timeout=180", "--access-logfile=-", "app:app"]
