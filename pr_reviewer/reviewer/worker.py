"""Consumes review jobs from the queue and posts the results to GitHub."""

import logging
import threading
from typing import Any, Literal

from langchain_core.embeddings import Embeddings

from pr_reviewer.common.github_client import GitHubAppClient
from pr_reviewer.common.models import ReviewJob
from pr_reviewer.common.queue import JobQueue
from pr_reviewer.reviewer.agent import ReviewAgent
from pr_reviewer.reviewer.budget import TokenBudget
from pr_reviewer.reviewer.conventions import guideline_documents, review_comment_documents
from pr_reviewer.reviewer.drafts import DraftStore, InMemoryDraftStore, ReviewDraft, draft_key
from pr_reviewer.reviewer.pipeline import PipelineOptions, run_review_pipeline
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

ReviewMode = Literal["auto", "approval"]


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
    ):
        self._queue = queue
        self._github = github
        self._agent = agent
        self._embeddings = embeddings
        self._review_comments_limit = review_comments_limit
        self._review_mode = review_mode
        self._options = PipelineOptions(budget=budget, max_findings=max_findings)
        self._drafts = drafts if drafts is not None else InMemoryDraftStore()
        self._stop = threading.Event()

    def process(self, job: ReviewJob) -> None:
        pr = self._github.get_pull_request(job.installation_id, job.owner, job.repo, job.pr_number)
        if job.kind == "approve":
            self._approve(job, pr)
        elif job.kind == "dismiss":
            self._dismiss(job)
        else:
            self._review(job, pr)

    def _review(self, job: ReviewJob, pr: dict[str, Any]) -> None:
        head_sha = pr["head"]["sha"]
        if job.head_sha and job.head_sha != head_sha:
            # A newer push already queued its own job; don't review stale code.
            logger.info("Skipping stale job delivery=%s", job.delivery_id)
            return

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
            logger.info("Nothing reviewable delivery=%s files=%d", job.delivery_id, len(files))
            return

        body, comments = build_review(output.result, output.files, output.omitted)
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

        run = output.run
        logger.info(
            "Review %s delivery=%s pr=%s/%s#%s findings=%d inline=%d dropped=%d secrets=%d omitted=%d "
            "input_tokens=%d output_tokens=%d llm_calls=%d tool_calls=%d",
            "drafted" if self._review_mode == "approval" else "posted",
            job.delivery_id, job.owner, job.repo, job.pr_number, len(output.result.findings), len(comments),
            len(output.dropped), len(output.secret_hits), len(output.omitted), run.input_tokens,
            run.output_tokens, run.llm_calls, run.tool_calls,
        )
        for item in output.dropped:
            logger.info(
                "Guardrail dropped finding delivery=%s reason=%s location=%s:%s",
                job.delivery_id, item.reason, item.finding.path, item.finding.line,
            )

    def _approve(self, job: ReviewJob, pr: dict[str, Any]) -> None:
        key = draft_key(job.owner, job.repo, job.pr_number)
        draft = self._drafts.get(key)
        if draft is None:
            self._reply(job, "There is no AI review draft waiting for approval on this PR. Comment `/ai-review` to create one.")
            return
        if draft.head_sha != pr["head"]["sha"]:
            self._drafts.delete(key)
            self._reply(
                job,
                f"The draft was for `{draft.head_sha[:7]}`, but the PR has new commits since. "
                "Comment `/ai-review` to review the latest changes.",
            )
            return

        body = f"{draft.body}\n\n---\n_Approved for publishing by @{job.requested_by}._"
        self._github.create_review(
            job.installation_id, job.owner, job.repo, job.pr_number, draft.head_sha, body, draft.comments
        )
        self._drafts.delete(key)
        logger.info("Published approved draft delivery=%s by=%s", job.delivery_id, job.requested_by)

    def _dismiss(self, job: ReviewJob) -> None:
        self._drafts.delete(draft_key(job.owner, job.repo, job.pr_number))
        self._reply(job, f"AI review draft dismissed by @{job.requested_by}.")
        logger.info("Dismissed draft delivery=%s by=%s", job.delivery_id, job.requested_by)

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
