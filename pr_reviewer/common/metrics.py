"""Prometheus metrics shared by both services, served on each one's /metrics.

Successful run rate = review_jobs_total{outcome="success"} divided by all
finished jobs (success + dead_letter); skipped jobs are excluded.
"""

from fastapi import FastAPI, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

WEBHOOKS = Counter("prr_webhooks_total", "Webhook deliveries received by the gateway", ["event", "outcome"])

REVIEW_JOBS = Counter(
    "prr_review_jobs_total",
    "Review jobs handled by the worker. outcome: success, skipped, retry, dead_letter",
    ["kind", "outcome"],
)
JOB_DURATION = Histogram(
    "prr_review_job_duration_seconds",
    "Time spent on one attempt of a job",
    ["kind"],
    buckets=(1, 5, 10, 20, 30, 60, 90, 120, 180, 300, 600),
)
QUEUE_WAIT = Histogram(
    "prr_queue_wait_seconds",
    "Time from the webhook being queued to the worker starting it",
    buckets=(0.1, 0.5, 1, 5, 10, 30, 60, 120, 300, 900),
)

LLM_TOKENS = Counter("prr_llm_tokens_total", "Tokens reported by OpenAI", ["type"])
LLM_CALLS = Counter("prr_llm_calls_total", "Chat completion calls made by the review agent")
TOOL_CALLS = Counter("prr_agent_tool_calls_total", "Repository and convention tool calls made by the agent")
FINDINGS = Counter("prr_findings_total", "Findings published or drafted", ["severity"])
GUARDRAIL_DROPS = Counter("prr_guardrail_dropped_findings_total", "Findings removed by output guardrails", ["reason"])
SECRETS_REDACTED = Counter("prr_secrets_redacted_total", "Secrets redacted before reaching the LLM")

HTTP_RETRIES = Counter("prr_http_retries_total", "Outbound HTTP calls retried", ["service", "reason"])


def add_metrics_route(app: FastAPI) -> None:
    @app.get("/metrics", include_in_schema=False)
    def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
