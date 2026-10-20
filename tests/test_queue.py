import json

import pytest
import redis

from pr_reviewer.common.config import QueueSettings
from pr_reviewer.common.models import ReviewJob
from pr_reviewer.common.queue import InMemoryJobQueue, RedisJobQueue, SqsJobQueue, build_queue


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def make_job(delivery_id="d1"):
    return ReviewJob(delivery_id=delivery_id, installation_id=1, owner="acme", repo="repo", pr_number=7, head_sha="abc", action="opened")


def test_scheduled_job_is_delivered_only_when_due():
    clock = Clock()
    queue = InMemoryJobQueue(clock=clock)
    queue.schedule(make_job(), delay_seconds=30)

    assert queue.dequeue(timeout=0) is None
    clock.now = 30
    assert queue.dequeue(timeout=0).delivery_id == "d1"


def test_dead_letter_keeps_job_and_error():
    queue = InMemoryJobQueue()
    queue.dead_letter(make_job(), "HTTPError: 404")

    assert [(job.delivery_id, error) for job, error in queue.dead] == [("d1", "HTTPError: 404")]


class FakeSqs:
    """Records SQS calls; receive_message returns the queued messages one at a time."""

    def __init__(self):
        self.sent = []
        self.deleted = []
        self.inbox = []

    def send_message(self, **kwargs):
        self.sent.append(kwargs)

    def receive_message(self, **kwargs):
        assert kwargs["WaitTimeSeconds"] <= 20
        return {"Messages": [self.inbox.pop(0)]} if self.inbox else {}

    def delete_message(self, **kwargs):
        self.deleted.append(kwargs)


def test_sqs_job_is_deleted_only_on_ack():
    sqs = FakeSqs()
    queue = SqsJobQueue(sqs, "https://sqs/main", "https://sqs/dead")
    sqs.inbox.append({"Body": make_job().model_dump_json(), "ReceiptHandle": "rh-1"})

    job = queue.dequeue(timeout=30)
    assert job.delivery_id == "d1"
    assert sqs.deleted == []

    queue.ack(job)
    assert sqs.deleted == [{"QueueUrl": "https://sqs/main", "ReceiptHandle": "rh-1"}]


def test_sqs_retry_is_delayed_message_capped_at_15_minutes():
    sqs = FakeSqs()
    SqsJobQueue(sqs, "https://sqs/main", "https://sqs/dead").schedule(make_job(), delay_seconds=1800)

    [message] = sqs.sent
    assert (message["QueueUrl"], message["DelaySeconds"]) == ("https://sqs/main", 900)
    assert "_receipt_handle" not in message["MessageBody"]


def test_sqs_dead_letter_goes_to_dlq_with_error():
    sqs = FakeSqs()
    SqsJobQueue(sqs, "https://sqs/main", "https://sqs/dead").dead_letter(make_job(), "boom")

    [message] = sqs.sent
    assert message["QueueUrl"] == "https://sqs/dead"
    assert json.loads(message["MessageBody"])["error"] == "boom"


def test_sqs_backend_requires_queue_urls():
    with pytest.raises(ValueError):
        build_queue(QueueSettings(queue_backend="sqs", _env_file=None))


def test_dead_letter_entry_moved_back_is_read_as_its_job():
    sqs = FakeSqs()
    queue = SqsJobQueue(sqs, "https://sqs/main", "https://sqs/dead")
    queue.dead_letter(make_job(), "boom")
    sqs.inbox.append({"Body": sqs.sent[0]["MessageBody"], "ReceiptHandle": "rh-2"})  # start-message-move-task

    assert queue.dequeue(timeout=1).delivery_id == "d1"


def test_redis_empty_poll_returns_none_when_client_times_out():
    class TimingOutRedis:
        def zrangebyscore(self, *args, **kwargs):
            return []

        def brpop(self, keys, timeout):
            raise redis.TimeoutError("Timeout reading from socket")

    assert RedisJobQueue(TimingOutRedis(), "q").dequeue(timeout=5) is None
