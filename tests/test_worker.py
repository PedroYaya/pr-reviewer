import pytest
import requests
from prometheus_client import REGISTRY

from pr_reviewer.common.models import ReviewJob
from pr_reviewer.common.queue import InMemoryJobQueue
from pr_reviewer.reviewer.agent import ReviewAgent
from pr_reviewer.reviewer.drafts import InMemoryDraftStore
from pr_reviewer.reviewer.worker import ReviewWorker
from tests.fakes import KeywordEmbeddings, ScriptedChatModel, finding, submit, tool_call

FILES = [{"filename": "app.py", "status": "modified", "additions": 1, "deletions": 0, "patch": "@@ -1,1 +1,2 @@\n a\n+print('hi')"}]


class FakeGitHub:
    def __init__(self, head_sha="abc123", files=FILES, repo_files=None, review_comments=()):
        self.head_sha = head_sha
        self.files = files
        self.repo_files = repo_files or {}
        self.review_comments = list(review_comments)
        self.reviews = []
        self.issue_comments = []
        self.file_reads = []

    def get_pull_request(self, installation_id, owner, repo, number):
        return {"title": "Add greeting", "body": None, "head": {"sha": self.head_sha}}

    def list_pull_request_files(self, installation_id, owner, repo, number):
        return self.files

    def get_file_content(self, installation_id, owner, repo, path, ref):
        self.file_reads.append((path, ref))
        return self.repo_files.get(path, "contents")

    def list_directory(self, installation_id, owner, repo, path, ref):
        return sorted(p for p in self.repo_files if p.rpartition("/")[0] == path)

    def list_review_comments(self, installation_id, owner, repo, limit):
        return self.review_comments

    def create_issue_comment(self, installation_id, owner, repo, number, body):
        self.issue_comments.append(body)
        return {"id": 2}

    def create_review(self, installation_id, owner, repo, number, commit_id, body, comments):
        self.reviews.append({"commit_id": commit_id, "body": body, "comments": comments})
        return {"id": 1}


def make_job(head_sha="abc123", kind="review", requested_by=None):
    return ReviewJob(
        delivery_id="d1", installation_id=42, owner="acme", repo="repo",
        pr_number=7, head_sha=head_sha, action="opened", kind=kind, requested_by=requested_by,
    )


def make_worker(github, *responses, embeddings=None):
    agent = ReviewAgent(ScriptedChatModel(responses=list(responses or [submit()])))
    return ReviewWorker(InMemoryJobQueue(), github, agent, embeddings=embeddings)


def test_posts_review_with_inline_comments_on_head_commit():
    github = FakeGitHub()
    make_worker(github, submit("Prints debug output.", [finding(line=2)])).process(make_job())

    [review] = github.reviews
    assert review["commit_id"] == "abc123"
    assert "Prints debug output." in review["body"]
    assert [c["line"] for c in review["comments"]] == [2]


def test_agent_tools_read_files_at_head_commit():
    github = FakeGitHub()
    make_worker(github, tool_call("read_file", {"path": "util.py"}), submit()).process(make_job())

    assert github.file_reads == [("util.py", "abc123")]


def test_skips_job_for_outdated_commit():
    github = FakeGitHub(head_sha="newer")
    make_worker(github).process(make_job(head_sha="abc123"))

    assert github.reviews == []


def test_skips_pull_request_without_files():
    github = FakeGitHub(files=[])
    make_worker(github).process(make_job())

    assert github.reviews == []


def test_reviews_are_independent():
    # Regression: the old reviewer shared LangChain memory across every PR.
    github = FakeGitHub()
    model = ScriptedChatModel(responses=[submit("first"), submit("second")])
    worker = ReviewWorker(InMemoryJobQueue(), github, ReviewAgent(model))
    worker.process(make_job())
    worker.process(make_job())

    assert len(model.received[1]) == len(model.received[0])
    assert "second" in github.reviews[1]["body"]


def test_run_survives_failed_job():
    queue = InMemoryJobQueue()
    github = FakeGitHub()
    worker = ReviewWorker(queue, github, ReviewAgent(ScriptedChatModel(responses=[])))

    def failing_then_stop(*args):
        worker.stop()
        raise RuntimeError("GitHub is down")

    github.get_pull_request = failing_then_stop
    queue.enqueue(make_job())
    worker.run()  # must return instead of raising

    assert github.reviews == []
    assert [job.attempt for job in queue.scheduled] == [2]


