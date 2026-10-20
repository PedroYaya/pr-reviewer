"""Logging setup: JSON lines with request context attached to every record.

``log_context`` binds fields such as ``delivery_id`` for the duration of a
block, so every log line written while handling one webhook or job carries
them without passing them around. The active trace and span ids are added
too, which links each log line to its trace.
"""

import contextvars
import json
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any

from opentelemetry import trace

_context: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar("log_context", default={})


@contextmanager
def log_context(**fields: Any) -> Iterator[None]:
    token = _context.set({**_context.get(), **fields})
    try:
        yield
    finally:
        _context.reset(token)


def current_context() -> dict[str, Any]:
    return dict(_context.get())


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.context = current_context()
        span = trace.get_current_span().get_span_context()
        if span.is_valid:
            record.context.update(trace_id=format(span.trace_id, "032x"), span_id=format(span.span_id, "016x"))
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "timestamp": datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            **getattr(record, "context", {}),
        }
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, default=str)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        context = " ".join(f"{k}={v}" for k, v in getattr(record, "context", {}).items())
        return f"{line} [{context}]" if context else line


def configure_logging(level: str, fmt: str = "json") -> None:
    root = logging.getLogger()
    # Replace only our own handler, so calling this twice (or under pytest) keeps other handlers.
    for existing in [h for h in root.handlers if getattr(h, "_pr_reviewer", False)]:
        root.removeHandler(existing)
    handler = logging.StreamHandler()
    handler._pr_reviewer = True  # type: ignore[attr-defined]
    handler.addFilter(ContextFilter())
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(TextFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(level.upper())
