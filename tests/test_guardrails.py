import pytest

from pr_reviewer.reviewer.diff import commentable_lines
from pr_reviewer.reviewer.guardrails import (
    REDACTED,
    RedactingRepoReader,
    apply_output_guardrails,
    redact_files,
    redact_text,
    secret_findings,
)
from pr_reviewer.reviewer.schemas import ReviewFinding
from tests.fakes import FakeRepo, finding

AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"
GITHUB_TOKEN = "ghp_" + "a" * 36
OPENAI_KEY = "sk-proj-" + "b" * 30


@pytest.mark.parametrize(
    "line, secret",
    [
        (f'aws_key = "{AWS_KEY}"', AWS_KEY),
        (f"export GH={GITHUB_TOKEN}", GITHUB_TOKEN),
        (f"client = OpenAI(api_key='{OPENAI_KEY}')", OPENAI_KEY),
        ('DB_PASSWORD = "hunter2-but-longer"', "hunter2-but-longer"),
        ('"auth_token": "abcdef1234567890"', "abcdef1234567890"),
        ('AWS_SECRET_ACCESS_KEY="wJalrXUtnFEMIK7MDENG"', "wJalrXUtnFEMIK7MDENG"),
    ],
)
def test_redacts_secrets(line, secret):
    redacted = redact_text(line)

    assert secret not in redacted
    assert REDACTED in redacted


@pytest.mark.parametrize(
    "line", ['password = os.environ["DB_PASSWORD"]', 'token = "short"', "sk-short", 'TOKEN_URL = "https://auth.example.com/token"']
)
def test_leaves_non_secrets_alone(line):
    assert redact_text(line) == line


def test_redacts_private_key_block_keeping_line_count():
    text = "key = '''\n-----BEGIN RSA PRIVATE KEY-----\nMIIEow\nAAAA\n-----END RSA PRIVATE KEY-----\n'''"

    redacted = redact_text(text).splitlines()

    assert len(redacted) == len(text.splitlines())
    assert "MIIEow" not in "\n".join(redacted)
    assert redacted[4] == "-----END RSA PRIVATE KEY-----"


def test_redact_files_reports_secrets_on_added_lines_only():
    patch = f'@@ -1,2 +1,3 @@\n-old = "{GITHUB_TOKEN}"\n+new = "{AWS_KEY}"\n ok = 1\n+again = "{AWS_KEY}"'
    original = {"filename": "settings.py", "patch": patch}

    [redacted], hits = redact_files([original])

    assert AWS_KEY not in redacted["patch"] and GITHUB_TOKEN not in redacted["patch"]
    assert commentable_lines(redacted["patch"]) == commentable_lines(patch)
    assert [(h.path, h.line, h.kind) for h in hits] == [
        ("settings.py", 1, "AWS access key"),
        ("settings.py", 3, "AWS access key"),
    ]
    assert original["patch"] == patch


def test_secret_findings_are_critical_security_issues():
    _, hits = redact_files([{"filename": "a.py", "patch": f'@@ -0,0 +1 @@\n+k = "{AWS_KEY}"'}])

    [result] = secret_findings(hits)

    assert (result.path, result.line, result.severity, result.category) == ("a.py", 1, "critical", "security")
    assert AWS_KEY not in result.explanation


def test_redacting_reader_redacts_tool_results():
    reader = RedactingRepoReader(FakeRepo({"config.py": f'TOKEN = "{GITHUB_TOKEN}"'}))

    assert GITHUB_TOKEN not in reader.read_file("config.py")


FILES = [{"filename": "app.py"}, {"filename": "lib.py"}]


def findings(*items):
    return [ReviewFinding.model_validate(item) for item in items]


def test_drops_findings_on_files_outside_the_review():
    kept, dropped = apply_output_guardrails(findings(finding(path="ghost.py")), FILES, max_findings=10)

    assert kept == []
    assert dropped[0].reason == "file not in the reviewed diff"


def test_drops_low_confidence_findings():
    kept, dropped = apply_output_guardrails(
        findings(finding(confidence="low"), finding(line=3, confidence="medium")), FILES, max_findings=10
    )

    assert [f.line for f in kept] == [3]
    assert dropped[0].reason == "low confidence"


def test_drops_duplicates_keeping_the_most_severe():
    kept, dropped = apply_output_guardrails(
        findings(finding(severity="minor", title="a"), finding(severity="critical", title="b")), FILES, max_findings=10
    )

    assert [f.title for f in kept] == ["b"]
    assert dropped[0].reason == "duplicate"


def test_caps_findings_keeping_highest_severity():
    items = [finding(line=i, severity="nit") for i in range(5)] + [finding(line=99, severity="critical")]

    kept, dropped = apply_output_guardrails(findings(*items), FILES, max_findings=3)

    assert [f.severity for f in kept] == ["critical", "nit", "nit"]
    assert {d.reason for d in dropped} == {"over the findings limit"}
