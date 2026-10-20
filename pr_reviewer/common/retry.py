"""Retry policy for outbound HTTP calls, built on tenacity.

GitHub signals rate limits with 429, or with 403 plus ``Retry-After`` or
``x-ratelimit-remaining: 0`` (secondary limits). Those requests were never
processed, so they are safe to retry for any method. Timeouts, connection
errors and 5xx responses are only retried for idempotent methods: a POST that
timed out may already have created a review, and posting it twice is worse
than failing the job.
"""

import logging
import time
from collections.abc import Callable

import requests
from tenacity import RetryCallState, Retrying, stop_after_attempt, wait_exponential_jitter

from pr_reviewer.common import metrics

logger = logging.getLogger(__name__)

IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})
RETRYABLE_STATUS = frozenset({500, 502, 503, 504})
# Don't sleep longer than this on a single Retry-After; the job-level retry takes over.
MAX_RETRY_AFTER_SECONDS = 60.0


class RetryableHTTPError(requests.HTTPError):
    """A response the caller may retry; carries the server's suggested wait, if any."""

    def __init__(self, response: requests.Response, retry_after: float | None):
        super().__init__(f"{response.status_code} from {response.url}", response=response)
        self.retry_after = retry_after


def rate_limit_wait(response: requests.Response) -> float | None:
    """Seconds GitHub asks us to wait, or None if the response is not a rate limit."""
    headers = response.headers
    if response.status_code not in (403, 429):
        return None
    if retry_after := headers.get("Retry-After"):
        return float(retry_after)
    if headers.get("x-ratelimit-remaining") == "0" and (reset := headers.get("x-ratelimit-reset")):
        return max(0.0, float(reset) - time.time())
    # A 429 without headers is still a rate limit; a bare 403 is a permission error.
    return 0.0 if response.status_code == 429 else None


def check_response(response: requests.Response, method: str) -> requests.Response:
    """Raise RetryableHTTPError for retryable responses, HTTPError for other failures."""
    wait = rate_limit_wait(response)
    if wait is not None:
        raise RetryableHTTPError(response, wait)
    if response.status_code in RETRYABLE_STATUS and method in IDEMPOTENT_METHODS:
        raise RetryableHTTPError(response, None)
    response.raise_for_status()
    return response


def _should_retry(state: RetryCallState, method: str) -> bool:
    error = state.outcome.exception() if state.outcome else None
    if isinstance(error, RetryableHTTPError):
        return True
    return isinstance(error, (requests.ConnectionError, requests.Timeout)) and method in IDEMPOTENT_METHODS


def _wait(state: RetryCallState, backoff: wait_exponential_jitter) -> float:
    error = state.outcome.exception() if state.outcome else None
    if isinstance(error, RetryableHTTPError) and error.retry_after:
        return min(error.retry_after, MAX_RETRY_AFTER_SECONDS)
    return backoff(state)


def http_retrying(
    service: str,
    method: str,
    attempts: int,
    sleep: Callable[[float], None] = time.sleep,
    initial_wait: float = 0.5,
    max_wait: float = 8.0,
) -> Retrying:
    backoff = wait_exponential_jitter(multiplier=initial_wait, max=max_wait)

    def before_sleep(state: RetryCallState) -> None:
        error = state.outcome.exception()
        reason = type(error).__name__
        if isinstance(error, requests.HTTPError) and error.response is not None:
            reason = str(error.response.status_code)
        metrics.HTTP_RETRIES.labels(service=service, reason=reason).inc()
        logger.warning(
            "Retrying %s %s call attempt=%d reason=%s wait=%.1fs",
            service, method, state.attempt_number, reason, state.next_action.sleep,
        )

    return Retrying(
        retry=lambda state: _should_retry(state, method),
        wait=lambda state: _wait(state, backoff),
        stop=stop_after_attempt(attempts),
        before_sleep=before_sleep,
        sleep=sleep,
        reraise=True,
    )
