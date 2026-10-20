# GitHub App PR Reviewer

An AI pull request reviewer delivered as a GitHub App. It runs as two Python microservices built with FastAPI, connected by a Redis queue, and uses LangChain and OpenAI to write the review.

## Architecture

```
GitHub ──webhook──▶ gateway (FastAPI) ──job──▶ Redis queue ──▶ reviewer (FastAPI + worker)
                    verify signature                            fetch PR files, apply token budget
                    filter events                               retrieve team conventions (RAG)
                    respond 202 right away                      review with LangChain + OpenAI
                                                                post review with inline comments
```

- **gateway** (`pr_reviewer/gateway`): receives GitHub webhooks, checks the `X-Hub-Signature-256` HMAC, keeps only reviewable PR events (`opened`, `synchronize`, `reopened`, `ready_for_review`, never drafts) and queues a `ReviewJob`. GitHub stops waiting for a webhook after 10 seconds, so this service never calls the LLM.
- **reviewer** (`pr_reviewer/reviewer`): a background worker takes jobs from the queue, skips any job whose commit is no longer the PR head, runs the review agent and posts the result. Its `/health` endpoint reports whether the worker is still running.
- **common** (`pr_reviewer/common`): settings, the GitHub App client (JWT, a cached token per installation, paginated file lists), the queue and the shared job model.

Each review is stateless. No context is shared between PRs.

### Review agent

1. **Token budget** (`reviewer/budget.py`): lock files, generated code, deleted files and binaries are skipped. Each patch is capped at `FILE_TOKEN_BUDGET` tokens, and files are admitted smallest first until `DIFF_TOKEN_BUDGET` is used up. The review body lists every file that was left out and why. Token usage reported by OpenAI is logged for every review.
2. **RAG over conventions** (`reviewer/conventions.py`, `reviewer/retrieval.py`): two sources are indexed in a vector store with OpenAI embeddings (`text-embedding-3-small`). The first is guideline files in the repo (`CONTRIBUTING.md`, `STYLEGUIDE.md`, `REVIEW_GUIDELINES.md`, `AGENTS.md`, … in the root, `.github/` or `docs/`), split by markdown section. The second is the last 100 human review comments on the repo's PRs, together with the code they were about. For each changed file the top matches go into the prompt, and the agent also has a `search_conventions` tool. Embeddings are cached in Redis by content hash, so later reviews of the same repo hardly re-embed anything. If loading conventions fails, the review goes ahead without them.
3. **Numbered diff** (`reviewer/diff.py`): each diff line in the prompt starts with its line number in the new file, so the model can point to exact lines.
4. **Tool calling** (`reviewer/agent.py`, `reviewer/repo_tools.py`): the model can call `read_file`, `list_directory` and `search_conventions` to read the repository at the PR's head commit, for up to 5 rounds. Tool results are capped at 20k characters.
5. **Structured output** (`reviewer/schemas.py`): the model finishes by calling the `ReviewResult` tool. OpenAI strict mode constrains its arguments to the schema, and Pydantic validates them: a summary plus findings with `path`, `line`, `severity`, `category`, `title`, `explanation` and `suggestion`. If the model uses up the tool rounds, `ReviewResult` is forced.
6. **Publishing** (`reviewer/publisher.py`): findings become a GitHub pull request review, ordered by severity. Findings on lines that are in the diff become inline comments. Findings on other lines go in the review body, because a single invalid line makes GitHub reject the whole review with a 422.

### Guardrails

- **Secrets never reach the LLM** (`reviewer/guardrails.py`): AWS, GitHub, OpenAI and Slack tokens, private key blocks, and quoted values assigned to names like `*password*`, `*secret*`, `*api_key*` or `*token*` are redacted from the diff and from every file the agent reads. Redaction keeps the line count, so diff line numbers stay valid. Each secret on an added line becomes a deterministic critical security finding.
- **Prompt injection**: the PR title, description, diff and conventions go to the model inside `<untrusted>` blocks. The system prompt tells it to treat them as data, and any `<untrusted>` tag inside that content is escaped so it can't close the block early.
- **Output filtering**: findings are dropped when they point at a file outside the reviewed diff, have low confidence or repeat another finding at the same location and category. Whatever remains is capped at `MAX_FINDINGS`, keeping the most severe. Every dropped finding is logged with the reason.

### Human-in-the-loop

