"""GitHub REST client that authenticates as a GitHub App installation."""

import time
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
import requests

API_URL = "https://api.github.com"
FILES_PAGE_SIZE = 100
# Refresh installation tokens slightly before GitHub expires them.
TOKEN_EXPIRY_MARGIN = timedelta(minutes=1)


class GitHubAppClient:
    def __init__(
        self,
        app_id: str,
        private_key: str,
        session: requests.Session | None = None,
        timeout: float = 10.0,
    ):
        self._app_id = app_id
        self._private_key = private_key
        self._session = session or requests.Session()
        self._timeout = timeout
        self._tokens: dict[int, tuple[str, datetime]] = {}

    def _app_jwt(self) -> str:
        now = int(time.time())
        # Backdate iat to tolerate clock drift; GitHub caps exp at 10 minutes.
        payload = {"iat": now - 60, "exp": now + 9 * 60, "iss": self._app_id}
        return jwt.encode(payload, self._private_key, algorithm="RS256")

    def _installation_token(self, installation_id: int) -> str:
        cached = self._tokens.get(installation_id)
        if cached and cached[1] - TOKEN_EXPIRY_MARGIN > datetime.now(timezone.utc):
            return cached[0]

        response = self._session.post(
            f"{API_URL}/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {self._app_jwt()}",
                "Accept": "application/vnd.github+json",
            },
            timeout=self._timeout,
        )
        response.raise_for_status()
        data = response.json()
        expires_at = datetime.fromisoformat(data["expires_at"].replace("Z", "+00:00"))
        self._tokens[installation_id] = (data["token"], expires_at)
        return data["token"]

    def _request(self, method: str, installation_id: int, path: str, **kwargs: Any) -> requests.Response:
        response = self._session.request(
            method,
            f"{API_URL}{path}",
            headers={
                "Authorization": f"Bearer {self._installation_token(installation_id)}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=self._timeout,
            **kwargs,
        )
        response.raise_for_status()
        return response

    def get_pull_request(self, installation_id: int, owner: str, repo: str, number: int) -> dict[str, Any]:
        return self._request("GET", installation_id, f"/repos/{owner}/{repo}/pulls/{number}").json()

    def list_pull_request_files(self, installation_id: int, owner: str, repo: str, number: int) -> list[dict[str, Any]]:
        files: list[dict[str, Any]] = []
        page = 1
        while True:
            batch = self._request(
                "GET",
                installation_id,
                f"/repos/{owner}/{repo}/pulls/{number}/files",
                params={"per_page": FILES_PAGE_SIZE, "page": page},
            ).json()
            files.extend(batch)
            if len(batch) < FILES_PAGE_SIZE:
                return files
            page += 1

    def create_issue_comment(self, installation_id: int, owner: str, repo: str, number: int, body: str) -> dict[str, Any]:
        return self._request(
            "POST",
            installation_id,
            f"/repos/{owner}/{repo}/issues/{number}/comments",
            json={"body": body},
        ).json()
