# GitHub App PR Reviewer

An AI pull request reviewer delivered as a GitHub App. It runs as two Python microservices built with FastAPI, connected by a Redis queue, and uses LangChain and OpenAI to write the review.

## Architecture

```
GitHub ──webhook──▶ gateway (FastAPI) ──job──▶ Redis queue ──▶ reviewer (FastAPI + worker)
                    verify signature                            fetch PR files (GitHub API)
                    filter events                               review with LangChain + OpenAI
                    respond 202 right away                      post review with inline comments
```

- **gateway** (`pr_reviewer/gateway`): receives GitHub webhooks, checks the `X-Hub-Signature-256` HMAC, keeps only reviewable PR events (`opened`, `synchronize`, `reopened`, `ready_for_review`, never drafts) and queues a `ReviewJob`. GitHub stops waiting for a webhook after 10 seconds, so this service never calls the LLM.
- **reviewer** (`pr_reviewer/reviewer`): a background worker takes jobs from the queue, skips any job whose commit is no longer the PR head, runs the review agent and posts the result. Its `/health` endpoint reports whether the worker is still running.
- **common** (`pr_reviewer/common`): settings, the GitHub App client (JWT, a cached token per installation, paginated file lists), the queue and the shared job model.

Each review is stateless. No context is shared between PRs.

### Review agent

1. **Numbered diff** (`reviewer/diff.py`): each diff line in the prompt starts with its line number in the new file, so the model can point to exact lines.
2. **Tool calling** (`reviewer/agent.py`, `reviewer/repo_tools.py`): the model can call `read_file` and `list_directory` to read the repository at the PR's head commit, for up to 5 rounds. Tool results are capped at 20k characters.
3. **Structured output** (`reviewer/schemas.py`): the model finishes by calling the `ReviewResult` tool. OpenAI strict mode constrains its arguments to the schema, and Pydantic validates them: a summary plus findings with `path`, `line`, `severity`, `category`, `title`, `explanation` and `suggestion`. If the model uses up the tool rounds, `ReviewResult` is forced.
4. **Publishing** (`reviewer/publisher.py`): findings become a GitHub pull request review, ordered by severity. Findings on lines that are in the diff become inline comments. Findings on other lines go in the review body, because a single invalid line makes GitHub reject the whole review with a 422.

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

The tests use an in-memory queue and a fake LLM, so they need neither Redis nor OpenAI.

## GitHub App configuration

The App already exists in the organization. Org App admins manage these settings:

- Webhook URL: `https://<host>/webhook`
- Repository permissions: Pull requests (Read & write), Contents (Read)
- Subscribed events: Pull requests
- Install the App on each repository you want reviewed

## Troubleshooting

- **GitHub deliveries**: App settings → Advanced → Recent deliveries. A queued review returns `202`; an event that is ignored returns `200`; a bad signature returns `401`.
- **ngrok inspector**: `http://127.0.0.1:4040`
- **Logs**: each service logs the `delivery_id` from GitHub, so you can follow one webhook from the gateway through to the reviewer.