| Comment on a PR | Effect |
|---|---|
| `/ai-review` | Review the current head commit now |
| `/ai-review approve` | Publish the pending draft (approval mode) |
| `/ai-review dismiss` | Discard the pending draft |

Commands are only accepted from users whose association with the repo is `OWNER`, `MEMBER` or `COLLABORATOR`, and comments from bots are ignored. With `REVIEW_MODE=approval`, the bot doesn't publish anything on its own. It posts a draft comment with a table of findings, and the review is published only when a maintainer approves it. If new commits arrive after the draft was made, approving it is refused.

## Reliability

Retries happen at two levels.

- **Per call.** The OpenAI SDK retries 429, 5xx and connection errors with exponential backoff and honours `Retry-After` (`OPENAI_MAX_RETRIES`, `OPENAI_TIMEOUT_SECONDS`). GitHub calls go through a tenacity policy (`common/retry.py`): rate limits (429, or 403 with `Retry-After` or `x-ratelimit-remaining: 0`) wait as long as GitHub asks, capped at 60 s, and are retried for any method, because GitHub never processed the request. Timeouts, connection errors and 5xx are retried with jittered backoff, but only for GETs. A POST that timed out may already have created the review.
- **Per job.** If a job still fails, the worker puts it in a Redis sorted set (`<queue>:delayed`) to run again after 30 s, then 120 s (`JOB_RETRY_BASE_SECONDS × 4ⁿ`). After `JOB_MAX_ATTEMPTS` it goes to `<queue>:dead` along with the error. Failures a retry can't fix go straight to the dead-letter list: 4xx other than 408/409/429, such as a deleted PR or a 422 on the review. So does a timeout or 5xx while posting the review, so that it's never posted twice. Several workers can share the queue: `ZREM` makes sure only one of them takes each due retry.

```bash
redis-cli LRANGE pr-review-jobs:dead 0 -1   # each entry: {"job": …, "error": …, "failed_at": …}
```

To replay a dead job, push its `job` field back onto `pr-review-jobs`.

## Observability

- **Logs** are JSON lines (`LOG_FORMAT=json`, or `text` locally). Every line written while a webhook or job is handled carries `delivery_id`, `pr`, `kind` and `attempt`, plus `trace_id` and `span_id` when tracing is on.
- **Metrics**: both services serve Prometheus metrics on `/metrics`.

| Metric | What it answers |
|---|---|
| `prr_review_jobs_total{kind,outcome}` | Successful run rate: `success / (success + dead_letter)`. `retry` counts retried attempts and `skipped` counts stale commits or nothing to review |
| `prr_review_job_duration_seconds`, `prr_queue_wait_seconds` | Time from push to review, and where it goes |
| `prr_llm_tokens_total{type}`, `prr_llm_calls_total`, `prr_agent_tool_calls_total` | Token use and cost per review |
| `prr_findings_total{severity}`, `prr_guardrail_dropped_findings_total{reason}`, `prr_secrets_redacted_total` | What the reviews contain and what the guardrails remove |
| `prr_http_retries_total{service,reason}`, `prr_webhooks_total{event,outcome}` | GitHub rate limits and failures, and incoming traffic |

```promql
sum(rate(prr_review_jobs_total{outcome="success"}[1d]))
  / sum(rate(prr_review_jobs_total{outcome=~"success|dead_letter"}[1d]))
```

- **Traces** (OpenTelemetry): set `OTEL_EXPORTER_OTLP_ENDPOINT` and install the `otel` extra. The gateway puts the W3C `traceparent` into each job, so one trace covers the webhook, the review job and its spans: `github.*`, `conventions.load`, `agent.review`, each `llm.invoke` (with token counts) and each `agent.tool`. Without an endpoint, the OpenTelemetry API is a no-op.

## Setup

```bash
python3.11 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp env.example .env   # fill in GitHub App and OpenAI values
```

