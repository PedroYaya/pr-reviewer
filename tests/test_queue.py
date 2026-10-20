from pr_reviewer.common.models import ReviewJob
from pr_reviewer.common.queue import InMemoryJobQueue


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
