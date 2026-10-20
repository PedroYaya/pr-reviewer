import hashlib
import hmac
import json

import pytest
from fastapi.testclient import TestClient

from pr_reviewer.common.config import GatewaySettings
from pr_reviewer.common.queue import InMemoryJobQueue
from pr_reviewer.gateway.main import create_app

SECRET = "test-secret"


def pr_payload(action="opened", draft=False):
    return {
        "action": action,
        "pull_request": {"number": 7, "draft": draft, "head": {"sha": "abc123"}},
        "repository": {"name": "repo", "owner": {"login": "acme"}},
        "installation": {"id": 42},
    }


def signed_headers(body: bytes, event="pull_request", secret=SECRET):
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return {
        "X-GitHub-Event": event,
        "X-GitHub-Delivery": "delivery-1",
        "X-Hub-Signature-256": f"sha256={digest}",
        "Content-Type": "application/json",
    }


@pytest.fixture
def queue():
    return InMemoryJobQueue()


@pytest.fixture
def client(queue):
    settings = GatewaySettings(github_webhook_secret=SECRET, _env_file=None)
    return TestClient(create_app(settings, queue))


def post(client, payload, event="pull_request", secret=SECRET):
    body = json.dumps(payload).encode()
    return client.post("/webhook", content=body, headers=signed_headers(body, event, secret))


def test_queues_opened_pull_request(client, queue):
    response = post(client, pr_payload())

    assert response.status_code == 202
    job = queue.dequeue(timeout=0)
    assert (job.owner, job.repo, job.pr_number, job.installation_id) == ("acme", "repo", 7, 42)
    assert job.head_sha == "abc123"
    assert job.delivery_id == "delivery-1"


def test_rejects_bad_signature(client, queue):
    response = post(client, pr_payload(), secret="wrong")

    assert response.status_code == 401
    assert len(queue) == 0


def test_rejects_missing_signature(client, queue):
    body = json.dumps(pr_payload()).encode()
    headers = signed_headers(body)
    del headers["X-Hub-Signature-256"]

    assert client.post("/webhook", content=body, headers=headers).status_code == 401
    assert len(queue) == 0


@pytest.mark.parametrize("payload", [pr_payload(action="closed"), pr_payload(draft=True)])
def test_ignores_non_reviewable_pull_requests(client, queue, payload):
    response = post(client, payload)

    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert len(queue) == 0


def test_ping(client):
    response = post(client, {"zen": "hi"}, event="ping")

    assert response.status_code == 200
    assert response.json() == {"status": "pong"}


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def comment_payload(body="/ai-review", association="MEMBER", user_type="User", action="created", on_pr=True):
    issue = {"number": 7, **({"pull_request": {"url": "..."}} if on_pr else {})}
    return {
        "action": action,
        "issue": issue,
        "comment": {"body": body, "author_association": association, "user": {"login": "maria", "type": user_type}},
        "repository": {"name": "repo", "owner": {"login": "acme"}},
        "installation": {"id": 42},
    }


@pytest.mark.parametrize(
    "body, kind",
    [("/ai-review", "review"), ("/ai-review approve", "approve"), ("/AI-review Dismiss\nthanks", "dismiss")],
)
def test_queues_commands_from_trusted_users(client, queue, body, kind):
    response = post(client, comment_payload(body), event="issue_comment")

    assert response.status_code == 202
    job = queue.dequeue(timeout=0)
    assert (job.kind, job.pr_number, job.head_sha, job.requested_by) == (kind, 7, None, "maria")


@pytest.mark.parametrize(
    "payload",
    [
        comment_payload(association="CONTRIBUTOR"),
        comment_payload(association="NONE"),
        comment_payload(user_type="Bot"),
        comment_payload(body="please /ai-review approve"),
        comment_payload(body="/ai-review merge"),
        comment_payload(action="edited"),
        comment_payload(on_pr=False),
        comment_payload(body=""),
    ],
)
def test_ignores_other_comments(client, queue, payload):
    response = post(client, payload, event="issue_comment")

    assert response.json()["status"] == "ignored"
    assert len(queue) == 0