| Variable | Used by | Notes |
|---|---|---|
| `GITHUB_WEBHOOK_SECRET` | gateway | Same secret configured in the GitHub App |
| `GITHUB_APP_ID`, `GITHUB_PRIVATE_KEY` | reviewer | PEM key can use literal `\n` on one line |
| `OPENAI_API_KEY`, `OPENAI_MODEL` | reviewer | Model defaults to `gpt-4o` |
| `REDIS_URL`, `REVIEW_QUEUE_NAME` | both | Defaults to `redis://localhost:6379/0` |
| `OPENAI_EMBEDDING_MODEL` | reviewer | Defaults to `text-embedding-3-small` |
| `DIFF_TOKEN_BUDGET`, `FILE_TOKEN_BUDGET` | reviewer | Defaults to 24000 / 6000 tokens |
| `CONVENTIONS_TOP_K` | reviewer | Convention snippets added to the prompt (default 6) |
| `REVIEW_MODE` | reviewer | `auto` (default) or `approval` |
| `MAX_FINDINGS` | reviewer | Cap on findings per review (default 15) |
| `OPENAI_MAX_RETRIES`, `GITHUB_MAX_ATTEMPTS` | reviewer | Per-call retries (defaults 4 / 4) |
| `JOB_MAX_ATTEMPTS`, `JOB_RETRY_BASE_SECONDS` | reviewer | Job-level retries before dead-lettering (defaults 3 / 30) |
| `LOG_FORMAT` | both | `json` (default) or `text` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | both | Enables tracing, e.g. `http://localhost:4318` |

## Running locally

```bash
docker run -d --name prr-redis -p 6379:6379 redis:7-alpine
uvicorn pr_reviewer.gateway.main:create_app --factory --port 8000
uvicorn pr_reviewer.reviewer.main:create_app --factory --port 8001
ngrok http 8000
```

Set the GitHub App webhook URL to `https://<id>.ngrok-free.app/webhook`, then open or update a PR in a repository where the App is installed.

## Tests

```bash
pytest
```

The tests use an in-memory queue and a fake LLM, so they need neither Redis nor OpenAI. Retry tests use scripted HTTP responses and don't sleep, and tracing tests capture spans in memory. They also check that every eval case's expected issue points at a line in its diff.

## Evals

> **Note:** this public repository is a sanitized copy. The production deployment, including its credentials, the real GitHub App installation and its eval results, lives in a private company repository. Here the evals run only against the mocked LLM in the test suite (`tests/test_evals.py`), and `evals/results/` is empty.

`evals/cases/` holds 20 fixed pull requests. 17 have seeded issues (SQL injection, XSS, path traversal, an unawaited promise, an N+1 query, a committed secret, a prompt injection, convention violations that only RAG can catch, …) and 3 are clean, to measure false positives. Each case lists the expected issues with file, line range and category.

```bash
python -m pr_reviewer.evals.run                       # full pipeline vs baseline, with LLM judge
python -m pr_reviewer.evals.run --variant full --no-judge --case sql-injection
python -m pr_reviewer.evals.run --repeat 3            # average out sampling noise
```

The suite runs the same `run_review_pipeline` as the worker, with no GitHub access. It compares two variants:

- **full**: the token budget, RAG, guardrails and finding cap.
- **baseline**: every diff in full, no RAG, no output filtering. This is close to the original single-prompt reviewer.

| Metric | How it is measured |
|---|---|
| Useful findings | An LLM judge (`evals/judge`, temperature 0, strict structured output) rates each finding as correct, specific and actionable, or not |
| Expected issues found | Location: same file, within ±2 lines. Judge: the finding identifies the issue by meaning |
| Findings on clean PRs | False positives |
| Avg tokens, LLM calls, tool calls, seconds | Taken from OpenAI usage metadata for each case |

Results are written to `evals/results/<timestamp>.json`, with every finding and the judge's reasoning. `--fail-under-useful 0.7` and `--fail-under-recall 0.8` make the command exit non-zero below those thresholds, for CI.

## GitHub App configuration

The App already exists in the organization. Org App admins manage these settings:

- Webhook URL: `https://<host>/webhook`
- Repository permissions: Pull requests (Read & write), Contents (Read)
- Subscribed events: Pull requests, Issue comments (for `/ai-review` commands)
- Install the App on each repository you want reviewed

## Troubleshooting

- **GitHub deliveries**: App settings → Advanced → Recent deliveries. A queued review returns `202`; an event that is ignored returns `200`; a bad signature returns `401`.
- **ngrok inspector**: `http://127.0.0.1:4040`
- **Logs**: every log line carries the `delivery_id` from GitHub, so you can follow one webhook from the gateway through to the reviewer (`jq 'select(.delivery_id=="…")'`).
- **Failed reviews**: check `prr_review_jobs_total{outcome="dead_letter"}` and the `pr-review-jobs:dead` list in Redis.
