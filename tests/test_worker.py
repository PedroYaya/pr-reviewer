from pr_reviewer.common.models import ReviewJob
from pr_reviewer.common.queue import InMemoryJobQueue
from pr_reviewer.reviewer.agent import ReviewAgent
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

    def create_review(self, installation_id, owner, repo, number, commit_id, body, comments):
        self.reviews.append({"commit_id": commit_id, "body": body, "comments": comments})
        return {"id": 1}


def make_job(head_sha="abc123"):
    return ReviewJob(
        delivery_id="d1", installation_id=42, owner="acme", repo="repo",
        pr_number=7, head_sha=head_sha, action="opened",
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
