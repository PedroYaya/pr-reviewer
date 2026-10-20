"""Test doubles shared across test modules."""

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic import Field

from pr_reviewer.reviewer.schemas import ReviewResult


class ScriptedChatModel(BaseChatModel):
    """Chat model that replays scripted responses and records what it was sent."""

    responses: list[AIMessage]
    received: list[list[Any]] = Field(default_factory=list)
    bind_calls: list[dict[str, Any]] = Field(default_factory=list)

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.received.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=self.responses.pop(0))])

    def bind_tools(self, tools, **kwargs):
        self.bind_calls.append({"tools": [getattr(t, "name", getattr(t, "__name__", t)) for t in tools], **kwargs})
        return self


def tool_call(name: str, args: dict[str, Any], call_id: str = "call-1") -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}])


def submit(summary: str = "Looks fine.", findings: list[dict[str, Any]] | None = None, call_id: str = "submit") -> AIMessage:
    return tool_call(ReviewResult.__name__, {"summary": summary, "findings": findings or []}, call_id)


def finding(path: str = "app.py", line: int = 2, severity: str = "major", **overrides: Any) -> dict[str, Any]:
    return {
        "path": path,
        "line": line,
        "severity": severity,
        "category": "bug",
        "title": "Off-by-one",
        "explanation": "Loop skips the last item.",
        "suggestion": None,
        **overrides,
    }


class FakeRepo:
    def __init__(self, files: dict[str, str] | None = None):
        self.files = files or {}

    def read_file(self, path: str) -> str:
        return self.files[path]

    def list_directory(self, path: str) -> list[str]:
        return sorted(self.files)
