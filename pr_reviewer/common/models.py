"""Messages exchanged between the gateway and reviewer services."""

from pydantic import BaseModel


class ReviewJob(BaseModel):
    delivery_id: str
    installation_id: int
    owner: str
    repo: str
    pr_number: int
    head_sha: str
    action: str
