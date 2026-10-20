"""Gateway service: verifies GitHub webhooks and queues review jobs.

GitHub gives up on a webhook delivery after 10 seconds, so this service only
validates and enqueues; the slow LLM work happens in the reviewer service.

Run with: uvicorn pr_reviewer.gateway.main:create_app --factory
"""

import json
import logging

from fastapi import FastAPI, Header, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse

from pr_reviewer.common.config import GatewaySettings
from pr_reviewer.common import metrics
from pr_reviewer.common.logging import configure_logging, log_context
from pr_reviewer.common.queue import JobQueue, build_queue
from pr_reviewer.common.tracing import configure_tracing, inject_context, tracer
from pr_reviewer.gateway.events import job_from_issue_comment_event, job_from_pull_request_event
from pr_reviewer.gateway.signature import is_valid_signature

logger = logging.getLogger(__name__)

EVENT_PARSERS = {
    "pull_request": job_from_pull_request_event,
    "issue_comment": job_from_issue_comment_event,
}


def create_app(settings: GatewaySettings | None = None, queue: JobQueue | None = None) -> FastAPI:
    settings = settings or GatewaySettings()
    configure_logging(settings.log_level, settings.log_format)
    configure_tracing("pr-reviewer-gateway", settings.otel_exporter_otlp_endpoint)
    if queue is None:
        queue = build_queue(settings)
    webhook_secret = settings.github_webhook_secret.get_secret_value().encode()

    app = FastAPI(title="PR Reviewer Gateway")
    metrics.add_metrics_route(app)

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
        with log_context(delivery_id=x_github_delivery, event=x_github_event), tracer.start_as_current_span(
            "webhook", attributes={"github.event": x_github_event, "github.delivery_id": x_github_delivery}
        ) as span:
            status, response = await handle(request, x_github_event, x_github_delivery, x_hub_signature_256)
            span.set_attribute("webhook.outcome", status)
            # The event header is unverified when the signature is bad; keep label values bounded.
            event_label = x_github_event if x_github_event in EVENT_PARSERS or x_github_event == "ping" else "other"
            metrics.WEBHOOKS.labels(event=event_label, outcome=status).inc()
            return response

    async def handle(request: Request, event: str, delivery_id: str, signature: str | None) -> tuple[str, JSONResponse]:
        body = await request.body()
        if not is_valid_signature(webhook_secret, body, signature):
            logger.warning("Rejected webhook with invalid signature")
            return "invalid_signature", JSONResponse({"detail": "Invalid webhook signature"}, status_code=401)

        if event == "ping":
            return "ping", JSONResponse({"status": "pong"})
        parse = EVENT_PARSERS.get(event)
        if parse is None:
            return "ignored", JSONResponse({"status": "ignored", "reason": f"event '{event}'"})

        job = parse(json.loads(body), delivery_id)
        if job is None:
            return "ignored", JSONResponse({"status": "ignored", "reason": "nothing to do for this event"})

        job.trace_context = inject_context()
        await run_in_threadpool(queue.enqueue, job)
        logger.info("Queued %s pr=%s/%s#%s", job.kind, job.owner, job.repo, job.pr_number)
        return "queued", JSONResponse({"status": "queued", "delivery_id": job.delivery_id}, status_code=202)

    return app
