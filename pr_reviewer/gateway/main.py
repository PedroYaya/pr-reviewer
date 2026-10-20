"""Gateway service: verifies GitHub webhooks and queues review jobs.

GitHub gives up on a webhook delivery after 10 seconds, so this service only
validates and enqueues; the slow LLM work happens in the reviewer service.

Run with: uvicorn pr_reviewer.gateway.main:create_app --factory
"""

import json
import logging

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from pr_reviewer.common.config import GatewaySettings
from pr_reviewer.common.logging import configure_logging
from pr_reviewer.common.queue import JobQueue, RedisJobQueue
from pr_reviewer.gateway.events import job_from_issue_comment_event, job_from_pull_request_event
from pr_reviewer.gateway.signature import is_valid_signature

logger = logging.getLogger(__name__)

EVENT_PARSERS = {
    "pull_request": job_from_pull_request_event,
    "issue_comment": job_from_issue_comment_event,
}


def create_app(settings: GatewaySettings | None = None, queue: JobQueue | None = None) -> FastAPI:
    settings = settings or GatewaySettings()
    configure_logging(settings.log_level)
    if queue is None:
        queue = RedisJobQueue.from_url(settings.redis_url, settings.review_queue_name)
    webhook_secret = settings.github_webhook_secret.get_secret_value().encode()

    app = FastAPI(title="PR Reviewer Gateway")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/webhook")
    async def webhook(
        request: Request,
        x_github_event: str = Header(),
        x_github_delivery: str = Header(),
        x_hub_signature_256: str | None = Header(default=None),
    ) -> JSONResponse:
        body = await request.body()
        if not is_valid_signature(webhook_secret, body, x_hub_signature_256):
            raise HTTPException(status_code=401, detail="Invalid webhook signature")

        if x_github_event == "ping":
            return JSONResponse({"status": "pong"})
        parse = EVENT_PARSERS.get(x_github_event)
        if parse is None:
            return JSONResponse({"status": "ignored", "reason": f"event '{x_github_event}'"})

        job = parse(json.loads(body), x_github_delivery)
        if job is None:
            return JSONResponse({"status": "ignored", "reason": "nothing to do for this event"})

        await run_in_threadpool(queue.enqueue, job)
        logger.info(
            "Queued %s delivery=%s pr=%s/%s#%s", job.kind, job.delivery_id, job.owner, job.repo, job.pr_number
        )
        return JSONResponse({"status": "queued", "delivery_id": job.delivery_id}, status_code=202)

    return app