def test_reviews_with_conventions_from_repo_and_past_comments():
    github = FakeGitHub(
        repo_files={"CONTRIBUTING.md": "## Output\nUse the logger, never print."},
        review_comments=[{"path": "cli.py", "body": "Debug print left in; please remove before merging.",
                          "diff_hunk": "+print(x)", "user": {"type": "User"}}],
    )
    model = ScriptedChatModel(responses=[submit()])
    worker = ReviewWorker(InMemoryJobQueue(), github, ReviewAgent(model), embeddings=KeywordEmbeddings(["print", "logger"]))

    worker.process(make_job())

    prompt = model.received[0][1].content
    assert "[guideline: CONTRIBUTING.md]" in prompt
    assert "[past_review: cli.py]" in prompt


def test_review_continues_when_conventions_fail_to_load():
    github = FakeGitHub()

    def broken(*args):
        raise RuntimeError("rate limited")

    github.list_review_comments = broken
    make_worker(github, embeddings=KeywordEmbeddings(["x"])).process(make_job())

    assert len(github.reviews) == 1


def test_skips_review_when_only_generated_files_changed():
    github = FakeGitHub(files=[{"filename": "poetry.lock", "status": "modified", "patch": "@@ -1 +1 @@\n+x"}])
    make_worker(github).process(make_job())

    assert github.reviews == []


def test_review_body_lists_files_left_out():
    github = FakeGitHub(files=[*FILES, {"filename": "poetry.lock", "status": "modified", "patch": "@@ -1 +1 @@\n+x"}])
    make_worker(github).process(make_job())

    assert "`poetry.lock`: lock file or generated code" in github.reviews[0]["body"]


AWS_KEY = "AKIA" + "ABCDEFGHIJKLMNOP"


def test_llm_never_sees_secrets_and_secret_becomes_finding():
    github = FakeGitHub(files=[{"filename": "settings.py", "status": "modified", "patch": f'@@ -0,0 +1 @@\n+KEY = "{AWS_KEY}"'}])
    model = ScriptedChatModel(responses=[submit()])
    ReviewWorker(InMemoryJobQueue(), github, ReviewAgent(model)).process(make_job())

    assert AWS_KEY not in str(model.received)
    [comment] = github.reviews[0]["comments"]
    assert (comment["path"], comment["line"]) == ("settings.py", 1)
    assert "Possible AWS access key committed" in comment["body"]


def test_output_guardrails_filter_model_findings():
    github = FakeGitHub()
    make_worker(github, submit(findings=[finding(line=2, confidence="low"), finding(path="ghost.py")])).process(make_job())

    assert github.reviews[0]["comments"] == []
    assert "No issues found." in github.reviews[0]["body"]


def approval_worker(github, drafts, *responses):
    agent = ReviewAgent(ScriptedChatModel(responses=list(responses or [submit()])))
    return ReviewWorker(InMemoryJobQueue(), github, agent, review_mode="approval", drafts=drafts)


def test_approval_mode_posts_draft_instead_of_review():
    github, drafts = FakeGitHub(), InMemoryDraftStore()
    approval_worker(github, drafts, submit(findings=[finding(line=2)])).process(make_job())

    assert github.reviews == []
    [draft_comment] = github.issue_comments
    assert "AI review draft" in draft_comment
    assert drafts.get("draft:acme/repo#7").head_sha == "abc123"


def test_approve_publishes_draft_and_credits_approver():
    github, drafts = FakeGitHub(), InMemoryDraftStore()
    worker = approval_worker(github, drafts, submit(findings=[finding(line=2)]))
    worker.process(make_job())

    worker.process(make_job(head_sha=None, kind="approve", requested_by="maria"))

    [review] = github.reviews
    assert [c["line"] for c in review["comments"]] == [2]
    assert review["body"].endswith("_Approved for publishing by @maria._")
    assert drafts.get("draft:acme/repo#7") is None


