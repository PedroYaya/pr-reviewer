"""Turn GitHub webhook payloads into review jobs."""

from typing import Any

from pr_reviewer.common.models import ReviewJob

REVIEWABLE_ACTIONS = {"opened", "synchronize", "reopened", "ready_for_review"}


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
