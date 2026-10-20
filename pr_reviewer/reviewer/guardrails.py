"""Input and output guardrails around the review agent.

Input: secrets in the diff or in files the agent reads are redacted before they
reach the LLM, and each secret added by the PR becomes a deterministic finding.

Output: findings are dropped when they point at files outside the PR, are
low confidence or duplicated, and the total is capped so a review stays readable.
"""

import re
from dataclasses import dataclass
from typing import Any

from pr_reviewer.reviewer.diff import iter_patch_lines
from pr_reviewer.reviewer.repo_tools import RepoReader
from pr_reviewer.reviewer.schemas import SEVERITY_ORDER, ReviewFinding

REDACTED = "[REDACTED]"

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16}\b")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{36,}|github_pat_[A-Za-z0-9_]{22,})\b")),
    ("OpenAI API key", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}")),
]
# Only the quoted value is redacted, so the variable name stays readable.
# Names may carry prefixes/suffixes (DB_PASSWORD, aws_secret_key); URLs are not secrets.
ASSIGNED_SECRET = re.compile(
    r"""(?i)\b[\w-]*(?:api[_-]?key|secret|password|passwd|token)[\w-]*["']?\s*[:=]\s*["'](?!https?://)([^"'\s]{12,})["']"""
)
PRIVATE_KEY_BEGIN = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")
PRIVATE_KEY_END = re.compile(r"-----END [A-Z ]*PRIVATE KEY-----")


@dataclass(frozen=True)
class SecretHit:
    path: str
    line: int
    kind: str


@dataclass(frozen=True)
class DroppedFinding:
    finding: ReviewFinding
    reason: str


def _redact_line(line: str) -> tuple[str, list[str]]:
    kinds = []
    for kind, pattern in SECRET_PATTERNS:
        line, count = pattern.subn(REDACTED, line)
        if count:
            kinds.append(kind)
    line, count = ASSIGNED_SECRET.subn(lambda m: m.group(0).replace(m.group(1), REDACTED), line)
    if count:
        kinds.append("hardcoded credential")
    return line, kinds


def redact_lines(lines: list[str], marker_width: int = 0) -> tuple[list[str], list[tuple[int, list[str]]]]:
    """Redact line by line, keeping the line count so diff line numbers stay valid.

    ``marker_width`` is 1 for patches, whose lines start with '+', '-' or ' '.
    Returns the redacted lines and (index, secret kinds) for each line with a hit.
    """
    redacted, hits = [], []
    in_private_key = False
    for index, line in enumerate(lines):
        marker, content = line[:marker_width], line[marker_width:]
        if in_private_key:
            if PRIVATE_KEY_END.search(content):
                in_private_key = False
            else:
                content = REDACTED
            redacted.append(marker + content)
            continue
        if PRIVATE_KEY_BEGIN.search(content):
            in_private_key = not PRIVATE_KEY_END.search(content)
            redacted.append(marker + content)
            hits.append((index, ["private key"]))
            continue
        content, kinds = _redact_line(content)
        redacted.append(marker + content)
        if kinds:
            hits.append((index, kinds))
    return redacted, hits


def redact_text(text: str) -> str:
    lines, _ = redact_lines(text.splitlines())
    return "\n".join(lines)


def redact_files(files: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[SecretHit]]:
    """Return copies of the files with redacted patches, plus secrets on added lines."""
    redacted_files, hits = [], []
    for file in files:
        raw_lines = file["patch"].splitlines()
        numbered = list(iter_patch_lines(file["patch"]))
        lines, line_hits = redact_lines(raw_lines, marker_width=1)
        for index, kinds in line_hits:
            number, raw = numbered[index]
            if number is not None and raw.startswith("+"):
                hits.extend(SecretHit(file["filename"], number, kind) for kind in kinds)
        redacted_files.append({**file, "patch": "\n".join(lines)})
    return redacted_files, hits


class RedactingRepoReader:
    """Wraps a RepoReader so file contents the agent reads are redacted too."""

    def __init__(self, inner: RepoReader):
        self._inner = inner

    def read_file(self, path: str) -> str:
        return redact_text(self._inner.read_file(path))

    def list_directory(self, path: str) -> list[str]:
        return self._inner.list_directory(path)


def secret_findings(hits: list[SecretHit]) -> list[ReviewFinding]:
    return [
        ReviewFinding(
            path=hit.path,
            line=hit.line,
            severity="critical",
            category="security",
            confidence="high",
            title=f"Possible {hit.kind} committed",
            explanation="This line looks like it contains a secret. Anyone with read access to the repository "
            "or its history can use it. The value was redacted before being sent to the AI reviewer.",
            suggestion="Remove it, rotate the credential, and load it from environment variables or a secrets manager.",
        )
        for hit in hits
    ]


def apply_output_guardrails(
    findings: list[ReviewFinding], files: list[dict[str, Any]], max_findings: int
) -> tuple[list[ReviewFinding], list[DroppedFinding]]:
    reviewed_paths = {f["filename"] for f in files}
    kept: list[ReviewFinding] = []
    dropped: list[DroppedFinding] = []
    seen: set[tuple[str, int, str]] = set()

    for finding in sorted(findings, key=lambda f: SEVERITY_ORDER[f.severity]):
        key = (finding.path, finding.line, finding.category)
        if finding.path not in reviewed_paths:
            dropped.append(DroppedFinding(finding, "file not in the reviewed diff"))
        elif finding.confidence == "low":
            dropped.append(DroppedFinding(finding, "low confidence"))
        elif key in seen:
            dropped.append(DroppedFinding(finding, "duplicate"))
        elif len(kept) >= max_findings:
            dropped.append(DroppedFinding(finding, "over the findings limit"))
        else:
            seen.add(key)
            kept.append(finding)
    return kept, dropped
