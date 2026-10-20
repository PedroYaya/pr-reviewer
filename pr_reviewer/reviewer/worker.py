"""Consumes review jobs from the queue and posts the results to GitHub."""

import logging
import threading

from langchain_core.embeddings import Embeddings

from pr_reviewer.common.github_client import GitHubAppClient
from pr_reviewer.common.models import ReviewJob
from pr_reviewer.common.queue import JobQueue
from pr_reviewer.reviewer.agent import ReviewAgent
from pr_reviewer.reviewer.budget import TokenBudget, select_files
from pr_reviewer.reviewer.conventions import guideline_documents, review_comment_documents
from pr_reviewer.reviewer.publisher import build_review
from pr_reviewer.reviewer.repo_tools import GitHubRepoReader
from pr_reviewer.reviewer.retrieval import ConventionIndex

logger = logging.getLogger(__name__)

POLL_TIMEOUT_SECONDS = 5
# Pause after a queue failure (e.g. Redis down) so the loop doesn't spin.
QUEUE_ERROR_BACKOFF_SECONDS = 2
DEFAULT_BUDGET = TokenBudget(diff_tokens=24_000, file_tokens=6_000)
DEFAULT_REVIEW_COMMENTS_LIMIT = 100


class ReviewWorker:
    def __init__(
        self,
        queue: JobQueue,
        github: GitHubAppClient,
        agent: ReviewAgent,
        embeddings: Embeddings | None = None,
        budget: TokenBudget = DEFAULT_BUDGET,
        review_comments_limit: int = DEFAULT_REVIEW_COMMENTS_LIMIT,
    ):
        self._queue = queue
        self._github = github
        self._agent = agent
        self._embeddings = embeddings
        self._budget = budget
        self._review_comments_limit = review_comments_limit
        self._stop = threading.Event()

    def process(self, job: ReviewJob) -> None:
        pr = self._github.get_pull_request(job.installation_id, job.owner, job.repo, job.pr_number)
        if pr["head"]["sha"] != job.head_sha:
            # A newer push already queued its own job; don't review stale code.
            logger.info("Skipping stale job delivery=%s", job.delivery_id)
            return

        files = self._github.list_pull_request_files(job.installation_id, job.owner, job.repo, job.pr_number)
        selection = select_files(files, self._budget)
        if not selection.files:
            logger.info("Nothing reviewable delivery=%s omitted=%d", job.delivery_id, len(selection.omitted))
            return

        repo = GitHubRepoReader(self._github, job.installation_id, job.owner, job.repo, job.head_sha)
        conventions = self._load_conventions(job, repo)
        run = self._agent.review(
            pr["title"], pr.get("body") or "", selection.files, repo, conventions=conventions, omitted=selection.omitted
        )
        body, comments = build_review(run.result, selection.files, selection.omitted)
        self._github.create_review(
            job.installation_id, job.owner, job.repo, job.pr_number, job.head_sha, body, comments
        )
        logger.info(
            "Posted review delivery=%s pr=%s/%s#%s findings=%d inline=%d omitted=%d "
            "input_tokens=%d output_tokens=%d llm_calls=%d tool_calls=%d",
            job.delivery_id, job.owner, job.repo, job.pr_number, len(run.result.findings), len(comments),
            len(selection.omitted), run.input_tokens, run.output_tokens, run.llm_calls, run.tool_calls,
        )

    def _load_conventions(self, job: ReviewJob, repo: GitHubRepoReader) -> ConventionIndex | None:
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
            logger.exception("Could not load conventions delivery=%s; reviewing without them", job.delivery_id)
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
                self.process(job)
            except Exception:
                logger.exception("Review failed delivery=%s", job.delivery_id)

    def stop(self) -> None:
        self._stop.set()
