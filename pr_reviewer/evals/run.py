"""Run the eval suite against the real review pipeline.

    python -m pr_reviewer.evals.run                      # full pipeline vs baseline, with judge
    python -m pr_reviewer.evals.run --variant full --no-judge --case sql-injection

Writes a JSON report to evals/results/ and prints a comparison table. Needs
OPENAI_API_KEY; GitHub credentials are not used.

Real implementation in production: this public copy is sanitized, and the
production runs and their results live in a private company repository. Here
the suite is exercised with a mocked LLM in tests/test_evals.py.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from pr_reviewer.common.embedding_cache import CachedEmbeddings, InMemoryKeyValueStore
from pr_reviewer.evals.cases import DEFAULT_CASES_DIR, DictRepoReader, EvalCase, load_cases
from pr_reviewer.evals.judge import Judge, LLMJudge
from pr_reviewer.evals.scoring import CaseScore, score_case, summarize
from pr_reviewer.reviewer.agent import ReviewAgent
from pr_reviewer.reviewer.pipeline import ConventionsLoader, PipelineOptions, run_review_pipeline
from pr_reviewer.reviewer.retrieval import ConventionIndex

VARIANTS = {"full": PipelineOptions(), "baseline": PipelineOptions.baseline()}
DEFAULT_RESULTS_DIR = DEFAULT_CASES_DIR.parent / "results"

REPORT_ROWS = [
    ("useful_rate", "Useful findings (judge)"),
    ("recall_judge", "Expected issues found (judge)"),
    ("recall_location", "Expected issues found (location)"),
    ("precision_location", "Findings on an expected issue"),
    ("findings_on_clean_cases", "Findings on clean PRs"),
    ("avg_input_tokens", "Avg input tokens"),
    ("avg_output_tokens", "Avg output tokens"),
    ("avg_total_tokens", "Avg total tokens"),
    ("avg_llm_calls", "Avg LLM calls"),
    ("avg_tool_calls", "Avg tool calls"),
    ("avg_seconds", "Avg seconds per case"),
    ("guardrail_dropped", "Findings dropped by guardrails"),
    ("errors", "Errors"),
]


class EvalSettings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    openai_api_key: SecretStr
    openai_model: str = "gpt-4o"
    openai_temperature: float = 0.2
    openai_embedding_model: str = "text-embedding-3-small"
    openai_judge_model: str = "gpt-4o"
    openai_max_retries: int = 4


def conventions_loader(case: EvalCase, embeddings: Embeddings | None) -> ConventionsLoader | None:
    if not case.conventions or embeddings is None:
        return None
    documents = [Document(c.text, metadata={"kind": c.kind, "source": c.source}) for c in case.conventions]
    return lambda _repo: ConventionIndex.build(embeddings, documents)


def run_case(
    case: EvalCase,
    agent: ReviewAgent,
    options: PipelineOptions,
    embeddings: Embeddings | None = None,
    judge: Judge | None = None,
) -> CaseScore:
    started = time.perf_counter()
    try:
        output = run_review_pipeline(
            agent, case.title, case.description, case.github_files(), DictRepoReader(case.repo_files),
            options, conventions_loader(case, embeddings),
        )
        findings = output.result.findings if output else []
        verdicts = judge.judge(case, findings) if judge else None
    except Exception as error:  # one broken case must not abort the suite
        return CaseScore(case.id, len(case.expected), 0, set(), 0, seconds=time.perf_counter() - started, error=repr(error))

    score = score_case(case, findings, verdicts)
    score.seconds = round(time.perf_counter() - started, 2)
    if output:
        score.input_tokens = output.run.input_tokens
        score.output_tokens = output.run.output_tokens
        score.llm_calls = output.run.llm_calls
        score.tool_calls = output.run.tool_calls
        score.dropped = len(output.dropped)
    return score


def run_suite(cases, agent, options, embeddings=None, judge=None, repeat=1, progress=None) -> list[CaseScore]:
    scores = []
    for _ in range(repeat):
        for case in cases:
            score = run_case(case, agent, options, embeddings, judge)
            if progress:
                progress(score)
            scores.append(score)
    return scores


def format_report(summaries: dict[str, dict]) -> str:
    variants = list(summaries)
    lines = ["| Metric | " + " | ".join(variants) + " |", "|---|" + "---|" * len(variants)]
    for key, label in REPORT_ROWS:
        values = [summaries[v].get(key) for v in variants]
        if all(value is None for value in values):
            continue
        cells = [
            f"{value:.0%}" if isinstance(value, float) and key.startswith(("useful", "recall", "precision")) else str(value)
            for value in values
        ]
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _score_json(score: CaseScore) -> dict:
    data = {k: v for k, v in vars(score).items()}
    data["location_matched"] = sorted(score.location_matched)
    data["judge_matched"] = sorted(score.judge_matched) if score.judge_matched is not None else None
    return data


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--variant", action="append", choices=sorted(VARIANTS), help="Repeatable; default: full and baseline")
    parser.add_argument("--case", action="append", help="Only run these case ids (repeatable)")
    parser.add_argument("--no-judge", action="store_true", help="Skip the LLM judge (no useful_rate)")
    parser.add_argument("--repeat", type=int, default=1, help="Run each case N times to average out sampling noise")
    parser.add_argument("--cases-dir", type=Path, default=DEFAULT_CASES_DIR)
    parser.add_argument("--out", type=Path, default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--fail-under-useful", type=float, help="Exit 1 if the first variant's useful_rate is lower")
    parser.add_argument("--fail-under-recall", type=float, help="Exit 1 if the first variant's recall is lower")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    settings = EvalSettings()
    cases = load_cases(args.cases_dir)
    if args.case:
        cases = [c for c in cases if c.id in set(args.case)]
    variants = args.variant or ["full", "baseline"]

    agent = ReviewAgent(ChatOpenAI(
        model=settings.openai_model, temperature=settings.openai_temperature,
        api_key=settings.openai_api_key, max_retries=settings.openai_max_retries,
    ))
    # Shared in-memory cache: variants and repeats don't re-embed the same conventions.
    embeddings = CachedEmbeddings(
        OpenAIEmbeddings(
            model=settings.openai_embedding_model,
            api_key=settings.openai_api_key,
            max_retries=settings.openai_max_retries,
        ),
        InMemoryKeyValueStore(), settings.openai_embedding_model, ttl_seconds=0,
    )
    judge = None if args.no_judge else LLMJudge(
        ChatOpenAI(model=settings.openai_judge_model, temperature=0, api_key=settings.openai_api_key,
                   max_retries=settings.openai_max_retries)
    )

    summaries, details = {}, {}
    for variant in variants:
        print(f"\n== {variant} ({len(cases)} cases x {args.repeat}) ==")
        scores = run_suite(
            cases, agent, VARIANTS[variant], embeddings, judge, args.repeat,
            progress=lambda s: print(f"  {s.case_id:<32} findings={s.findings:<3} matched={len(s.location_matched)}/{s.expected}"
                                     + (f"  ERROR {s.error}" if s.error else "")),
        )
        summaries[variant] = summarize(scores)
        details[variant] = [_score_json(s) for s in scores]

    report = format_report(summaries)
    print("\n" + report)

    args.out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = args.out / f"{stamp}.json"
    path.write_text(json.dumps({
        "created_at": stamp,
        "models": {"review": settings.openai_model, "judge": None if args.no_judge else settings.openai_judge_model,
                   "embeddings": settings.openai_embedding_model},
        "repeat": args.repeat,
        "summaries": summaries,
        "cases": details,
    }, indent=2))
    print(f"\nFull results: {path}")

    first = summaries[variants[0]]
    if args.fail_under_useful is not None and (first.get("useful_rate") or 0) < args.fail_under_useful:
        print(f"FAIL: useful_rate {first.get('useful_rate')} < {args.fail_under_useful}")
        return 1
    if args.fail_under_recall is not None and (first.get("recall_location") or 0) < args.fail_under_recall:
        print(f"FAIL: recall {first.get('recall_location')} < {args.fail_under_recall}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
