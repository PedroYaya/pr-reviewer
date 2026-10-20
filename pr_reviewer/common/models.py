"""Messages exchanged between the gateway and reviewer services."""

from typing import Literal

from pydantic import BaseModel

# "review" comes from PR events or a `/ai-review` comment; "approve" and
# "dismiss" act on a draft review waiting for a maintainer.
JobKind = Literal["review", "approve", "dismiss"]


class ReviewJob(BaseModel):
    delivery_id: str
    installation_id: int
    owner: str
    repo: str
    pr_number: int
    # Commit the event was about; None for comment commands, which use the current head.
    head_sha: str | None
    action: str
    kind: JobKind = "review"
    requested_by: str | None = None
