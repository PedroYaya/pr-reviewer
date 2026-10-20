"""Job queue used to hand review work from the gateway to the reviewer."""

from collections import deque
from typing import Protocol

import redis

from pr_reviewer.common.models import ReviewJob


class JobQueue(Protocol):
    def enqueue(self, job: ReviewJob) -> None: ...

    def dequeue(self, timeout: int) -> ReviewJob | None: ...


class RedisJobQueue:
    def __init__(self, client: redis.Redis, name: str):
        self._client = client
        self._name = name

    @classmethod
    def from_url(cls, url: str, name: str) -> "RedisJobQueue":
        return cls(redis.Redis.from_url(url), name)

    def enqueue(self, job: ReviewJob) -> None:
        self._client.lpush(self._name, job.model_dump_json())

    def dequeue(self, timeout: int) -> ReviewJob | None:
        item = self._client.brpop([self._name], timeout=timeout)
        if item is None:
            return None
        _, raw = item
        return ReviewJob.model_validate_json(raw)

    def ping(self) -> bool:
        return bool(self._client.ping())


class InMemoryJobQueue:
    """Single-process queue for tests and local experiments."""

    def __init__(self):
        self._items: deque[ReviewJob] = deque()

    def enqueue(self, job: ReviewJob) -> None:
        self._items.appendleft(job)

    def dequeue(self, timeout: int) -> ReviewJob | None:
        return self._items.pop() if self._items else None

    def __len__(self) -> int:
        return len(self._items)
