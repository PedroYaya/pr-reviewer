import pytest

from pr_reviewer.evals.cases import DictRepoReader, load_cases
from pr_reviewer.evals.judge import FindingVerdict
from pr_reviewer.evals.run import VARIANTS, format_report, run_case
from pr_reviewer.evals.scoring import score_case, summarize
from pr_reviewer.reviewer.agent import ReviewAgent
from pr_reviewer.reviewer.diff import commentable_lines
from pr_reviewer.reviewer.schemas import ReviewFinding
from tests.fakes import ScriptedChatModel, finding, submit

CASES = {case.id: case for case in load_cases()}


def test_suite_has_twenty_cases_with_unique_ids():
    assert len(load_cases()) == 20 == len(CASES)


def test_suite_includes_clean_cases_for_false_positives():
    assert sum(1 for case in CASES.values() if not case.expected) >= 3


@pytest.mark.parametrize("case", list(CASES.values()), ids=list(CASES))
def test_expected_issues_point_at_commentable_lines(case):
    patches = {f.filename: f.patch for f in case.files}
    for issue in case.expected:
        low, high = issue.lines
        assert set(range(low, high + 1)) <= commentable_lines(patches[issue.path]), issue.id


def test_repo_reader_mimics_github():
    reader = DictRepoReader({"src/a.py": "a", "src/lib/b.py": "b", "README.md": "r"})

    assert reader.list_directory("") == ["README.md", "src"]
    assert reader.list_directory("src") == ["src/a.py", "src/lib"]
    with pytest.raises(Exception, match="404"):
        reader.read_file("missing.py")


def as_findings(*items):
    return [ReviewFinding.model_validate(item) for item in items]


def test_scores_location_matches_with_tolerance():
    case = CASES["pagination-off-by-one"]
    score = score_case(case, as_findings(finding(path="app/pagination.py", line=4), finding(path="app/pagination.py", line=30)), None)

    assert score.location_matched == {"start-index"}
    assert score.findings_on_expected == 1
    assert score.useful is None


def test_scores_judge_verdicts():
    case = CASES["sql-injection"]
    verdicts = [
        FindingVerdict(finding_index=0, useful=True, matches_expected="sqli", reason="right"),
        FindingVerdict(finding_index=1, useful=False, matches_expected="made-up", reason="wrong"),
    ]
    score = score_case(case, as_findings(finding(path="app/users.py", line=40), finding(path="app/users.py", line=41)), verdicts)

    assert score.useful == 1
    assert score.judge_matched == {"sqli"}
    assert score.location_matched == set()


def test_summary_reports_headline_metrics():
    scores = [
        score_case(CASES["sql-injection"], as_findings(finding(path="app/users.py", line=14)),
                   [FindingVerdict(finding_index=0, useful=True, matches_expected="sqli", reason="")]),
        score_case(CASES["clean-docs"], as_findings(finding(path="README.md", line=11)),
                   [FindingVerdict(finding_index=0, useful=False, matches_expected=None, reason="")]),
    ]
    scores[0].input_tokens, scores[1].input_tokens = 1000, 3000

    summary = summarize(scores)

    assert summary["recall_location"] == 1.0
    assert summary["useful_rate"] == 0.5
    assert summary["findings_on_clean_cases"] == 1
    assert summary["avg_input_tokens"] == 2000


def agent_returning(*responses):
    return ReviewAgent(ScriptedChatModel(responses=list(responses)))


def test_full_variant_finds_committed_secret_without_the_llm():
    score = run_case(CASES["hardcoded-secret"], agent_returning(submit()), VARIANTS["full"])

    assert score.error is None
    assert score.location_matched == {"stripe-key"}


def test_full_variant_skips_lockfile_but_baseline_sends_it():
    case = CASES["lockfile-and-retry"]
    full_model = ScriptedChatModel(responses=[submit()])
    baseline_model = ScriptedChatModel(responses=[submit()])

    run_case(case, ReviewAgent(full_model), VARIANTS["full"])
    run_case(case, ReviewAgent(baseline_model), VARIANTS["baseline"])

    assert "dep-59" not in full_model.received[0][1].content
    assert "dep-59" in baseline_model.received[0][1].content


def test_baseline_keeps_findings_guardrails_would_drop():
    case = CASES["sql-injection"]
    low = finding(path="app/users.py", line=14, confidence="low")

    full = run_case(case, agent_returning(submit(findings=[low])), VARIANTS["full"])
    baseline = run_case(case, agent_returning(submit(findings=[low])), VARIANTS["baseline"])

    assert (full.findings, full.dropped) == (0, 1)
    assert baseline.findings == 1


def test_failing_case_is_recorded_not_raised():
    score = run_case(CASES["sql-injection"], agent_returning(), VARIANTS["full"])

    assert score.error is not None


class StubJudge:
    def judge(self, case, findings):
        return [FindingVerdict(finding_index=i, useful=True, matches_expected=None, reason="") for i in range(len(findings))]


def test_run_case_uses_judge():
    score = run_case(CASES["sql-injection"], agent_returning(submit(findings=[finding(path="app/users.py", line=14)])),
                     VARIANTS["full"], judge=StubJudge())

    assert score.useful == 1


def test_report_formats_percentages_side_by_side():
    report = format_report({"full": {"useful_rate": 0.8, "avg_total_tokens": 1500, "errors": 0},
                            "baseline": {"useful_rate": 0.6, "avg_total_tokens": 2000, "errors": 0}})

    assert "| Metric | full | baseline |" in report
    assert "| Useful findings (judge) | 80% | 60% |" in report
    assert "| Avg total tokens | 1500 | 2000 |" in report
