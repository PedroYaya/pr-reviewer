"""Scores eval runs and aggregates them into the suite's headline metrics.

Two kinds of matching, reported separately:
- location (deterministic): same file, line within the expected range +/- LINE_TOLERANCE.
- judge (LLM): the judge says the finding identifies the expected issue.
"""

from dataclasses import dataclass, field
from statistics import mean

from pr_reviewer.evals.cases import EvalCase, ExpectedIssue
from pr_reviewer.evals.judge import FindingVerdict
from pr_reviewer.reviewer.schemas import ReviewFinding

LINE_TOLERANCE = 2


@dataclass
class CaseScore:
    case_id: str
    expected: int
    findings: int
    location_matched: set[str]
    findings_on_expected: int
    useful: int | None = None
    judge_matched: set[str] | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0
    tool_calls: int = 0
    dropped: int = 0
    seconds: float = 0.0
    error: str | None = None
    details: list[dict] = field(default_factory=list)


def location_match(finding: ReviewFinding, issue: ExpectedIssue) -> bool:
    low, high = issue.lines
    return finding.path == issue.path and low - LINE_TOLERANCE <= finding.line <= high + LINE_TOLERANCE


def score_case(case: EvalCase, findings: list[ReviewFinding], verdicts: list[FindingVerdict] | None) -> CaseScore:
    matched: set[str] = set()
    on_expected = 0
    details = []
    by_index = {v.finding_index: v for v in verdicts or []}
    for index, finding in enumerate(findings):
        hits = {issue.id for issue in case.expected if location_match(finding, issue)}
        matched |= hits
        on_expected += bool(hits)
        verdict = by_index.get(index)
        details.append({
            "location": f"{finding.path}:{finding.line}",
            "severity": finding.severity,
            "title": finding.title,
            "location_match": sorted(hits),
            "useful": verdict.useful if verdict else None,
            "judge_match": verdict.matches_expected if verdict else None,
            "judge_reason": verdict.reason if verdict else None,
        })

    score = CaseScore(case.id, len(case.expected), len(findings), matched, on_expected, details=details)
    if verdicts is not None:
        expected_ids = {issue.id for issue in case.expected}
        # A finding with no verdict counts as not useful.
        score.useful = sum(1 for i in range(len(findings)) if i in by_index and by_index[i].useful)
        score.judge_matched = {v.matches_expected for v in verdicts if v.matches_expected in expected_ids}
    return score


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def summarize(scores: list[CaseScore]) -> dict:
    ok = [s for s in scores if s.error is None]
    clean = [s for s in ok if s.expected == 0]
    judged = [s for s in ok if s.useful is not None]
    expected_total = sum(s.expected for s in ok)
    findings_total = sum(s.findings for s in ok)
    summary = {
        "cases": len(scores),
        "errors": len(scores) - len(ok),
        "expected_issues": expected_total,
        "findings": findings_total,
        "recall_location": _ratio(sum(len(s.location_matched) for s in ok), expected_total),
        "precision_location": _ratio(sum(s.findings_on_expected for s in ok), findings_total),
        "clean_cases": len(clean),
        "findings_on_clean_cases": sum(s.findings for s in clean),
        "avg_input_tokens": round(mean(s.input_tokens for s in ok)) if ok else None,
        "avg_output_tokens": round(mean(s.output_tokens for s in ok)) if ok else None,
        "avg_total_tokens": round(mean(s.input_tokens + s.output_tokens for s in ok)) if ok else None,
        "avg_llm_calls": round(mean(s.llm_calls for s in ok), 2) if ok else None,
        "avg_tool_calls": round(mean(s.tool_calls for s in ok), 2) if ok else None,
        "avg_seconds": round(mean(s.seconds for s in ok), 2) if ok else None,
        "guardrail_dropped": sum(s.dropped for s in ok),
    }
    if judged:
        summary["useful_rate"] = _ratio(sum(s.useful for s in judged), sum(s.findings for s in judged))
        summary["recall_judge"] = _ratio(
            sum(len(s.judge_matched) for s in judged), sum(s.expected for s in judged)
        )
    return summary
