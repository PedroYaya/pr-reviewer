"""Job queue used to hand review work from the gateway to the reviewer.

Failed jobs are retried later and, once they run out of attempts, moved to a
dead-letter queue so they can be inspected and replayed. Redis is used locally;
on AWS the queue is SQS, which also redelivers a job whose worker died mid-review.
"""

import heapq
import json
import time
from collections import deque
from typing import Any, Protocol

import redis

from pr_reviewer.common.config import QueueSettings
from pr_reviewer.common.models import ReviewJob

# Due retries moved back to the main queue per dequeue call.
PROMOTE_BATCH = 50


class JobQueue(Protocol):
    def enqueue(self, job: ReviewJob) -> None: ...

    def dequeue(self, timeout: int) -> ReviewJob | None: ...

    def schedule(self, job: ReviewJob, delay_seconds: float) -> None: ...

    def dead_letter(self, job: ReviewJob, error: str) -> None: ...

    def ack(self, job: ReviewJob) -> None:
        """Mark a dequeued job as handled (done, rescheduled or dead-lettered)."""
        ...


def parse_job(raw: str | bytes) -> ReviewJob:
    """Read a queued job, including a dead-letter entry moved back for replay."""
    data = json.loads(raw)
    if "job" in data and "error" in data:
        data = data["job"]
    return ReviewJob.model_validate(data)


def build_queue(settings: QueueSettings) -> "RedisJobQueue | SqsJobQueue":
    if settings.queue_backend == "sqs":
        return SqsJobQueue.from_settings(settings)
    return RedisJobQueue.from_url(settings.redis_url, settings.review_queue_name)


class RedisJobQueue:
    """BRPOP removes the job immediately, so a worker crash mid-review loses it."""

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
        try:
            item = self._client.brpop([self._name], timeout=timeout)
        except redis.TimeoutError:
            # redis-py 8 raises instead of returning None when BRPOP times out on an empty queue.
            return None
        if item is None:
            return None
        _, raw = item
        return parse_job(raw)

    def schedule(self, job: ReviewJob, delay_seconds: float) -> None:
        self._client.zadd(self._delayed, {job.model_dump_json(): time.time() + delay_seconds})

    def dead_letter(self, job: ReviewJob, error: str) -> None:
        entry = {"job": job.model_dump(mode="json"), "error": error, "failed_at": time.time()}
        self._client.lpush(self._dead, json.dumps(entry))

    def ack(self, job: ReviewJob) -> None:
        pass

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

    def ack(self, job: ReviewJob) -> None:
        pass

    @property
    def scheduled(self) -> list[ReviewJob]:
        return [job for _, _, job in sorted(self._delayed)]

    def __len__(self) -> int:
        return len(self._items)


class SqsJobQueue:
    """Amazon SQS queue with at-least-once delivery.

    A received job stays invisible for the queue's visibility timeout and is
    deleted only on ``ack``. If the worker dies first, SQS delivers it again,
    and after the redrive policy's ``maxReceiveCount`` moves it to the DLQ.
    Retries are new messages with ``DelaySeconds`` (SQS caps it at 15 minutes).
    """

    MAX_DELAY_SECONDS = 900
    MAX_WAIT_SECONDS = 20

    def __init__(self, client: Any, queue_url: str, dead_letter_url: str):
        self._client = client
        self._url = queue_url
        self._dead_url = dead_letter_url

    @classmethod
    def from_settings(cls, settings: QueueSettings) -> "SqsJobQueue":
        import boto3  # optional dependency: the "aws" extra

        if not settings.sqs_queue_url or not settings.sqs_dead_letter_queue_url:
            raise ValueError("QUEUE_BACKEND=sqs needs SQS_QUEUE_URL and SQS_DEAD_LETTER_QUEUE_URL")
        client = boto3.client("sqs", region_name=settings.aws_region)
        return cls(client, settings.sqs_queue_url, settings.sqs_dead_letter_queue_url)

    def enqueue(self, job: ReviewJob) -> None:
        self._client.send_message(QueueUrl=self._url, MessageBody=job.model_dump_json())

    def dequeue(self, timeout: int) -> ReviewJob | None:
        response = self._client.receive_message(
            QueueUrl=self._url, MaxNumberOfMessages=1, WaitTimeSeconds=min(timeout, self.MAX_WAIT_SECONDS)
        )
        messages = response.get("Messages", [])
        if not messages:
            return None
        job = parse_job(messages[0]["Body"])
        job._receipt_handle = messages[0]["ReceiptHandle"]
        return job

    def schedule(self, job: ReviewJob, delay_seconds: float) -> None:
        self._client.send_message(
            QueueUrl=self._url,
            MessageBody=job.model_dump_json(),
            DelaySeconds=min(int(delay_seconds), self.MAX_DELAY_SECONDS),
        )

    def dead_letter(self, job: ReviewJob, error: str) -> None:
        entry = {"job": job.model_dump(mode="json"), "error": error, "failed_at": time.time()}
        self._client.send_message(QueueUrl=self._dead_url, MessageBody=json.dumps(entry))

    def ack(self, job: ReviewJob) -> None:
        if job._receipt_handle:
            self._client.delete_message(QueueUrl=self._url, ReceiptHandle=job._receipt_handle)

    def ping(self) -> bool:
        self._client.get_queue_attributes(QueueUrl=self._url, AttributeNames=["ApproximateNumberOfMessages"])
        return True
