"""Helpers for GitHub unified diff patches.

GitHub only accepts inline review comments on lines that appear in the diff,
so we number the patch for the LLM and later check its findings against the
same set of lines.
"""

import re
from collections.abc import Iterator

HUNK_HEADER = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def iter_patch_lines(patch: str) -> Iterator[tuple[int | None, str]]:
    """Yield (new_file_line_number, raw_line); the number is None for removed lines and headers."""
    new_line = 0
    for raw in patch.splitlines():
        if match := HUNK_HEADER.match(raw):
            new_line = int(match.group(1))
            yield None, raw
        elif raw.startswith("-") or raw.startswith("\\"):
            yield None, raw
        else:
            yield new_line, raw
            new_line += 1


def commentable_lines(patch: str) -> set[int]:
    return {number for number, _ in iter_patch_lines(patch) if number is not None}


def number_patch(patch: str) -> str:
    """Prefix each line with its new-file line number so the LLM can cite it."""
    return "\n".join(
        f"{number:>5} {raw}" if number is not None else f"{'':>5} {raw}"
        for number, raw in iter_patch_lines(patch)
    )
