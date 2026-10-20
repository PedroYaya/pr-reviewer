"""Job queue used to hand review work from the gateway to the reviewer.

Failed jobs are retried later through a delayed set and, once they run out of
attempts, moved to a dead-letter list so they can be inspected and replayed.
"""

import heapq
import json
import time
from collections import deque
from typing import Protocol

import redis

from pr_reviewer.common.models import ReviewJob

# Due retries moved back to the main queue per dequeue call.
PROMOTE_BATCH = 50


class JobQueue(Protocol):
    def enqueue(self, job: ReviewJob) -> None: ...

    def dequeue(self, timeout: int) -> ReviewJob | None: ...

    def schedule(self, job: ReviewJob, delay_seconds: float) -> None: ...

    def dead_letter(self, job: ReviewJob, error: str) -> None: ...


class RedisJobQueue:
    def __init__(self, client: redis.Redis, name: str):
        self._client = client
        self._name = name
        self._delayed = f"{name}:delayed"
        self._dead = f"{name}:dead"

    @classmethod
    def from_url(cls, url: str, name: str) -> "RedisJobQueue":
        return cls(redis.Redis.from_url(url), name)

    def enqueue(self, job: ReviewJob) -> None:
        self._client.lpush(self._name, job.model_dump_json())

    def dequeue(self, timeout: int) -> ReviewJob | None:
        self._promote_due()
        item = self._client.brpop([self._name], timeout=timeout)
        if item is None:
            return None
        _, raw = item
        return ReviewJob.model_validate_json(raw)

    def schedule(self, job: ReviewJob, delay_seconds: float) -> None:
        self._client.zadd(self._delayed, {job.model_dump_json(): time.time() + delay_seconds})

    def dead_letter(self, job: ReviewJob, error: str) -> None:
        entry = {"job": job.model_dump(mode="json"), "error": error, "failed_at": time.time()}
        self._client.lpush(self._dead, json.dumps(entry))

    def _promote_due(self) -> None:
        for raw in self._client.zrangebyscore(self._delayed, "-inf", time.time(), start=0, num=PROMOTE_BATCH):
            # ZREM returns 1 only for the worker that removed it, so each retry is queued once.
            if self._client.zrem(self._delayed, raw):
                self._client.lpush(self._name, raw)

    def ping(self) -> bool:
        return bool(self._client.ping())


class InMemoryJobQueue:
    """Single-process queue for tests and local experiments."""

    def __init__(self, clock=time.monotonic):
        self._items: deque[ReviewJob] = deque()
        self._delayed: list[tuple[float, int, ReviewJob]] = []
        self.dead: list[tuple[ReviewJob, str]] = []
        self._clock = clock
        self._seq = 0

    def enqueue(self, job: ReviewJob) -> None:
        self._items.appendleft(job)

    def dequeue(self, timeout: int) -> ReviewJob | None:
        while self._delayed and self._delayed[0][0] <= self._clock():
            self.enqueue(heapq.heappop(self._delayed)[2])
        return self._items.pop() if self._items else None

    def schedule(self, job: ReviewJob, delay_seconds: float) -> None:
        self._seq += 1
        heapq.heappush(self._delayed, (self._clock() + delay_seconds, self._seq, job))

    def dead_letter(self, job: ReviewJob, error: str) -> None:
        self.dead.append((job, error))

    @property
    def scheduled(self) -> list[ReviewJob]:
        return [job for _, _, job in sorted(self._delayed)]

    def __len__(self) -> int:
        return len(self._items)
