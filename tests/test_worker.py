from langchain_core.language_models.fake_chat_models import FakeListChatModel

from pr_reviewer.common.models import ReviewJob
from pr_reviewer.common.queue import InMemoryJobQueue
from pr_reviewer.reviewer.llm_reviewer import LLMReviewer, format_files_context
from pr_reviewer.reviewer.worker import ReviewWorker

FILES = [{"filename": "app.py", "status": "modified", "additions": 1, "deletions": 0, "patch": "+print('hi')"}]


class FakeGitHub:
    def __init__(self, head_sha="abc123", files=FILES):
        self.head_sha = head_sha
        self.files = files
        self.comments = []

    def get_pull_request(self, installation_id, owner, repo, number):
        return {"title": "Add greeting", "body": None, "head": {"sha": self.head_sha}}

    def list_pull_request_files(self, installation_id, owner, repo, number):
        return self.files

    def create_issue_comment(self, installation_id, owner, repo, number, body):
        self.comments.append(body)
        return {"id": 1}


def make_job(head_sha="abc123"):
    return ReviewJob(
        delivery_id="d1", installation_id=42, owner="acme", repo="repo",
        pr_number=7, head_sha=head_sha, action="opened",
    )


def make_worker(github, responses=("Looks good",)):
    reviewer = LLMReviewer(FakeListChatModel(responses=list(responses)))
    return ReviewWorker(InMemoryJobQueue(), github, reviewer)


def test_posts_review_comment():
    github = FakeGitHub()
    make_worker(github).process(make_job())

    assert github.comments == ["Looks good"]


def test_skips_job_for_outdated_commit():
    github = FakeGitHub(head_sha="newer")
    make_worker(github).process(make_job(head_sha="abc123"))

    assert github.comments == []


def test_skips_pull_request_without_files():
    github = FakeGitHub(files=[])
    make_worker(github).process(make_job())

    assert github.comments == []


def test_reviews_are_independent():
    # Regression: the old reviewer shared LangChain memory across every PR.
    github = FakeGitHub()
    worker = make_worker(github, responses=("first", "second"))
    worker.process(make_job())
    worker.process(make_job())

    assert github.comments == ["first", "second"]


def test_run_survives_failed_job():
    queue = InMemoryJobQueue()
    github = FakeGitHub()
    worker = ReviewWorker(queue, github, LLMReviewer(FakeListChatModel(responses=["ok"])))

    def failing_then_stop(*args):
        worker.stop()
        raise RuntimeError("GitHub is down")

    github.get_pull_request = failing_then_stop
    queue.enqueue(make_job())
    worker.run()  # must return instead of raising

    assert github.comments == []


def test_files_context_includes_patch():
    context = format_files_context(FILES)

    assert "**app.py** (modified)" in context
    assert "+print('hi')" in context
