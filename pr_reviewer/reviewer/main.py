"""Reviewer service: runs the queue worker and exposes health and metrics endpoints.

Run with: uvicorn pr_reviewer.reviewer.main:create_app --factory --port 8001
"""

import threading
from contextlib import asynccontextmanager

import redis
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from langchain_openai import OpenAIEmbeddings

from pr_reviewer.common.config import ReviewerSettings
from pr_reviewer.common.embedding_cache import CachedEmbeddings, RedisKeyValueStore
from pr_reviewer.common.github_client import GitHubAppClient
from pr_reviewer.common.logging import configure_logging
from pr_reviewer.common.metrics import add_metrics_route
from pr_reviewer.common.queue import build_queue
from pr_reviewer.common.tracing import configure_tracing
from pr_reviewer.reviewer.agent import ReviewAgent
from pr_reviewer.reviewer.budget import TokenBudget
from pr_reviewer.reviewer.drafts import RedisDraftStore
from pr_reviewer.reviewer.worker import ReviewWorker


def build_worker(settings: ReviewerSettings) -> ReviewWorker:
    redis_client = redis.Redis.from_url(settings.redis_url)
    embeddings = CachedEmbeddings(
        OpenAIEmbeddings(
            model=settings.openai_embedding_model,
            api_key=settings.openai_api_key,
            max_retries=settings.openai_max_retries,
        ),
        RedisKeyValueStore(redis_client),
        namespace=settings.openai_embedding_model,
        ttl_seconds=settings.embedding_cache_ttl_seconds,
    )
    return ReviewWorker(
        queue=build_queue(settings),
        github=GitHubAppClient(
            settings.github_app_id,
            settings.github_private_key.get_secret_value(),
            attempts=settings.github_max_attempts,
        ),
        agent=ReviewAgent.from_settings(settings),
        embeddings=embeddings,
        budget=TokenBudget(diff_tokens=settings.diff_token_budget, file_tokens=settings.file_token_budget),
        review_comments_limit=settings.review_comments_limit,
        review_mode=settings.review_mode,
        max_findings=settings.max_findings,
        drafts=RedisDraftStore(redis_client, settings.draft_ttl_seconds),
        max_attempts=settings.job_max_attempts,
        retry_base_seconds=settings.job_retry_base_seconds,
    )


def create_app(settings: ReviewerSettings | None = None, worker: ReviewWorker | None = None) -> FastAPI:
    settings = settings or ReviewerSettings()
    configure_logging(settings.log_level, settings.log_format)
    configure_tracing("pr-reviewer-worker", settings.otel_exporter_otlp_endpoint)
    worker = worker or build_worker(settings)
    thread = threading.Thread(target=worker.run, name="review-worker", daemon=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        thread.start()
        yield
        worker.stop()
        thread.join(timeout=settings.shutdown_grace_seconds)

    app = FastAPI(title="PR Reviewer Worker", lifespan=lifespan)
    add_metrics_route(app)

    @app.get("/health")
    def health() -> JSONResponse:
        if not thread.is_alive():
            return JSONResponse({"status": "worker stopped"}, status_code=503)
        return JSONResponse({"status": "ok"})

    return app
