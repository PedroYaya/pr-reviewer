"""Consumes review jobs from the queue and posts the results to GitHub."""

import logging
import threading

from pr_reviewer.common.github_client import GitHubAppClient
from pr_reviewer.common.models import ReviewJob
from pr_reviewer.common.queue import JobQueue
from pr_reviewer.reviewer.agent import ReviewAgent
from pr_reviewer.reviewer.publisher import build_review
from pr_reviewer.reviewer.repo_tools import GitHubRepoReader

logger = logging.getLogger(__name__)

POLL_TIMEOUT_SECONDS = 5
# Pause after a queue failure (e.g. Redis down) so the loop doesn't spin.
QUEUE_ERROR_BACKOFF_SECONDS = 2


class ReviewWorker:
    def __init__(self, queue: JobQueue, github: GitHubAppClient, agent: ReviewAgent):
        self._queue = queue
        self._github = github
        self._agent = agent
        self._stop = threading.Event()

    def process(self, job: ReviewJob) -> None:
        pr = self._github.get_pull_request(job.installation_id, job.owner, job.repo, job.pr_number)
        if pr["head"]["sha"] != job.head_sha:
            # A newer push already queued its own job; don't review stale code.
            logger.info("Skipping stale job delivery=%s", job.delivery_id)
            return

        files = self._github.list_pull_request_files(job.installation_id, job.owner, job.repo, job.pr_number)
        if not files:
            logger.info("No changed files delivery=%s", job.delivery_id)
            return

        repo = GitHubRepoReader(self._github, job.installation_id, job.owner, job.repo, job.head_sha)
        result = self._agent.review(pr["title"], pr.get("body") or "", files, repo)
        body, comments = build_review(result, files)
        self._github.create_review(
            job.installation_id, job.owner, job.repo, job.pr_number, job.head_sha, body, comments
        )
        logger.info(
            "Posted review delivery=%s pr=%s/%s#%s findings=%d inline=%d",
            job.delivery_id, job.owner, job.repo, job.pr_number, len(result.findings), len(comments),
        )

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
