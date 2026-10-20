from langchain_core.documents import Document
from langchain_core.messages import ToolMessage

from pr_reviewer.reviewer.agent import SUBMIT_TOOL, ReviewAgent, format_files_context
from pr_reviewer.reviewer.budget import OmittedFile
from pr_reviewer.reviewer.repo_tools import MAX_FILE_CHARS
from pr_reviewer.reviewer.retrieval import ConventionIndex
from tests.fakes import FakeRepo, KeywordEmbeddings, ScriptedChatModel, finding, submit, tool_call

FILES = [{"filename": "app.py", "status": "modified", "additions": 1, "deletions": 0, "patch": "@@ -1,1 +1,2 @@\n x = 1\n+y = x / 0"}]


def run(responses, repo=None, max_tool_rounds=5, **review_kwargs):
    model = ScriptedChatModel(responses=responses)
    agent = ReviewAgent(model, max_tool_rounds=max_tool_rounds)
    review = agent.review("Title", "Body", FILES, repo or FakeRepo(), **review_kwargs)
    return review, model


def tool_messages(model, call_index):
    return [m for m in model.received[call_index] if isinstance(m, ToolMessage)]


def prompt_text(model):
    return model.received[0][1].content


def test_returns_structured_result_from_submit_tool():
    review, model = run([submit("Divides by zero.", [finding(line=2, severity="critical")])])

    assert review.result.summary == "Divides by zero."
    assert review.result.findings[0].line == 2
    assert review.result.findings[0].severity == "critical"
    assert review.llm_calls == 1


def test_uses_strict_tools_without_parallel_calls():
    _, model = run([submit()])

    bind = model.bind_calls[0]
    assert bind["tools"] == ["read_file", "list_directory", SUBMIT_TOOL]
    assert bind["strict"] is True
    assert bind["parallel_tool_calls"] is False
    assert bind["tool_choice"] == "required"


def test_feeds_tool_results_back_before_submitting():
    repo = FakeRepo({"util.py": "def helper(): ..."})
    review, model = run([tool_call("read_file", {"path": "util.py"}, "c1"), submit()], repo)

    [message] = tool_messages(model, 1)
    assert message.tool_call_id == "c1"
    assert message.content == "def helper(): ..."
    assert review.tool_calls == 1


def test_forces_submit_when_tool_budget_is_exhausted():
    responses = [tool_call("list_directory", {"path": ""}, f"c{i}") for i in range(2)] + [submit("Forced.")]
    review, model = run(responses, max_tool_rounds=2)

    assert review.result.summary == "Forced."
    assert model.bind_calls[-1]["tools"] == [SUBMIT_TOOL]
    assert model.bind_calls[-1]["tool_choice"] == SUBMIT_TOOL


def test_unknown_tool_gets_error_message():
    _, model = run([tool_call("delete_repo", {}, "c1"), submit()])

    [message] = tool_messages(model, 1)
    assert "Unknown tool" in message.content


def test_large_files_are_truncated():
    repo = FakeRepo({"big.py": "x" * (MAX_FILE_CHARS + 10)})
    _, model = run([tool_call("read_file", {"path": "big.py"}), submit()], repo)

    [message] = tool_messages(model, 1)
    assert message.content.endswith(f"[truncated, {MAX_FILE_CHARS + 10} chars total]")


def test_sums_token_usage_across_calls():
    review, _ = run([tool_call("list_directory", {"path": ""}, tokens=(1000, 50)), submit(tokens=(1200, 300))])

    assert (review.input_tokens, review.output_tokens, review.llm_calls) == (2200, 350, 2)


def test_injects_relevant_conventions_and_search_tool():
    index = ConventionIndex.build(
        KeywordEmbeddings(["division", "logging"]),
        [
            Document("Guard every division against zero.", metadata={"kind": "guideline", "source": "CONTRIBUTING.md"}),
            Document("Use structured logging.", metadata={"kind": "guideline", "source": "STYLEGUIDE.md"}),
        ],
    )
    files_about_division = [{**FILES[0], "patch": FILES[0]["patch"] + "\n+# division"}]
    model = ScriptedChatModel(responses=[tool_call("search_conventions", {"query": "logging"}, "c1"), submit()])
    ReviewAgent(model, conventions_top_k=1).review("T", "B", files_about_division, FakeRepo(), conventions=index)

    assert "[guideline: CONTRIBUTING.md]" in prompt_text(model)
    assert "STYLEGUIDE.md" not in prompt_text(model)
    assert "search_conventions" in model.bind_calls[0]["tools"]
    [message] = tool_messages(model, 1)
    assert message.content.startswith("[guideline: STYLEGUIDE.md]")


def test_prompt_without_conventions_or_omitted_files():
    _, model = run([submit()])

    assert "(no team conventions found)" in prompt_text(model)
    assert "**Files not included above:**\n(none)" in prompt_text(model)


def test_prompt_lists_omitted_files():
    _, model = run([submit()], omitted=[OmittedFile("poetry.lock", "lock file or generated code")])

    assert "- poetry.lock: lock file or generated code" in prompt_text(model)


def test_prompt_contains_numbered_diff():
    context = format_files_context([*FILES, {**FILES[0], "filename": "big.py", "truncated": True}])

    assert "### app.py (modified, +1 -0)" in context
    assert "    2 +y = x / 0" in context
    assert "### big.py (modified, +1 -0, diff truncated)" in context
