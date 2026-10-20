"""Structured output the LLM must return when it finishes a review.

Every field is required (nullable where optional) so the schema is valid for
OpenAI strict structured outputs.
"""

from typing import Literal

from pydantic import BaseModel, Field

Severity = Literal["critical", "major", "minor", "nit"]
Category = Literal["bug", "security", "performance", "maintainability", "style", "testing"]

SEVERITY_ORDER: dict[str, int] = {"critical": 0, "major": 1, "minor": 2, "nit": 3}


class ReviewFinding(BaseModel):
    """One problem found in the changed code."""

    path: str = Field(description="File path exactly as shown in the diff header")
    line: int = Field(description="Line number in the NEW version of the file, taken from the numbered diff")
    severity: Severity
    category: Category
    title: str = Field(description="One-line description of the problem")
    explanation: str = Field(description="Why this is a problem and what can go wrong")
    suggestion: str | None = Field(description="Concrete fix, or null if there is no obvious one")


class ReviewResult(BaseModel):
    """Submit the final code review. Call this exactly once, when you are done investigating."""

    summary: str = Field(description="Two to four sentences: what the PR does and the overall assessment")
    findings: list[ReviewFinding] = Field(description="Problems found; empty if the change looks good")
