import requests
from fastapi.testclient import TestClient

from pr_reviewer.common.config import ReviewerSettings
from pr_reviewer.common.queue import InMemoryJobQueue
from pr_reviewer.reviewer.agent import ReviewAgent
from pr_reviewer.reviewer.drafts import InMemoryDraftStore
from pr_reviewer.reviewer.history import ReviewHistory
from pr_reviewer.reviewer.main import create_app
from pr_reviewer.reviewer.worker import ReviewWorker
from tests.fakes import ScriptedChatModel, finding, submit
from tests.test_worker import FakeGitHub, make_job


def history_worker(github, *responses, history=None, **options):
    agent = ReviewAgent(ScriptedChatModel(responses=list(responses or [submit()])))
    history = history or ReviewHistory()
    return ReviewWorker(InMemoryJobQueue(), github, agent, history=history, **options), history


def test_published_review_is_recorded_with_findings_and_tokens():
    worker, history = history_worker(FakeGitHub(), submit("Prints debug output.", [finding(line=2)], tokens=(100, 20)))

    worker.handle(make_job())

    record = history.get("d1")
    assert (record.status, record.head_sha, record.summary) == ("published", "abc123", "Prints debug output.")
    assert [f["line"] for f in record.findings] == [2]
    assert (record.input_tokens, record.output_tokens, record.llm_calls) == (100, 20, 1)


def test_stale_job_is_recorded_as_skipped():
    worker, history = history_worker(FakeGitHub(head_sha="newer"))

    worker.handle(make_job(head_sha="older"))

    record = history.get("d1")
    assert (record.status, record.note) == ("skipped", "a newer commit was pushed")


def test_retries_update_the_same_record_until_it_fails():
    github = FakeGitHub()

    def fail(*args):
        response = requests.Response()
        response.status_code = 502
        raise requests.HTTPError("502", response=response)

    github.get_pull_request = fail
    worker, history = history_worker(github, max_attempts=2, retry_base_seconds=10)

    worker.handle(make_job())
    assert (history.get("d1").status, history.get("d1").attempt) == ("retrying", 1)

    worker.handle(make_job().model_copy(update={"attempt": 2}))
    record = history.get("d1")
    assert (record.status, record.attempt, record.error) == ("failed", 2, "HTTPError: 502")
    assert len(history.list()) == 1


def test_approval_flow_moves_draft_from_awaiting_to_approved():
    github, drafts = FakeGitHub(), InMemoryDraftStore()
    worker, history = history_worker(github, review_mode="approval", drafts=drafts)

    worker.handle(make_job())
    assert history.get("d1").status == "awaiting_approval"

    worker.handle(make_job(head_sha=None, kind="approve", requested_by="maria").model_copy(update={"delivery_id": "d2"}))
    record = history.get("d1")
    assert (record.status, record.note) == ("approved", "approved by @maria")
    assert history.get("d2") is None  # commands act on the review, they aren't reviews themselves


def test_dismissed_draft_is_recorded():
    worker, history = history_worker(FakeGitHub(), review_mode="approval", drafts=InMemoryDraftStore())
    worker.handle(make_job())

    worker.handle(make_job(head_sha=None, kind="dismiss", requested_by="maria").model_copy(update={"delivery_id": "d2"}))

    assert history.get("d1").status == "dismissed"


def test_history_failure_does_not_fail_the_review():
    class BrokenHistory(ReviewHistory):
        def started(self, job):
            raise RuntimeError("disk full")

    github = FakeGitHub()
    worker, _ = history_worker(github, history=BrokenHistory())

    worker.handle(make_job())

    assert len(github.reviews) == 1


def test_api_lists_and_filters_reviews():
    worker, history = history_worker(FakeGitHub(), submit("ok", [finding(line=2)]))
    worker.handle(make_job())
    settings = ReviewerSettings(github_app_id="1", github_private_key="key", openai_api_key="sk-test", _env_file=None)
    # Without the context manager the lifespan doesn't run, so the worker thread never starts.
    client = TestClient(create_app(settings, worker=worker, history=history))

    [review] = client.get("/api/reviews").json()
    assert (review["delivery_id"], review["status"], review["findings"][0]["line"]) == ("d1", "published", 2)
    assert client.get("/api/reviews", params={"status": "failed"}).json() == []
    assert client.get("/api/reviews/d1").json()["summary"] == "ok"
    assert client.get("/api/reviews/missing").status_code == 404
    assert client.get("/api/stats").json() == {"published": 1}