def test_approve_refuses_draft_for_outdated_commit():
    github, drafts = FakeGitHub(), InMemoryDraftStore()
    worker = approval_worker(github, drafts)
    worker.process(make_job())
    github.head_sha = "newer"

    worker.process(make_job(head_sha=None, kind="approve", requested_by="maria"))

    assert github.reviews == []
    assert "has new commits" in github.issue_comments[-1]
    assert drafts.get("draft:acme/repo#7") is None


def test_approve_without_draft_explains():
    github = FakeGitHub()
    approval_worker(github, InMemoryDraftStore()).process(make_job(head_sha=None, kind="approve", requested_by="maria"))

    assert github.reviews == []
    assert "no AI review draft" in github.issue_comments[0]


def test_dismiss_discards_draft():
    github, drafts = FakeGitHub(), InMemoryDraftStore()
    worker = approval_worker(github, drafts)
    worker.process(make_job())

    worker.process(make_job(head_sha=None, kind="dismiss", requested_by="maria"))

    assert drafts.get("draft:acme/repo#7") is None
    assert github.issue_comments[-1] == "AI review draft dismissed by @maria."


def test_command_review_uses_current_head():
    github = FakeGitHub(head_sha="latest")
    make_worker(github).process(make_job(head_sha=None))

    assert github.reviews[0]["commit_id"] == "latest"


def http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status}", response=response)


def jobs_metric(outcome, kind="review"):
    return REGISTRY.get_sample_value("prr_review_jobs_total", {"kind": kind, "outcome": outcome}) or 0.0


def failing_worker(error, max_attempts=3):
    queue = InMemoryJobQueue()
    github = FakeGitHub()

    def fail(*args):
        raise error

    github.get_pull_request = fail
    worker = ReviewWorker(queue, github, ReviewAgent(ScriptedChatModel(responses=[])), max_attempts=max_attempts, retry_base_seconds=10)
    return worker, queue


def test_transient_failure_is_retried_with_backoff():
    worker, queue = failing_worker(http_error(502))
    before = jobs_metric("retry")

    worker.handle(make_job().model_copy(update={"attempt": 2}))

    [retry] = queue.scheduled
    assert retry.attempt == 3
    assert queue.dead == []
    assert jobs_metric("retry") == before + 1


def test_job_is_dead_lettered_after_last_attempt():
    worker, queue = failing_worker(RuntimeError("boom"), max_attempts=2)

    worker.handle(make_job().model_copy(update={"attempt": 2}))

    assert queue.scheduled == []
    [(job, error)] = queue.dead
    assert (job.delivery_id, error) == ("d1", "RuntimeError: boom")


@pytest.mark.parametrize("status", [404, 422])
def test_client_errors_are_not_retried(status):
    worker, queue = failing_worker(http_error(status))

    worker.handle(make_job())

    assert queue.scheduled == []
    assert len(queue.dead) == 1


def test_publish_with_unknown_outcome_is_not_retried():
    # A timeout on POST /reviews may still have created the review; retrying could post it twice.
    queue = InMemoryJobQueue()
    github = FakeGitHub()

    def timeout(*args):
        raise requests.Timeout("read timed out")

    github.create_review = timeout
    worker = ReviewWorker(queue, github, ReviewAgent(ScriptedChatModel(responses=[submit()])))

    worker.handle(make_job())

    assert queue.scheduled == []
    [(_, error)] = queue.dead
    assert error.startswith("PublishError")


def test_successful_review_is_counted():
    before = jobs_metric("success")
    worker = make_worker(FakeGitHub(), submit("ok", [finding(line=2)], tokens=(100, 20)))

    worker.handle(make_job())

    assert jobs_metric("success") == before + 1


def test_run_acks_every_job_even_when_it_fails():
    class AckingQueue(InMemoryJobQueue):
        acked = []

        def ack(self, job):
            self.acked.append(job.delivery_id)

    queue = AckingQueue()
    github = FakeGitHub()
    worker = ReviewWorker(queue, github, ReviewAgent(ScriptedChatModel(responses=[])))

    def failing_then_stop(*args):
        worker.stop()
        raise RuntimeError("GitHub is down")

    github.get_pull_request = failing_then_stop
    queue.enqueue(make_job())
    worker.run()

    assert queue.acked == ["d1"]
