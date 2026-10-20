"""Turns a structured review into a GitHub pull request review payload."""

from collections import Counter
from collections.abc import Sequence
from typing import Any

from pr_reviewer.reviewer.budget import OmittedFile
from pr_reviewer.reviewer.diff import commentable_lines
from pr_reviewer.reviewer.schemas import SEVERITY_ORDER, ReviewFinding, ReviewResult

SEVERITY_ICONS = {"critical": "🔴", "major": "🟠", "minor": "🟡", "nit": "⚪"}


def format_finding(finding: ReviewFinding) -> str:
    text = f"{SEVERITY_ICONS[finding.severity]} **{finding.severity.capitalize()} · {finding.category}: {finding.title}**\n\n{finding.explanation}"
    if finding.suggestion:
        text += f"\n\n**Suggestion:** {finding.suggestion}"
    return text


def build_review(
    result: ReviewResult, files: list[dict[str, Any]], omitted: Sequence[OmittedFile] = ()
) -> tuple[str, list[dict[str, Any]]]:
    """Return (review body, inline comments).

    Findings on lines outside the diff can't be posted inline (GitHub rejects
    the whole review), so they go in the review body instead.
    """
    lines_by_path = {f["filename"]: commentable_lines(f.get("patch") or "") for f in files}
    findings = sorted(result.findings, key=lambda f: SEVERITY_ORDER[f.severity])

    comments, unplaced = [], []
    for finding in findings:
        if finding.line in lines_by_path.get(finding.path, set()):
            comments.append({"path": finding.path, "line": finding.line, "side": "RIGHT", "body": format_finding(finding)})
        else:
            unplaced.append(finding)

    body = f"## 🤖 AI Code Review\n\n{result.summary}\n\n"
    if findings:
        counts = Counter(f.severity for f in findings)
        body += "**Findings:** " + " · ".join(
            f"{counts[s]} {s}" for s in SEVERITY_ORDER if counts[s]
        )
    else:
        body += "No issues found."
    if unplaced:
        body += "\n\n### Other findings\n\n" + "\n\n".join(
            f"`{f.path}:{f.line}`: {format_finding(f)}" for f in unplaced
        )
    if omitted:
        body += f"\n\n<details><summary>{len(omitted)} file(s) not reviewed</summary>\n\n" + "\n".join(
            f"- `{o.filename}`: {o.reason}" for o in omitted
        ) + "\n</details>"
    return body, comments


def build_draft_comment(result: ReviewResult, comments: list[dict[str, Any]], head_sha: str) -> str:
    """Issue comment that previews a draft review so a maintainer can decide whether to publish it."""
    findings = sorted(result.findings, key=lambda f: SEVERITY_ORDER[f.severity])
    text = (
        f"## 🤖 AI review draft for `{head_sha[:7]}`\n\n{result.summary}\n\n"
        f"{len(findings)} finding(s), {len(comments)} of them inline."
    )
    if findings:
        text += "\n\n| Severity | Location | Finding |\n|---|---|---|\n" + "\n".join(
            f"| {SEVERITY_ICONS[f.severity]} {f.severity} | `{f.path}:{f.line}` | {f.title.replace('|', '/')} |"
            for f in findings
        )
    return text + "\n\nA maintainer can reply `/ai-review approve` to publish it or `/ai-review dismiss` to discard it."
