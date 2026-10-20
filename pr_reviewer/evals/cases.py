"""Eval cases: a fixed PR plus the issues a good review must find.

Each case is a JSON file in ``evals/cases``. Patches may be written as a list of
lines for readability. Cases with no expected issues measure false positives.
"""

import json
from pathlib import Path
from typing import Any, Literal

import requests
from pydantic import BaseModel, Field, field_validator

from pr_reviewer.reviewer.schemas import Category

DEFAULT_CASES_DIR = Path(__file__).resolve().parents[2] / "evals" / "cases"


class CaseFile(BaseModel):
    filename: str
    status: str = "modified"
    patch: str | None = None
    additions: int = 0
    deletions: int = 0

    @field_validator("patch", mode="before")
    @classmethod
    def _join_lines(cls, value: Any) -> Any:
        return "\n".join(value) if isinstance(value, list) else value


class CaseConvention(BaseModel):
    kind: Literal["guideline", "past_review"] = "guideline"
    source: str
    text: str


class ExpectedIssue(BaseModel):
    id: str
    path: str
    lines: tuple[int, int] = Field(description="Inclusive range of new-file lines where the issue is")
    category: Category
    description: str


class EvalCase(BaseModel):
    id: str
    title: str
    description: str = ""
    tags: list[str] = []
    files: list[CaseFile]
    repo_files: dict[str, str] = {}
    conventions: list[CaseConvention] = []
    expected: list[ExpectedIssue] = []

    @field_validator("repo_files", mode="before")
    @classmethod
    def _join_file_lines(cls, value: Any) -> Any:
        if isinstance(value, dict):
            return {path: "\n".join(c) if isinstance(c, list) else c for path, c in value.items()}
        return value

    def github_files(self) -> list[dict[str, Any]]:
        return [f.model_dump() for f in self.files]


def load_cases(directory: Path = DEFAULT_CASES_DIR) -> list[EvalCase]:
    return [EvalCase.model_validate(json.loads(path.read_text())) for path in sorted(directory.glob("*.json"))]


class DictRepoReader:
    """RepoReader over a case's ``repo_files``, mimicking GitHub's 404s."""

    def __init__(self, files: dict[str, str]):
        self._files = files

    def read_file(self, path: str) -> str:
        if path not in self._files:
            raise requests.HTTPError(f"404 Not Found: {path}")
        return self._files[path]

    def list_directory(self, path: str) -> list[str]:
        prefix = f"{path.rstrip('/')}/" if path else ""
        entries = {p[len(prefix):].split("/", 1)[0] for p in self._files if p.startswith(prefix)}
        if prefix and not entries:
            raise requests.HTTPError(f"404 Not Found: {path}")
        return sorted(prefix + e for e in entries)
