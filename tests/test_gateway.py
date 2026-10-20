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
