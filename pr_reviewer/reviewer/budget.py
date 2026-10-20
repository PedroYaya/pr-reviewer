"""Keeps the diff sent to the LLM within a token budget.

Lock files and generated code are skipped, each patch is capped, and files are
admitted smallest-first so one huge diff can't crowd out the rest of the PR.
"""

from dataclasses import dataclass
from fnmatch import fnmatch
from typing import Any

# Rough estimate for OpenAI tokenizers on code. Real usage is read from the
# API response; this is only for deciding what fits.
CHARS_PER_TOKEN = 4

IGNORED_PATTERNS = (
    "*.lock", "package-lock.json", "pnpm-lock.yaml", "go.sum",
    "*.min.js", "*.min.css", "*.map", "*.snap", "*.svg",
    "*_pb2.py", "*.pb.go", "*.generated.*",
    "dist/*", "build/*", "vendor/*", "node_modules/*",
    "*/dist/*", "*/build/*", "*/vendor/*", "*/node_modules/*",
)


@dataclass(frozen=True)
class TokenBudget:
    diff_tokens: int
    file_tokens: int


@dataclass(frozen=True)
class OmittedFile:
    filename: str
    reason: str


@dataclass
class DiffSelection:
    files: list[dict[str, Any]]
    omitted: list[OmittedFile]


def estimate_tokens(text: str) -> int:
    return -(-len(text) // CHARS_PER_TOKEN)


def is_ignored(filename: str) -> bool:
    return any(fnmatch(filename, pattern) for pattern in IGNORED_PATTERNS)


def truncate_patch(patch: str, max_tokens: int) -> tuple[str, bool]:
    """Cut the patch at a line boundary so it fits; returns (patch, was_truncated)."""
    max_chars = max_tokens * CHARS_PER_TOKEN
    if len(patch) <= max_chars:
        return patch, False
    kept, used = [], 0
    for line in patch.splitlines():
        if used + len(line) + 1 > max_chars:
            break
        kept.append(line)
        used += len(line) + 1
    return "\n".join(kept), True


def select_files(files: list[dict[str, Any]], budget: TokenBudget) -> DiffSelection:
    omitted: list[OmittedFile] = []
    candidates: list[tuple[int, dict[str, Any]]] = []
    for index, file in enumerate(files):
        name = file["filename"]
        if is_ignored(name):
            omitted.append(OmittedFile(name, "lock file or generated code"))
        elif file.get("status") == "removed":
            omitted.append(OmittedFile(name, "file deleted"))
        elif not file.get("patch"):
            omitted.append(OmittedFile(name, "binary or too large for GitHub to diff"))
        else:
            patch, truncated = truncate_patch(file["patch"], budget.file_tokens)
            candidates.append((index, {**file, "patch": patch, "truncated": truncated}))

    selected: list[tuple[int, dict[str, Any]]] = []
    used = 0
    for index, file in sorted(candidates, key=lambda item: len(item[1]["patch"])):
        cost = estimate_tokens(file["patch"])
        if used + cost > budget.diff_tokens:
            omitted.append(OmittedFile(file["filename"], "over the review token budget"))
            continue
        selected.append((index, file))
        used += cost

    return DiffSelection(files=[file for _, file in sorted(selected, key=lambda item: item[0])], omitted=omitted)
