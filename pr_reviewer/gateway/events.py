"""Turn GitHub webhook payloads into review jobs."""

import re
from typing import Any

from pr_reviewer.common.models import JobKind, ReviewJob

REVIEWABLE_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}
# Only people with write-level ties to the repo may spend LLM budget or publish drafts.
TRUSTED_ASSOCIATIONS = {"OWNER", "MEMBER", "COLLABORATOR"}
COMMAND = re.compile(r"^/ai-review(?:\s+(approve|dismiss))?\s*$", re.IGNORECASE)


def job_from_pull_request_event(payload: dict[str, Any], delivery_id: str) -> ReviewJob | None:
    """Return a job for PR events worth reviewing, or None to ignore the event."""
    action = payload.get("action")
    pull_request = payload.get("pull_request") or {}
    if action not in REVIEWABLE_ACTIONS or pull_request.get("draft"):
        return None

    repository = payload["repository"]
    return ReviewJob(
        delivery_id=delivery_id,
        installation_id=payload["installation"]["id"],
        owner=repository["owner"]["login"],
        repo=repository["name"],
        pr_number=pull_request["number"],
        head_sha=pull_request["head"]["sha"],
        action=action,
    )


def job_from_issue_comment_event(payload: dict[str, Any], delivery_id: str) -> ReviewJob | None:
    """Return a job for `/ai-review [approve|dismiss]` comments on PRs by trusted users."""
    comment = payload.get("comment") or {}
    issue = payload.get("issue") or {}
    if payload.get("action") != "created" or "pull_request" not in issue:
        return None
    if (comment.get("user") or {}).get("type") == "Bot":
        return None  # never react to our own (or other bots') comments

    first_line = (comment.get("body") or "").strip().splitlines()[:1]
    match = COMMAND.match(first_line[0]) if first_line else None
    if match is None or comment.get("author_association") not in TRUSTED_ASSOCIATIONS:
        return None

    kind: JobKind = (match.group(1) or "review").lower()  # type: ignore[assignment]
    repository = payload["repository"]
    return ReviewJob(
        delivery_id=delivery_id,
        installation_id=payload["installation"]["id"],
        owner=repository["owner"]["login"],
        repo=repository["name"],
        pr_number=issue["number"],
        head_sha=None,
        action="issue_comment",
        kind=kind,
        requested_by=comment["user"]["login"],
    )
