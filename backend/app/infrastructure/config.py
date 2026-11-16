"""Application configuration, loaded from environment (.env)."""
from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Infra
    redis_url: str = "redis://localhost:6379/0"

    # AI provider: OpenRouter (one OpenAI-compatible endpoint for every model).
    # Absent key -> deterministic mock fallback so the app still boots & demos.
    openrouter_api_key: str | None = None
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    openrouter_parse_model: str = "google/gemini-3.1-flash-lite"    # PDF -> markdown
    openrouter_summary_model: str = "google/gemini-3.1-flash-lite"  # summary
    openrouter_ocr_model: str = "openai/gpt-5-mini"                 # OCR (vision)
    openrouter_max_tokens: int = 4096
    openrouter_referer: str = "http://localhost:3000"
    openrouter_title: str = "Summer PDF Processing"

    # Upload limits
    max_upload_bytes: int = 20 * 1024 * 1024  # 20 MB per file, aligned to Gemini inline limit
    max_request_bytes: int = 60 * 1024 * 1024  # aggregate cap across all files in one request
    gemini_max_pages: int = 1000
    # OCR rendering safety: scale a page down so its raster never exceeds this pixel budget.
    ocr_max_pixels: int = 4_000_000  # ~4 MP per page

    # Login brute-force protection (attempts/min per username+IP).
    login_max_per_min: int = 10

    # Raw-bytes retention in Redis
    raw_ttl_seconds: int = 24 * 3600

    # Auth. NOTE: the defaults below are DEMO credentials for zero-config local boot only.
    # Always override API_KEYS and ACCOUNTS via .env in any shared/production deployment.
    # API keys: comma-separated "key:principal" pairs (for curl / programmatic access).
    api_keys: str = "demo-key:demo-user"

    # Login accounts: comma-separated "username:password:principal:daily_limit".
    accounts: str = "tester:test-pass-123:tester:10"
    session_ttl_seconds: int = 24 * 3600

    # Rate limits (per principal)
    daily_limit: int = 100
    max_concurrent: int = 5
    rate_per_min: int = 30
    inflight_ttl_seconds: int = 900  # stale in-flight entries age out of the concurrency ZSET

    # Worker / queue tuning
    stream_name: str = "docs:stream"
    dead_stream_name: str = "docs:dead"
    consumer_group: str = "workers"
    reaper_min_idle_ms: int = 30_000
    max_delivery_attempts: int = 3
    block_ms: int = 5_000

    def api_key_map(self) -> dict[str, str]:
        """Parse API_KEYS into {key: principal}."""
        out: dict[str, str] = {}
        for pair in self.api_keys.split(","):
            pair = pair.strip()
            if not pair or ":" not in pair:
                continue
            key, principal = pair.split(":", 1)
            out[key.strip()] = principal.strip()
        return out

    def account_map(self) -> dict[str, dict]:
        """Parse ACCOUNTS into {username: {password, principal, daily_limit}}."""
        out: dict[str, dict] = {}
        for entry in self.accounts.split(","):
            entry = entry.strip()
            if not entry:
                continue
            parts = entry.split(":")
            if len(parts) < 3:
                continue
            username, password, principal = parts[0].strip(), parts[1].strip(), parts[2].strip()
            daily_limit = None
            if len(parts) >= 4 and parts[3].strip().isdigit():
                daily_limit = int(parts[3].strip())
            out[username] = {"password": password, "principal": principal, "daily_limit": daily_limit}
        return out


@lru_cache
def get_settings() -> Settings:
    return Settings()
