from pr_reviewer.reviewer.publisher import build_review
from pr_reviewer.reviewer.schemas import ReviewResult
from tests.fakes import finding

FILES = [{"filename": "app.py", "patch": "@@ -1,1 +1,3 @@\n a\n+b\n+c"}]


def result(*findings):
    return ReviewResult.model_validate({"summary": "Summary.", "findings": list(findings)})


def test_findings_on_diff_lines_become_inline_comments():
    body, comments = build_review(result(finding(line=2, suggestion="Use c")), FILES)

    assert comments == [
        {
            "path": "app.py",
            "line": 2,
            "side": "RIGHT",
            "body": "🟠 **Major · bug: Off-by-one**\n\nLoop skips the last item.\n\n**Suggestion:** Use c",
        }
    ]
    assert "Other findings" not in body


def test_findings_outside_the_diff_go_in_the_body():
    body, comments = build_review(result(finding(line=40), finding(path="other.py", line=1)), FILES)

    assert comments == []
    assert "`app.py:40`" in body
    assert "`other.py:1`" in body


def test_comments_are_sorted_by_severity_and_counted():
    body, comments = build_review(
        result(finding(line=2, severity="nit"), finding(line=3, severity="critical"), finding(line=1, severity="nit")),
        FILES,
    )

    assert [c["line"] for c in comments] == [3, 2, 1]
    assert "**Findings:** 1 critical · 2 nit" in body


def test_no_findings():
    body, comments = build_review(result(), FILES)

    assert comments == []
    assert body.endswith("No issues found.")
