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

# Default: API server. Honors $PORT (Railway/PaaS) and falls back to 8000 locally.
# The worker service overrides this command (docker-compose / Railway start command).
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
