from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from pr_reviewer.common.github_client import FILES_PAGE_SIZE, GitHubAppClient


@pytest.fixture(scope="module")
def private_key():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    ).decode()


class FakeResponse:
    def __init__(self, data):
        self._data = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._data


class FakeSession:
    def __init__(self, pages=None, expires_in=timedelta(hours=1)):
        self.pages = pages or [[]]
        self.expires_in = expires_in
        self.token_requests = []
        self.requests = []

    def post(self, url, **kwargs):
        self.token_requests.append(url)
        expires_at = datetime.now(timezone.utc) + self.expires_in
        return FakeResponse({"token": f"token-{len(self.token_requests)}", "expires_at": expires_at.isoformat()})

    def request(self, method, url, **kwargs):
        self.requests.append((method, url, kwargs))
        page = kwargs.get("params", {}).get("page", 1)
        return FakeResponse(self.pages[page - 1])


def test_caches_token_per_installation(private_key):
    session = FakeSession()
    client = GitHubAppClient("123", private_key, session=session)

    client.get_pull_request(1, "acme", "repo", 7)
    client.get_pull_request(1, "acme", "repo", 8)
    client.get_pull_request(2, "other", "repo", 1)

    assert len(session.token_requests) == 2
    auth_headers = [kwargs["headers"]["Authorization"] for _, _, kwargs in session.requests]
    assert auth_headers == ["Bearer token-1", "Bearer token-1", "Bearer token-2"]


def test_refreshes_token_close_to_expiry(private_key):
    session = FakeSession(expires_in=timedelta(seconds=30))
    client = GitHubAppClient("123", private_key, session=session)

    client.get_pull_request(1, "acme", "repo", 7)
    client.get_pull_request(1, "acme", "repo", 7)

    assert len(session.token_requests) == 2


def test_lists_files_across_pages(private_key):
    full_page = [{"filename": f"f{i}.py"} for i in range(FILES_PAGE_SIZE)]
    session = FakeSession(pages=[full_page, [{"filename": "last.py"}]])
    client = GitHubAppClient("123", private_key, session=session)

    files = client.list_pull_request_files(1, "acme", "repo", 7)

    assert len(files) == FILES_PAGE_SIZE + 1
    assert files[-1]["filename"] == "last.py"
