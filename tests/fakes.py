"""Test doubles shared across test modules."""

import posixpath
import re
from typing import Any

import requests
from langchain_core.embeddings import Embeddings
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


def tool_call(name: str, args: dict[str, Any], call_id: str = "call-1", tokens: tuple[int, int] | None = None) -> AIMessage:
    usage = {"input_tokens": tokens[0], "output_tokens": tokens[1], "total_tokens": sum(tokens)} if tokens else None
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": call_id}], usage_metadata=usage)


def submit(summary: str = "Looks fine.", findings: list[dict[str, Any]] | None = None, call_id: str = "submit", tokens=None) -> AIMessage:
    return tool_call(ReviewResult.__name__, {"summary": summary, "findings": findings or []}, call_id, tokens)


def finding(path: str = "app.py", line: int = 2, severity: str = "major", **overrides: Any) -> dict[str, Any]:
    return {
        "path": path,
        "line": line,
        "severity": severity,
        "category": "bug",
        "confidence": "high",
        "title": "Off-by-one",
        "explanation": "Loop skips the last item.",
        "suggestion": None,
        **overrides,
    }


class FakeRepo:
    """In-memory repository; listing a directory that doesn't exist raises like GitHub's 404."""

    def __init__(self, files: dict[str, str] | None = None):
        self.files = files or {}

    def read_file(self, path: str) -> str:
        return self.files[path]

    def list_directory(self, path: str) -> list[str]:
        entries = sorted(p for p in self.files if posixpath.dirname(p) == path)
        if path and not entries:
            raise requests.HTTPError(f"404 {path}")
        return entries


class KeywordEmbeddings(Embeddings):
    """Bag-of-words vectors over a fixed vocabulary, so similarity is predictable in tests."""

    def __init__(self, vocabulary: list[str]):
        self.vocabulary = vocabulary
        self.embedded: list[str] = []

    def _vector(self, text: str) -> list[float]:
        words = re.findall(r"[a-z_]+", text.lower())
        # Small constant dimension avoids zero vectors, which break cosine similarity.
        return [0.01] + [float(words.count(term)) for term in self.vocabulary]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self.embedded.extend(texts)
        return [self._vector(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._vector(text)
