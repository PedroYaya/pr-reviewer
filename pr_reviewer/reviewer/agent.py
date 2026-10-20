"""Tool-calling review agent built on LangChain.

The model explores the repository with read-only tools, then finishes by
calling the ``ReviewResult`` tool, whose arguments are a strict structured
output validated with Pydantic.
"""

import logging
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, ToolMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from pr_reviewer.common.config import ReviewerSettings
from pr_reviewer.reviewer.diff import number_patch
from pr_reviewer.reviewer.repo_tools import RepoReader, make_repo_tools
from pr_reviewer.reviewer.schemas import ReviewResult

logger = logging.getLogger(__name__)

MAX_TOOL_ROUNDS = 5
SUBMIT_TOOL = ReviewResult.__name__

SYSTEM_PROMPT = """You are an expert software engineer reviewing a GitHub pull request.

Report only real problems in the changed code: bugs, security issues, performance
problems, missing tests, and maintainability issues worth a reviewer's time.
Do not praise, restate the diff, or report issues in unchanged code.

Each diff line is prefixed with its line number in the new file. Cite that number
in findings; removed lines have no number and cannot be commented on.

If the diff alone is not enough to judge a change, use read_file or list_directory
to look at surrounding code. When you are done, call {submit_tool} exactly once."""

HUMAN_PROMPT = """**PR Title:** {pr_title}
**PR Description:** {pr_description}

**Files Changed:**
{files_context}"""

PROMPT = ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("human", HUMAN_PROMPT)])


def format_files_context(files: list[dict[str, Any]]) -> str:
    sections = []
    for file in files:
        header = f"### {file.get('filename', 'unknown')} ({file.get('status', 'unknown')}, +{file.get('additions', 0)} -{file.get('deletions', 0)})"
        patch = file.get("patch")
        body = f"```diff\n{number_patch(patch)}\n```" if patch else "(no textual diff: binary or too large)"
        sections.append(f"{header}\n{body}")
    return "\n\n".join(sections)


class ReviewAgent:
    """Stateless agent: each PR is reviewed on its own, with no shared memory."""

    def __init__(self, llm: BaseChatModel, max_tool_rounds: int = MAX_TOOL_ROUNDS):
        self._llm = llm
        self._max_tool_rounds = max_tool_rounds

    @classmethod
    def from_settings(cls, settings: ReviewerSettings) -> "ReviewAgent":
        llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=settings.openai_temperature,
            api_key=settings.openai_api_key,
        )
        return cls(llm)

    def review(self, title: str, description: str, files: list[dict[str, Any]], repo: RepoReader) -> ReviewResult:
        messages: list[BaseMessage] = PROMPT.format_messages(
            submit_tool=SUBMIT_TOOL,
            pr_title=title,
            pr_description=description or "(no description)",
            files_context=format_files_context(files),
        )
        tools = {t.name: t for t in make_repo_tools(repo)}
        # Strict structured outputs don't support parallel tool calls.
        explorer = self._llm.bind_tools(
            [*tools.values(), ReviewResult], tool_choice="required", strict=True, parallel_tool_calls=False
        )

        for _ in range(self._max_tool_rounds):
            response = explorer.invoke(messages)
            messages.append(response)
            for call in response.tool_calls:
                if call["name"] == SUBMIT_TOOL:
                    return ReviewResult.model_validate(call["args"])
                messages.append(self._run_tool(tools, call))

        logger.info("Tool budget exhausted after %d rounds; forcing final review", self._max_tool_rounds)
        finisher = self._llm.bind_tools([ReviewResult], tool_choice=SUBMIT_TOOL, strict=True, parallel_tool_calls=False)
        response = finisher.invoke(messages)
        return ReviewResult.model_validate(response.tool_calls[0]["args"])

    @staticmethod
    def _run_tool(tools: dict, call: dict) -> ToolMessage:
        selected = tools.get(call["name"])
        if selected is None:
            content = f"Unknown tool '{call['name']}'"
        else:
            content = selected.invoke(call["args"])
        return ToolMessage(content=content, tool_call_id=call["id"])
