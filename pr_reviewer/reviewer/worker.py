"""Consumes review jobs from the queue and posts the results to GitHub."""

import logging
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any, Literal

import requests
from langchain_core.embeddings import Embeddings
from opentelemetry.trace import Status, StatusCode

from pr_reviewer.common import metrics
from pr_reviewer.common.github_client import GitHubAppClient
from pr_reviewer.common.logging import log_context
from pr_reviewer.common.models import ReviewJob
from pr_reviewer.common.queue import JobQueue
from pr_reviewer.common.retry import RetryableHTTPError
from pr_reviewer.common.tracing import extract_context, tracer
from pr_reviewer.reviewer.agent import ReviewAgent
from pr_reviewer.reviewer.budget import TokenBudget
from pr_reviewer.reviewer.conventions import guideline_documents, review_comment_documents
from pr_reviewer.reviewer.drafts import DraftStore, InMemoryDraftStore, ReviewDraft, draft_key
from pr_reviewer.reviewer.history import ReviewHistory
from pr_reviewer.reviewer.pipeline import PipelineOptions, PipelineOutput, run_review_pipeline
from pr_reviewer.reviewer.publisher import build_draft_comment, build_review
from pr_reviewer.reviewer.repo_tools import GitHubRepoReader, RepoReader
from pr_reviewer.reviewer.retrieval import ConventionIndex

logger = logging.getLogger(__name__)

POLL_TIMEOUT_SECONDS = 5
# Pause after a queue failure (e.g. Redis down) so the loop doesn't spin.
QUEUE_ERROR_BACKOFF_SECONDS = 2
DEFAULT_BUDGET = TokenBudget(diff_tokens=24_000, file_tokens=6_000)
DEFAULT_REVIEW_COMMENTS_LIMIT = 100
DEFAULT_MAX_FINDINGS = 15
DEFAULT_JOB_ATTEMPTS = 3
DEFAULT_RETRY_BASE_SECONDS = 30.0
# Client errors that a later attempt can't fix: 404 (PR or repo gone), 422 (review rejected), …
RETRYABLE_CLIENT_STATUS = frozenset({408, 409, 429})

ReviewMode = Literal["auto", "approval"]
JobOutcome = Literal["success", "skipped"]


class PublishError(Exception):
    """Posting to the PR failed in a way that leaves it unknown whether GitHub saved it."""


@contextmanager
def publishing(span_name: str, **attributes: Any) -> Iterator[None]:
    """Wrap a POST that must not be duplicated.

    A rate-limited request was never processed, so the job may run again. After
    a timeout or 5xx the review may already be on the PR; retrying could post it
    twice, so the job goes to the dead-letter queue for a person to check.
    """
    with tracer.start_as_current_span(span_name, attributes=attributes):
        try:
            yield
        except RetryableHTTPError:
            raise
        except requests.HTTPError as error:
            if error.response is not None and error.response.status_code < 500:
                raise
            raise PublishError(f"unknown whether the post was saved: {error!r}") from error
        except (requests.ConnectionError, requests.Timeout) as error:
            raise PublishError(f"unknown whether the post was saved: {error!r}") from error


def is_retryable(error: Exception) -> bool:
    """Whether running the job again later could succeed."""
    if isinstance(error, PublishError):
        return False
    status = getattr(error, "status_code", None)  # openai.APIStatusError
    if isinstance(error, requests.HTTPError) and error.response is not None:
        status = error.response.status_code
    if status is not None and 400 <= status < 500:
        return status in RETRYABLE_CLIENT_STATUS
    # 5xx, timeouts, connection errors and invalid model output (pydantic.ValidationError).
    return True


