FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Install dependencies first for better layer caching.
COPY pyproject.toml ./
RUN pip install --upgrade pip && pip install .

COPY app ./app

EXPOSE 8000

# One image, two roles. APP_ROLE=worker runs the stream consumer; anything else runs the
# API server (honoring $PORT for Railway/PaaS, falling back to 8000 locally). This lets a
# platform that can't set a per-service start command (e.g. Railway CLI) pick the role via env.
CMD ["sh", "-c", "if [ \"$APP_ROLE\" = worker ]; then exec python -m app.worker; else exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}; fi"]
