"""Tool-calling review agent built on LangChain.

The model explores the repository with read-only tools, then finishes by
calling the ``ReviewResult`` tool, whose arguments are a strict structured
output validated with Pydantic.
"""

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from pr_reviewer.common.config import ReviewerSettings
from pr_reviewer.reviewer.budget import OmittedFile
from pr_reviewer.reviewer.diff import number_patch
from pr_reviewer.reviewer.repo_tools import RepoReader, make_repo_tools
from pr_reviewer.reviewer.retrieval import ConventionIndex, format_documents, make_convention_tool
from pr_reviewer.reviewer.schemas import ReviewResult

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5
CONVENTIONS_TOP_K = 6
SUBMIT_TOOL = ReviewResult.__name__

SYSTEM_PROMPT = """You are an expert software engineer reviewing a GitHub pull request.

Report only real problems in the changed code: bugs, security issues, performance
problems, missing tests, and maintainability issues worth a reviewer's time.
Do not praise, restate the diff, or report issues in unchanged code.

Each diff line is prefixed with its line number in the new file. Cite that number
in findings; removed lines have no number and cannot be commented on.

Team conventions, when provided, are this team's rules: flag changes that break
them and name the convention in the explanation. Do not invent rules they don't state.

If the diff alone is not enough to judge a change, use the tools to look at
surrounding code or search the conventions. When you are done, call {submit_tool}
exactly once."""

HUMAN_PROMPT = """**PR Title:** {pr_title}
**PR Description:** {pr_description}

**Team conventions relevant to this change:**
{conventions_context}

**Files Changed:**
{files_context}

**Files not included above:**
{omitted_context}"""

PROMPT = ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("human", HUMAN_PROMPT)])


@dataclass
class ReviewRun:
    result: ReviewResult
    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0
    tool_calls: int = 0


def format_files_context(files: list[dict[str, Any]]) -> str:
    sections = []
    for file in files:
        notes = f", +{file.get('additions', 0)} -{file.get('deletions', 0)}"
        if file.get("truncated"):
            notes += ", diff truncated"
        header = f"### {file.get('filename', 'unknown')} ({file.get('status', 'unknown')}{notes})"
        sections.append(f"{header}\n```diff\n{number_patch(file['patch'])}\n```")
    return "\n\n".join(sections)


def format_omitted(omitted: Sequence[OmittedFile]) -> str:
    return "\n".join(f"- {o.filename}: {o.reason}" for o in omitted) or "(none)"


class ReviewAgent:
    """Stateless agent: each PR is reviewed on its own, with no shared memory."""

    def __init__(self, llm: BaseChatModel, max_tool_rounds: int = MAX_TOOL_ROUNDS, conventions_top_k: int = CONVENTIONS_TOP_K):
        self._llm = llm
        self._max_tool_rounds = max_tool_rounds
        self._conventions_top_k = conventions_top_k

    @classmethod
    def from_settings(cls, settings: ReviewerSettings) -> "ReviewAgent":
        llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=settings.openai_temperature,
            api_key=settings.openai_api_key,
        )
        return cls(llm, conventions_top_k=settings.conventions_top_k)

    def review(
        self,
        title: str,
        description: str,
        files: list[dict[str, Any]],
        repo: RepoReader,
        conventions: ConventionIndex | None = None,
        omitted: Sequence[OmittedFile] = (),
    ) -> ReviewRun:
        conventions_context = "(no team conventions found)"
        tool_list = make_repo_tools(repo)
        if conventions is not None:
            conventions_context = format_documents(conventions.relevant_to(files, self._conventions_top_k))
            tool_list.append(make_convention_tool(conventions))

        messages: list[BaseMessage] = PROMPT.format_messages(
            submit_tool=SUBMIT_TOOL,
            pr_title=title,
            pr_description=description or "(no description)",
            conventions_context=conventions_context,
            files_context=format_files_context(files),
            omitted_context=format_omitted(omitted),
        )
        tools = {t.name: t for t in tool_list}
        run = ReviewRun(result=ReviewResult(summary="", findings=[]))
        # Strict structured outputs don't support parallel tool calls.
        explorer = self._llm.bind_tools(
            [*tools.values(), ReviewResult], tool_choice="required", strict=True, parallel_tool_calls=False
        )

        for _ in range(self._max_tool_rounds):
            response = self._invoke(explorer, messages, run)
            for call in response.tool_calls:
                if call["name"] == SUBMIT_TOOL:
                    run.result = ReviewResult.model_validate(call["args"])
                    return run
                run.tool_calls += 1
                messages.append(self._run_tool(tools, call))

        logger.info("Tool budget exhausted after %d rounds; forcing final review", self._max_tool_rounds)
        finisher = self._llm.bind_tools([ReviewResult], tool_choice=SUBMIT_TOOL, strict=True, parallel_tool_calls=False)
        response = self._invoke(finisher, messages, run)
        run.result = ReviewResult.model_validate(response.tool_calls[0]["args"])
        return run

    @staticmethod
    def _invoke(model, messages: list[BaseMessage], run: ReviewRun) -> AIMessage:
        response = model.invoke(messages)
        messages.append(response)
        run.llm_calls += 1
        if usage := response.usage_metadata:
            run.input_tokens += usage["input_tokens"]
            run.output_tokens += usage["output_tokens"]
        return response

    @staticmethod
    def _run_tool(tools: dict, call: dict) -> ToolMessage:
        selected = tools.get(call["name"])
        if selected is None:
            content = f"Unknown tool '{call['name']}'"
        else:
            content = selected.invoke(call["args"])
        return ToolMessage(content=content, tool_call_id=call["id"])
