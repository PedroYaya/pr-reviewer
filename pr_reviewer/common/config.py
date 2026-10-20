"""Service settings, loaded from environment variables or a local .env file."""

from typing import Literal

from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class QueueSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    redis_url: str = "redis://localhost:6379/0"
    review_queue_name: str = "pr-review-jobs"
    log_level: str = "INFO"
    log_format: Literal["json", "text"] = "json"
    # Tracing is off unless this is set, e.g. http://localhost:4318
    otel_exporter_otlp_endpoint: str | None = None


class GatewaySettings(QueueSettings):
    github_webhook_secret: SecretStr


class ReviewerSettings(QueueSettings):
    github_app_id: str
    github_private_key: SecretStr
    openai_api_key: SecretStr
    openai_model: str = "gpt-4o"
    openai_temperature: float = 0.2
    openai_embedding_model: str = "text-embedding-3-small"
    # The OpenAI SDK retries 429, 5xx and connection errors with backoff, honouring Retry-After.
    openai_max_retries: int = 4
    openai_timeout_seconds: float = 120.0

    github_max_attempts: int = 4
    # A job that still fails is retried later (base * 4^n seconds), then dead-lettered.
    job_max_attempts: int = 3
    job_retry_base_seconds: float = 30.0

    diff_token_budget: int = 24_000
    file_token_budget: int = 6_000
    conventions_top_k: int = 6
    review_comments_limit: int = 100
    embedding_cache_ttl_seconds: int = 30 * 24 * 3600

    # "auto" publishes reviews directly; "approval" posts a draft a maintainer must approve.
    review_mode: Literal["auto", "approval"] = "auto"
    max_findings: int = 15
    draft_ttl_seconds: int = 7 * 24 * 3600

    @field_validator("github_private_key", mode="before")
    @classmethod
    def _unescape_newlines(cls, value: str) -> str:
        # .env files usually store the PEM key on one line with literal "\n".
        return value.replace("\\n", "\n") if isinstance(value, str) else value
