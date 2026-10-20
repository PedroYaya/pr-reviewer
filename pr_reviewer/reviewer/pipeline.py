"""The review pipeline, independent of GitHub and the queue.

The worker runs it for real PRs and the eval suite runs it on fixed cases, so
both measure exactly the same behaviour. Options let the evals switch features
off to compare against a baseline.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from pr_reviewer.common.tracing import tracer
from pr_reviewer.reviewer.agent import ReviewAgent, ReviewRun
from pr_reviewer.reviewer.budget import DiffSelection, OmittedFile, TokenBudget, select_files
from pr_reviewer.reviewer.guardrails import (
    DroppedFinding,
    RedactingRepoReader,
    SecretHit,
    apply_output_guardrails,
    redact_files,
    secret_findings,
)
from pr_reviewer.reviewer.repo_tools import RepoReader
from pr_reviewer.reviewer.retrieval import ConventionIndex
from pr_reviewer.reviewer.schemas import ReviewResult

ConventionsLoader = Callable[[RepoReader], ConventionIndex | None]
# Effectively unlimited, for the baseline variant.
NO_LIMIT = 10**9


@dataclass(frozen=True)
class PipelineOptions:
    budget: TokenBudget = TokenBudget(diff_tokens=24_000, file_tokens=6_000)
    filter_files: bool = True
    use_conventions: bool = True
    output_guardrails: bool = True
    max_findings: int = 15

    @classmethod
    def baseline(cls) -> "PipelineOptions":
        """Every diff in full, no RAG, no output filtering: close to the original single-prompt reviewer."""
        return cls(
            budget=TokenBudget(diff_tokens=NO_LIMIT, file_tokens=NO_LIMIT),
            filter_files=False,
            use_conventions=False,
            output_guardrails=False,
            max_findings=NO_LIMIT,
        )


@dataclass
class PipelineOutput:
    result: ReviewResult
    run: ReviewRun
    files: list[dict[str, Any]]
    omitted: list[OmittedFile]
    dropped: list[DroppedFinding] = field(default_factory=list)
    secret_hits: list[SecretHit] = field(default_factory=list)


def _select(files: list[dict[str, Any]], options: PipelineOptions) -> DiffSelection:
    if options.filter_files:
        return select_files(files, options.budget)
    return DiffSelection(files=[{**f, "truncated": False} for f in files if f.get("patch")], omitted=[])


def run_review_pipeline(
    agent: ReviewAgent,
    title: str,
    description: str,
    files: list[dict[str, Any]],
    repo: RepoReader,
    options: PipelineOptions = PipelineOptions(),
    load_conventions: ConventionsLoader | None = None,
) -> PipelineOutput | None:
    """Review the PR; returns None when no file is worth sending to the LLM."""
    selection = _select(files, options)
    if not selection.files:
        return None

    # Input guardrail: the LLM only ever sees redacted diffs and files.
    llm_files, secret_hits = redact_files(selection.files)
    safe_repo = RedactingRepoReader(repo)
    conventions = None
    if load_conventions and options.use_conventions:
        with tracer.start_as_current_span("conventions.load"):
            conventions = load_conventions(safe_repo)

    with tracer.start_as_current_span(
        "agent.review", attributes={"review.files": len(llm_files), "review.omitted": len(selection.omitted)}
    ) as span:
        run = agent.review(title, description, llm_files, safe_repo, conventions=conventions, omitted=selection.omitted)
        span.set_attribute("review.findings", len(run.result.findings))

    findings = secret_findings(secret_hits) + run.result.findings
    dropped: list[DroppedFinding] = []
    if options.output_guardrails:
        findings, dropped = apply_output_guardrails(findings, llm_files, options.max_findings)
    result = run.result.model_copy(update={"findings": findings})
    return PipelineOutput(result, run, llm_files, selection.omitted, dropped, secret_hits)
