"""OpenTelemetry tracing, off unless an OTLP endpoint is configured.

The code only depends on the OpenTelemetry API, whose tracer is a no-op until
a provider is installed. With ``OTEL_EXPORTER_OTLP_ENDPOINT`` set (and the
``otel`` extra installed), spans are exported over OTLP/HTTP to a collector,
Jaeger, Grafana Tempo or AWS X-Ray via the ADOT collector.

The gateway injects the trace context into each job, and the worker continues
it, so one trace covers the webhook, the queue wait and the review.
"""

import logging

from opentelemetry import context, propagate, trace

logger = logging.getLogger(__name__)

tracer = trace.get_tracer("pr_reviewer")


def configure_tracing(service_name: str, otlp_endpoint: str | None) -> None:
    if not otlp_endpoint:
        return
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        logger.warning("OTLP endpoint set but the 'otel' extra is not installed; tracing stays off")
        return

    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{otlp_endpoint.rstrip('/')}/v1/traces")))
    trace.set_tracer_provider(provider)
    logger.info("Tracing enabled service=%s endpoint=%s", service_name, otlp_endpoint)


def inject_context() -> dict[str, str]:
    """Current trace context as W3C headers (``traceparent``), for a queued job."""
    carrier: dict[str, str] = {}
    propagate.inject(carrier)
    return carrier


def extract_context(carrier: dict[str, str]) -> context.Context:
    return propagate.extract(carrier)
