import json
import logging

import pytest
from fastapi.testclient import TestClient
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from pr_reviewer.common.config import GatewaySettings
from pr_reviewer.common.logging import ContextFilter, JsonFormatter, log_context
from pr_reviewer.common.queue import InMemoryJobQueue
from pr_reviewer.gateway.main import create_app
from pr_reviewer.reviewer.agent import ReviewAgent
from pr_reviewer.reviewer.worker import ReviewWorker
from tests.fakes import ScriptedChatModel, finding, submit
from tests.test_gateway import SECRET, post, pr_payload
from tests.test_worker import FakeGitHub


@pytest.fixture(scope="module")
def spans():
    # The global provider can only be set once per process; later tests reuse it.
    exporter = InMemorySpanExporter()
    provider = trace.get_tracer_provider()
    if not isinstance(provider, TracerProvider):
        provider = TracerProvider()
        trace.set_tracer_provider(provider)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    return exporter


@pytest.fixture
def gateway():
    queue = InMemoryJobQueue()
    client = TestClient(create_app(GatewaySettings(github_webhook_secret=SECRET, _env_file=None), queue))
    return client, queue


def format_record(message: str) -> dict:
    record = logging.LogRecord("test", logging.INFO, __file__, 1, message, None, None)
    ContextFilter().filter(record)
    return json.loads(JsonFormatter().format(record))


def test_json_logs_carry_bound_context():
    with log_context(delivery_id="d1"), log_context(attempt=2):
        entry = format_record("hello")

    assert entry["message"] == "hello"
    assert (entry["delivery_id"], entry["attempt"]) == ("d1", 2)
    assert "delivery_id" not in format_record("after")


def test_metrics_endpoint_counts_webhooks(gateway):
    client, _ = gateway
    post(client, pr_payload())

    body = client.get("/metrics").text
    assert 'prr_webhooks_total{event="pull_request",outcome="queued"}' in body


def test_unknown_event_names_share_one_metric_label(gateway):
    client, _ = gateway
    post(client, {}, event="made-up-event", secret="wrong")

    assert 'prr_webhooks_total{event="other",outcome="invalid_signature"}' in client.get("/metrics").text


def test_review_trace_continues_the_webhook_trace(gateway, spans):
    spans.clear()
    client, queue = gateway
    post(client, pr_payload())
    job = queue.dequeue(timeout=0)
    assert "traceparent" in job.trace_context

    agent = ReviewAgent(ScriptedChatModel(responses=[submit("ok", [finding(line=2)], tokens=(100, 20))]))
    ReviewWorker(InMemoryJobQueue(), FakeGitHub(), agent).handle(job)

    by_name = {span.name: span for span in spans.get_finished_spans()}
    webhook, review = by_name["webhook"], by_name["review_job.review"]
    assert review.context.trace_id == webhook.context.trace_id
    assert review.parent.span_id == webhook.context.span_id
    assert {"agent.review", "llm.invoke", "github.publish"} <= by_name.keys()
    assert by_name["llm.invoke"].attributes["llm.input_tokens"] == 100
