"""Reviewer service: runs the queue worker and exposes a health endpoint.

Run with: uvicorn pr_reviewer.reviewer.main:create_app --factory --port 8001
"""

import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from pr_reviewer.common.config import ReviewerSettings
from pr_reviewer.common.github_client import GitHubAppClient
from pr_reviewer.common.logging import configure_logging
from pr_reviewer.common.queue import RedisJobQueue
from pr_reviewer.reviewer.agent import ReviewAgent
from pr_reviewer.reviewer.worker import ReviewWorker


def build_worker(settings: ReviewerSettings) -> ReviewWorker:
    return ReviewWorker(
        queue=RedisJobQueue.from_url(settings.redis_url, settings.review_queue_name),
        github=GitHubAppClient(settings.github_app_id, settings.github_private_key.get_secret_value()),
        agent=ReviewAgent.from_settings(settings),
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
