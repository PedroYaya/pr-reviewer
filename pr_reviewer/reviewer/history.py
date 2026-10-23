"""Review history in SQLite, read by the dashboard API.

GitHub only ever sees the published review. This records what it never sees:
jobs in progress, retries and failures, token use and the findings the
guardrails dropped. The reviewer service is the only writer, so a single
SQLite file is enough; any SQLAlchemy URL (e.g. Postgres) works the same.
"""

import time
from typing import Any, Literal

from sqlalchemy import JSON, Column, func
from sqlalchemy.pool import StaticPool
from sqlmodel import Field, Session, SQLModel, create_engine, select

from pr_reviewer.common.models import ReviewJob
from pr_reviewer.reviewer.pipeline import PipelineOutput

ReviewStatus = Literal[
    "reviewing", "retrying", "failed", "skipped", "published", "awaiting_approval", "approved", "dismissed"
]


class ReviewRecord(SQLModel, table=True):
    """One review job, keyed by the GitHub delivery that triggered it; retries update the same row."""

    __tablename__ = "reviews"

    delivery_id: str = Field(primary_key=True)
    owner: str
    repo: str
    pr_number: int = Field(index=True)
    head_sha: str | None = None
    status: str = Field(index=True)
    attempt: int = 1
    summary: str | None = None
    findings: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    dropped_findings: int = 0
    secrets_redacted: int = 0
    omitted_files: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    # Skip reason, who approved or dismissed a draft, …
    note: str | None = None
    error: str | None = None
    enqueued_at: float
    updated_at: float = Field(index=True)


class ReviewHistory:
    def __init__(self, url: str = "sqlite://"):
        # The worker thread writes while API requests read from FastAPI's threadpool.
        options: dict[str, Any] = {"connect_args": {"check_same_thread": False}} if url.startswith("sqlite") else {}
        if url == "sqlite://":
            options["poolclass"] = StaticPool  # one shared connection, or each thread gets its own empty database
        self._engine = create_engine(url, **options)
        SQLModel.metadata.create_all(self._engine)

    def started(self, job: ReviewJob) -> None:
        with Session(self._engine) as session:
            record = session.get(ReviewRecord, job.delivery_id) or ReviewRecord(
                delivery_id=job.delivery_id, owner=job.owner, repo=job.repo, pr_number=job.pr_number,
                status="reviewing", enqueued_at=job.enqueued_at, updated_at=time.time(),
            )
            record.head_sha = job.head_sha or record.head_sha
            record.status = "reviewing"
            record.attempt = job.attempt
            record.error = None
            record.updated_at = time.time()
            session.add(record)
            session.commit()

    def finished(
        self,
        job: ReviewJob,
        status: ReviewStatus,
        output: PipelineOutput | None = None,
        head_sha: str | None = None,
        note: str | None = None,
    ) -> None:
        updates: dict[str, Any] = {"status": status, "note": note}
        if head_sha:
            updates["head_sha"] = head_sha
        if output is not None:
            updates.update(
                summary=output.result.summary,
                findings=[f.model_dump() for f in output.result.findings],
                dropped_findings=len(output.dropped),
                secrets_redacted=len(output.secret_hits),
                omitted_files=len(output.omitted),
                input_tokens=output.run.input_tokens,
                output_tokens=output.run.output_tokens,
                llm_calls=output.run.llm_calls,
                tool_calls=output.run.tool_calls,
            )
        self._update(job.delivery_id, **updates)

    def failed(self, job: ReviewJob, status: Literal["retrying", "failed"], error: str) -> None:
        self._update(job.delivery_id, status=status, error=error)

    def resolve_draft(self, owner: str, repo: str, pr_number: int, status: Literal["approved", "dismissed"], note: str) -> None:
        """Close the PR's draft waiting for approval, if there is one."""
        with Session(self._engine) as session:
            record = session.exec(
                select(ReviewRecord)
                .where(ReviewRecord.owner == owner, ReviewRecord.repo == repo, ReviewRecord.pr_number == pr_number)
                .where(ReviewRecord.status == "awaiting_approval")
                .order_by(ReviewRecord.updated_at.desc())
            ).first()
            if record is not None:
                self._apply(session, record, status=status, note=note)

    def list(self, status: str | None = None, limit: int = 50) -> list[ReviewRecord]:
        with Session(self._engine) as session:
            query = select(ReviewRecord).order_by(ReviewRecord.updated_at.desc()).limit(limit)
            if status:
                query = query.where(ReviewRecord.status == status)
            return list(session.exec(query))

    def get(self, delivery_id: str) -> ReviewRecord | None:
        with Session(self._engine) as session:
            return session.get(ReviewRecord, delivery_id)

    def counts(self) -> dict[str, int]:
        with Session(self._engine) as session:
            rows = session.exec(select(ReviewRecord.status, func.count()).group_by(ReviewRecord.status))
            return dict(rows.all())

    def _update(self, delivery_id: str, **fields: Any) -> None:
        with Session(self._engine) as session:
            record = session.get(ReviewRecord, delivery_id)
            if record is not None:
                self._apply(session, record, **fields)

    @staticmethod
    def _apply(session: Session, record: ReviewRecord, **fields: Any) -> None:
        for name, value in fields.items():
            setattr(record, name, value)
        record.updated_at = time.time()
        session.add(record)
        session.commit()
