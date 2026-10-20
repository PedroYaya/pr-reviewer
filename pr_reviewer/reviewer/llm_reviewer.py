"""LangChain pipeline that turns a pull request diff into review feedback."""

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from pr_reviewer.common.config import ReviewerSettings

SYSTEM_PROMPT = """You are an expert software engineer performing a code review.
Analyze the code changes in a pull request and give constructive feedback.

Focus on:
1. Code quality and best practices
2. Potential bugs or issues
3. Security concerns
4. Performance implications
5. Maintainability and readability

Be constructive and specific. Use markdown formatting."""

HUMAN_PROMPT = """Review the following pull request.

**PR Title:** {pr_title}
**PR Description:** {pr_description}

**Files Changed:**
{files_context}

Format your review as:

## 🤖 AI Code Review

### ✅ Positive Aspects
### ⚠️ Issues Found
### 🔧 Suggestions for Improvement
### 📝 Summary"""


def format_files_context(files: list[dict[str, Any]]) -> str:
    sections = []
    for file in files:
        lines = [
            f"**{file.get('filename', 'unknown')}** ({file.get('status', 'unknown')})",
            f"- Additions: +{file.get('additions', 0)}",
            f"- Deletions: -{file.get('deletions', 0)}",
        ]
        if patch := file.get("patch"):
            lines.append(f"```diff\n{patch}\n```")
        sections.append("\n".join(lines))
    return "\n\n".join(sections)


class LLMReviewer:
    """Stateless reviewer: each PR is reviewed on its own, with no shared memory."""

    def __init__(self, llm: BaseChatModel):
        prompt = ChatPromptTemplate.from_messages([("system", SYSTEM_PROMPT), ("human", HUMAN_PROMPT)])
        self._chain = prompt | llm | StrOutputParser()

    @classmethod
    def from_settings(cls, settings: ReviewerSettings) -> "LLMReviewer":
        llm = ChatOpenAI(
            model=settings.openai_model,
            temperature=settings.openai_temperature,
            api_key=settings.openai_api_key,
        )
        return cls(llm)

    def review(self, title: str, description: str, files: list[dict[str, Any]]) -> str:
        return self._chain.invoke(
            {
                "pr_title": title,
                "pr_description": description or "(no description)",
                "files_context": format_files_context(files),
            }
        )
