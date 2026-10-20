"""Draft reviews waiting for a maintainer's approval (approval review mode)."""

from typing import Any, Protocol

import redis
from pydantic import BaseModel


class ReviewDraft(BaseModel):
    head_sha: str
    body: str
    comments: list[dict[str, Any]]


def draft_key(owner: str, repo: str, number: int) -> str:
    return f"draft:{owner}/{repo}#{number}"


class DraftStore(Protocol):
    def save(self, key: str, draft: ReviewDraft) -> None: ...

    def get(self, key: str) -> ReviewDraft | None: ...

    def delete(self, key: str) -> None: ...


class RedisDraftStore:
    def __init__(self, client: redis.Redis, ttl_seconds: int):
        self._client = client
        self._ttl_seconds = ttl_seconds

    def save(self, key: str, draft: ReviewDraft) -> None:
        self._client.set(key, draft.model_dump_json(), ex=self._ttl_seconds)

    def get(self, key: str) -> ReviewDraft | None:
        raw = self._client.get(key)
        return ReviewDraft.model_validate_json(raw) if raw else None

    def delete(self, key: str) -> None:
        self._client.delete(key)


class InMemoryDraftStore:
    def __init__(self):
        self.drafts: dict[str, ReviewDraft] = {}

    def save(self, key: str, draft: ReviewDraft) -> None:
        self.drafts[key] = draft

    def get(self, key: str) -> ReviewDraft | None:
        return self.drafts.get(key)

    def delete(self, key: str) -> None:
        self.drafts.pop(key, None)