class ReviewWorker:
    def __init__(
        self,
        queue: JobQueue,
        github: GitHubAppClient,
        agent: ReviewAgent,
        embeddings: Embeddings | None = None,
        budget: TokenBudget = DEFAULT_BUDGET,
        review_comments_limit: int = DEFAULT_REVIEW_COMMENTS_LIMIT,
        review_mode: ReviewMode = "auto",
        max_findings: int = DEFAULT_MAX_FINDINGS,
        drafts: DraftStore | None = None,
        max_attempts: int = DEFAULT_JOB_ATTEMPTS,
        retry_base_seconds: float = DEFAULT_RETRY_BASE_SECONDS,
        history: ReviewHistory | None = None,
    ):
        self._queue = queue
        self._github = github
        self._agent = agent
        self._embeddings = embeddings
        self._review_comments_limit = review_comments_limit
        self._review_mode = review_mode
        self._options = PipelineOptions(budget=budget, max_findings=max_findings)
        self._drafts = drafts if drafts is not None else InMemoryDraftStore()
        self._max_attempts = max_attempts
        self._retry_base_seconds = retry_base_seconds
        self._history = history
        self._stop = threading.Event()

    def handle(self, job: ReviewJob) -> None:
        """Run one job with logging context, a trace span and metrics; retry or dead-letter on failure."""
        fields = {
            "delivery_id": job.delivery_id, "kind": job.kind, "attempt": job.attempt,
            "pr": f"{job.owner}/{job.repo}#{job.pr_number}",
        }
        with log_context(**fields), tracer.start_as_current_span(
            f"review_job.{job.kind}", context=extract_context(job.trace_context), attributes=fields
        ) as span:
            if job.attempt == 1:
                metrics.QUEUE_WAIT.observe(max(0.0, time.time() - job.enqueued_at))
            started = time.monotonic()
            if job.kind == "review":
                self._record(lambda h: h.started(job))
            try:
                outcome = self.process(job)
            except Exception as error:
                span.record_exception(error)
                span.set_status(Status(StatusCode.ERROR, type(error).__name__))
                self._handle_failure(job, error)
            else:
                metrics.REVIEW_JOBS.labels(kind=job.kind, outcome=outcome).inc()
                span.set_attribute("job.outcome", outcome)
            finally:
                metrics.JOB_DURATION.labels(kind=job.kind).observe(time.monotonic() - started)

    def _handle_failure(self, job: ReviewJob, error: Exception) -> None:
        if is_retryable(error) and job.attempt < self._max_attempts:
            delay = self._retry_base_seconds * 4 ** (job.attempt - 1)
            self._queue.schedule(job.model_copy(update={"attempt": job.attempt + 1}), delay)
            if job.kind == "review":
                self._record(lambda h: h.failed(job, "retrying", f"{type(error).__name__}: {error}"))
            metrics.REVIEW_JOBS.labels(kind=job.kind, outcome="retry").inc()
            logger.warning("Job failed, retrying in %.0fs: %r", delay, error, exc_info=True)
            return
        self._queue.dead_letter(job, f"{type(error).__name__}: {error}")
        if job.kind == "review":
            self._record(lambda h: h.failed(job, "failed", f"{type(error).__name__}: {error}"))
        metrics.REVIEW_JOBS.labels(kind=job.kind, outcome="dead_letter").inc()
        logger.error("Job failed permanently, moved to dead-letter queue: %r", error, exc_info=True)

    def process(self, job: ReviewJob) -> JobOutcome:
        with tracer.start_as_current_span("github.get_pull_request"):
            pr = self._github.get_pull_request(job.installation_id, job.owner, job.repo, job.pr_number)
        if job.kind == "approve":
            return self._approve(job, pr)
        if job.kind == "dismiss":
            return self._dismiss(job)
        return self._review(job, pr)

    def _review(self, job: ReviewJob, pr: dict[str, Any]) -> JobOutcome:
        head_sha = pr["head"]["sha"]
        if job.head_sha and job.head_sha != head_sha:
            # A newer push already queued its own job; don't review stale code.
            logger.info("Skipping stale job")
            self._record(lambda h: h.finished(job, "skipped", note="a newer commit was pushed"))
            return "skipped"

        with tracer.start_as_current_span("github.list_pull_request_files"):
            files = self._github.list_pull_request_files(job.installation_id, job.owner, job.repo, job.pr_number)
        repo = GitHubRepoReader(self._github, job.installation_id, job.owner, job.repo, head_sha)
        output = run_review_pipeline(
            self._agent,
            pr["title"],
            pr.get("body") or "",
            files,
            repo,
            self._options,
            load_conventions=lambda safe_repo: self._load_conventions(job, safe_repo),
        )
        if output is None:
            logger.info("Nothing reviewable files=%d", len(files))
            self._record(lambda h: h.finished(job, "skipped", head_sha=head_sha, note="no reviewable files"))
            return "skipped"

        body, comments = build_review(output.result, output.files, output.omitted)
        with publishing("github.publish", review_mode=self._review_mode):
            self._publish(job, head_sha, output, body, comments)
        status = "awaiting_approval" if self._review_mode == "approval" else "published"
        self._record(lambda h: h.finished(job, status, output, head_sha=head_sha))

        run = output.run
        for f in output.result.findings:
            metrics.FINDINGS.labels(severity=f.severity).inc()
        for item in output.dropped:
            metrics.GUARDRAIL_DROPS.labels(reason=item.reason).inc()
        metrics.SECRETS_REDACTED.inc(len(output.secret_hits))
        logger.info(
            "Review %s findings=%d inline=%d dropped=%d secrets=%d omitted=%d "
            "input_tokens=%d output_tokens=%d llm_calls=%d tool_calls=%d",
            "drafted" if self._review_mode == "approval" else "posted",
            len(output.result.findings), len(comments), len(output.dropped), len(output.secret_hits),
            len(output.omitted), run.input_tokens, run.output_tokens, run.llm_calls, run.tool_calls,
        )
        for item in output.dropped:
            logger.info(
                "Guardrail dropped finding reason=%s location=%s:%s",
                item.reason, item.finding.path, item.finding.line,
            )
        return "success"

    def _publish(self, job: ReviewJob, head_sha: str, output: PipelineOutput, body: str, comments: list[dict[str, Any]]) -> None:
        if self._review_mode == "approval":
            self._drafts.save(
                draft_key(job.owner, job.repo, job.pr_number),
                ReviewDraft(head_sha=head_sha, body=body, comments=comments),
            )
            self._github.create_issue_comment(
                job.installation_id, job.owner, job.repo, job.pr_number,
                build_draft_comment(output.result, comments, head_sha),
            )
        else:
            self._github.create_review(
                job.installation_id, job.owner, job.repo, job.pr_number, head_sha, body, comments
            )

    def _approve(self, job: ReviewJob, pr: dict[str, Any]) -> JobOutcome:
        key = draft_key(job.owner, job.repo, job.pr_number)
        draft = self._drafts.get(key)
        if draft is None:
            self._reply(job, "There is no AI review draft waiting for approval on this PR. Comment `/ai-review` to create one.")
            return "skipped"
        if draft.head_sha != pr["head"]["sha"]:
            self._drafts.delete(key)
            self._resolve_draft(job, "dismissed", "new commits since the draft")
            self._reply(
                job,
                f"The draft was for `{draft.head_sha[:7]}`, but the PR has new commits since. "
                "Comment `/ai-review` to review the latest changes.",
            )
            return "skipped"

        body = f"{draft.body}\n\n---\n_Approved for publishing by @{job.requested_by}._"
        with publishing("github.publish", review_mode="approved_draft"):
            self._github.create_review(
                job.installation_id, job.owner, job.repo, job.pr_number, draft.head_sha, body, draft.comments
            )
        self._drafts.delete(key)
        self._resolve_draft(job, "approved", f"approved by @{job.requested_by}")
        logger.info("Published approved draft by=%s", job.requested_by)
        return "success"

    def _dismiss(self, job: ReviewJob) -> JobOutcome:
        self._drafts.delete(draft_key(job.owner, job.repo, job.pr_number))
        self._resolve_draft(job, "dismissed", f"dismissed by @{job.requested_by}")
        self._reply(job, f"AI review draft dismissed by @{job.requested_by}.")
        logger.info("Dismissed draft by=%s", job.requested_by)
        return "success"

    def _record(self, write: Callable[[ReviewHistory], None]) -> None:
        """History only feeds the dashboard: failing to write it must never fail or repeat a review."""
        if self._history is None:
            return
        try:
            write(self._history)
        except Exception:
            logger.exception("Could not record review history")

    def _resolve_draft(self, job: ReviewJob, status: Literal["approved", "dismissed"], note: str) -> None:
        self._record(lambda h: h.resolve_draft(job.owner, job.repo, job.pr_number, status, note))

    def _reply(self, job: ReviewJob, text: str) -> None:
        self._github.create_issue_comment(job.installation_id, job.owner, job.repo, job.pr_number, text)

    def _load_conventions(self, job: ReviewJob, repo: RepoReader) -> ConventionIndex | None:
        """Build the RAG index; a failure here degrades the review instead of blocking it."""
        if self._embeddings is None:
            return None
        try:
            comments = self._github.list_review_comments(
                job.installation_id, job.owner, job.repo, self._review_comments_limit
            )
            documents = guideline_documents(repo) + review_comment_documents(comments)
            return ConventionIndex.build(self._embeddings, documents)
        except Exception:
            logger.exception("Could not load conventions; reviewing without them")
            return None

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                job = self._queue.dequeue(timeout=POLL_TIMEOUT_SECONDS)
            except Exception:
                logger.exception("Failed to read from queue")
                self._stop.wait(QUEUE_ERROR_BACKOFF_SECONDS)
                continue
            if job is None:
                continue
            try:
                self.handle(job)
            finally:
                self._ack(job)

    def _ack(self, job: ReviewJob) -> None:
        try:
            self._queue.ack(job)
        except Exception:
            # The job will be delivered again; the stale-commit check keeps that harmless for PR events.
            logger.exception("Failed to acknowledge job delivery=%s", job.delivery_id)

    def stop(self) -> None:
        self._stop.set()
