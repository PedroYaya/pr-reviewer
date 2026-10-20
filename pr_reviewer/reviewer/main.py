"""Reviewer service: runs the queue worker and exposes a health endpoint.

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
from pr_reviewer.common.queue import RedisJobQueue
from pr_reviewer.reviewer.agent import ReviewAgent
from pr_reviewer.reviewer.budget import TokenBudget
from pr_reviewer.reviewer.worker import ReviewWorker


def build_worker(settings: ReviewerSettings) -> ReviewWorker:
    redis_client = redis.Redis.from_url(settings.redis_url)
    embeddings = CachedEmbeddings(
        OpenAIEmbeddings(model=settings.openai_embedding_model, api_key=settings.openai_api_key),
        RedisKeyValueStore(redis_client),
        namespace=settings.openai_embedding_model,
        ttl_seconds=settings.embedding_cache_ttl_seconds,
    )
    return ReviewWorker(
        queue=RedisJobQueue(redis_client, settings.review_queue_name),
        github=GitHubAppClient(settings.github_app_id, settings.github_private_key.get_secret_value()),
        agent=ReviewAgent.from_settings(settings),
        embeddings=embeddings,
        budget=TokenBudget(diff_tokens=settings.diff_token_budget, file_tokens=settings.file_token_budget),
        review_comments_limit=settings.review_comments_limit,
    )


def create_app(settings: ReviewerSettings | None = None, worker: ReviewWorker | None = None) -> FastAPI:
    settings = settings or ReviewerSettings()
    configure_logging(settings.log_level)
    worker = worker or build_worker(settings)
    thread = threading.Thread(target=worker.run, name="review-worker", daemon=True)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        thread.start()
        yield
        worker.stop()
        thread.join(timeout=10)

    app = FastAPI(title="PR Reviewer Worker", lifespan=lifespan)

    @app.get("/health")
    def health() -> JSONResponse:
        if not thread.is_alive():
            return JSONResponse({"status": "worker stopped"}, status_code=503)
        return JSONResponse({"status": "ok"})

    return app
