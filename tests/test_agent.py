from langchain_core.messages import ToolMessage

from pr_reviewer.reviewer.agent import SUBMIT_TOOL, ReviewAgent, format_files_context
from pr_reviewer.reviewer.repo_tools import MAX_FILE_CHARS
from tests.fakes import FakeRepo, ScriptedChatModel, finding, submit, tool_call

FILES = [{"filename": "app.py", "status": "modified", "additions": 1, "deletions": 0, "patch": "@@ -1,1 +1,2 @@\n x = 1\n+y = x / 0"}]


def run(responses, repo=None, max_tool_rounds=5):
    model = ScriptedChatModel(responses=responses)
    result = ReviewAgent(model, max_tool_rounds=max_tool_rounds).review("Title", "Body", FILES, repo or FakeRepo())
    return result, model


def tool_messages(model, call_index):
    return [m for m in model.received[call_index] if isinstance(m, ToolMessage)]


def test_returns_structured_result_from_submit_tool():
    result, model = run([submit("Divides by zero.", [finding(line=2, severity="critical")])])

    assert result.summary == "Divides by zero."
    assert result.findings[0].line == 2
    assert result.findings[0].severity == "critical"
    assert len(model.received) == 1


def test_uses_strict_tools_without_parallel_calls():
    _, model = run([submit()])

    bind = model.bind_calls[0]
    assert bind["tools"] == ["read_file", "list_directory", SUBMIT_TOOL]
    assert bind["strict"] is True
    assert bind["parallel_tool_calls"] is False
    assert bind["tool_choice"] == "required"


def test_feeds_tool_results_back_before_submitting():
    repo = FakeRepo({"util.py": "def helper(): ..."})
    result, model = run([tool_call("read_file", {"path": "util.py"}, "c1"), submit()], repo)

    [message] = tool_messages(model, 1)
    assert message.tool_call_id == "c1"
    assert message.content == "def helper(): ..."
    assert result.findings == []


def test_forces_submit_when_tool_budget_is_exhausted():
    responses = [tool_call("list_directory", {"path": ""}, f"c{i}") for i in range(2)] + [submit("Forced.")]
    result, model = run(responses, max_tool_rounds=2)

    assert result.summary == "Forced."
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


def test_prompt_contains_numbered_diff():
    context = format_files_context(FILES)

    assert "### app.py (modified, +1 -0)" in context
    assert "    2 +y = x / 0" in context
