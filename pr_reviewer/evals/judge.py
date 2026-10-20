"""LLM-as-judge: rates whether each review finding is useful.

"Useful" means a senior engineer would want the comment on the PR: it is
correct, specific to this change, and actionable. The judge also says which
expected issue (if any) a finding identifies, which catches matches that land
on a different line than the one the case author picked.
"""

from typing import Protocol

from langchain_core.language_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from pr_reviewer.evals.cases import EvalCase
from pr_reviewer.reviewer.diff import number_patch
from pr_reviewer.reviewer.schemas import ReviewFinding


class FindingVerdict(BaseModel):
    finding_index: int
    useful: bool = Field(description="True if a senior engineer would want this comment on the PR: correct, specific and actionable")
    matches_expected: str | None = Field(description="id of the expected issue this finding identifies, or null")
    reason: str = Field(description="One sentence justifying the verdict")


class JudgeResult(BaseModel):
    verdicts: list[FindingVerdict]


class Judge(Protocol):
    def judge(self, case: EvalCase, findings: list[ReviewFinding]) -> list[FindingVerdict]: ...


JUDGE_PROMPT = ChatPromptTemplate.from_messages([
    ("system", """You grade an AI code reviewer. For every finding, decide:
- useful: would a senior engineer want this exact comment on the PR? It must be technically
  correct, about the changed code, and actionable. Vague, wrong, nitpicky-without-value or
  duplicate comments are not useful.
- matches_expected: the id of the known issue the finding identifies, judged by meaning,
  not by exact line. null if it identifies none.
Return one verdict per finding, using its index."""),
    ("human", """## Pull request
{title}

## Diff
{diff}

## Known issues
{expected}

## Findings to grade
{findings}"""),
])


def _diff(case: EvalCase) -> str:
    return "\n\n".join(f"### {f.filename}\n{number_patch(f.patch)}" for f in case.files if f.patch)


class LLMJudge:
    def __init__(self, llm: BaseChatModel):
        self._chain = JUDGE_PROMPT | llm.with_structured_output(JudgeResult, method="json_schema", strict=True)

    def judge(self, case: EvalCase, findings: list[ReviewFinding]) -> list[FindingVerdict]:
        if not findings:
            return []
        result: JudgeResult = self._chain.invoke({
            "title": case.title,
            "diff": _diff(case),
            "expected": "\n".join(f"- {e.id} ({e.path}:{e.lines[0]}-{e.lines[1]}): {e.description}" for e in case.expected)
            or "(none: this PR has no known issues)",
            "findings": "\n".join(
                f"[{i}] {f.path}:{f.line} {f.severity}/{f.category}: {f.title}. {f.explanation}"
                for i, f in enumerate(findings)
            ),
        })
        return result.verdicts
