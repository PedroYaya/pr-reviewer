// Fake reviewer: moves reviews through the same lifecycle as the real worker,
// so the dashboard can be built and demoed without GitHub or OpenAI.
//
//   reviewing ─▶ published | awaiting_approval | skipped
//       │                      └─▶ approved | dismissed
//       └─▶ retrying ─▶ reviewing (next attempt) … ─▶ failed after the last attempt

import type { Finding, Review, ReviewStatus, Stats } from "../api";

const MAX_ATTEMPTS = 3;

const REPOS = [
  ["acme", "payments-api"],
  ["acme", "web-app"],
  ["acme", "data-pipeline"],
  ["globex", "auth-service"],
] as const;

const FINDINGS: Finding[] = [
  {
    path: "app/db/orders.py", line: 42, severity: "critical", category: "security", confidence: "high",
    title: "SQL injection through string formatting",
    explanation: "The order id from the request is interpolated into the SQL string, so a crafted id can run arbitrary SQL.",
    suggestion: 'cursor.execute("SELECT * FROM orders WHERE id = %s", (order_id,))',
  },
  {
    path: "src/hooks/useCart.ts", line: 18, severity: "major", category: "bug", confidence: "high",
    title: "Promise is not awaited",
    explanation: "saveCart() returns a promise that is never awaited, so errors are lost and the UI shows success before the save finishes.",
    suggestion: "await saveCart(items);",
  },
  {
    path: "app/services/report.py", line: 77, severity: "major", category: "performance", confidence: "medium",
    title: "N+1 query inside the loop",
    explanation: "Each iteration loads the customer separately, which turns one page of 100 invoices into 101 queries.",
    suggestion: "Load customers in one query with select_related('customer').",
  },
  {
    path: "config/settings.py", line: 9, severity: "critical", category: "security", confidence: "high",
    title: "Secret committed to the repository",
    explanation: "An API key is hardcoded on an added line. It was redacted before reaching the model and must be rotated.",
    suggestion: "Read it from an environment variable and rotate the key.",
  },
  {
    path: "app/utils/cache.py", line: 23, severity: "minor", category: "bug", confidence: "medium",
    title: "Mutable default argument",
    explanation: "The default list is shared between calls, so entries leak from one call into the next.",
    suggestion: "Use `items: list | None = None` and create the list inside the function.",
  },
  {
    path: "src/api/client.ts", line: 51, severity: "minor", category: "maintainability", confidence: "high",
    title: "Exception swallowed silently",
    explanation: "The catch block ignores the error, which hides network failures from both the user and the logs.",
    suggestion: "Log the error and rethrow it, or show it to the user.",
  },
  {
    path: "app/handlers/upload.py", line: 35, severity: "major", category: "security", confidence: "high",
    title: "Path traversal in file name",
    explanation: "The uploaded file name is joined to the storage path without normalising it, so '../' can write outside the folder.",
    suggestion: "Use os.path.basename() and check the resolved path stays inside the upload folder.",
  },
  {
    path: "tests/test_orders.py", line: 12, severity: "nit", category: "testing", confidence: "medium",
    title: "Fix has no regression test",
    explanation: "The bug fixed in this PR has no test, so it can come back unnoticed.",
    suggestion: null,
  },
];

const SUMMARIES = [
  "Adds order lookup by id to the payments API. The query is built with string formatting and is injectable.",
  "Refactors the cart hook to save on every change. One async call is not awaited.",
  "Adds a monthly invoice report. Works, but queries the database once per invoice.",
  "Moves configuration into a settings module. A live API key was committed.",
  "Small cleanup of the caching helpers; one default argument is shared between calls.",
];

const ERRORS = [
  "HTTPError: 502 Server Error: Bad Gateway for url: https://api.github.com/...",
  "APITimeoutError: Request timed out.",
  "RateLimitError: Error code: 429 - Rate limit reached for gpt-4o",
];

interface Timer {
  // Ticks left in the current status.
  ticks: number;
  // Whether the current attempt will fail.
  fails: boolean;
}

const pick = <T,>(items: readonly T[]): T => items[Math.floor(Math.random() * items.length)];
const chance = (probability: number) => Math.random() < probability;
const between = (low: number, high: number) => low + Math.floor(Math.random() * (high - low + 1));
const hex = (length: number) =>
  Array.from({ length }, () => Math.floor(Math.random() * 16).toString(16)).join("");

export class Simulator {
  private reviews: Review[] = [];
  private timers = new Map<string, Timer>();

  constructor(private clock: () => number = () => Date.now() / 1000) {}

  /** Fills the history with a few minutes of activity so the dashboard isn't empty. */
  seed(minutes = 5, tickSeconds = 2.5) {
    const start = this.clock() - minutes * 60;
    let virtual = start;
    const real = this.clock;
    this.clock = () => virtual;
    for (; virtual < real(); virtual += tickSeconds) this.tick();
    this.clock = real;
  }

  tick() {
    for (const review of this.reviews) this.advance(review);
    if (this.reviews.length === 0 || chance(0.45)) this.enqueue();
  }

  list(status: ReviewStatus | null, limit: number): Review[] {
    return this.reviews
      .filter((r) => status === null || r.status === status)
      .sort((a, b) => b.updated_at - a.updated_at)
      .slice(0, limit);
  }

  get(deliveryId: string): Review | undefined {
    return this.reviews.find((r) => r.delivery_id === deliveryId);
  }

  stats(): Stats {
    const counts: Stats = {};
    for (const r of this.reviews) counts[r.status] = (counts[r.status] ?? 0) + 1;
    return counts;
  }

  private enqueue() {
    const [owner, repo] = pick(REPOS);
    const now = this.clock();
    const review: Review = {
      delivery_id: crypto.randomUUID(),
      owner,
      repo,
      pr_number: between(100, 480),
      head_sha: hex(40),
      status: "reviewing",
      attempt: 1,
      summary: null,
      findings: [],
      dropped_findings: 0,
      secrets_redacted: 0,
      omitted_files: 0,
      input_tokens: 0,
      output_tokens: 0,
      llm_calls: 0,
      tool_calls: 0,
      note: null,
      error: null,
      enqueued_at: now - between(1, 8),
      updated_at: now,
    };
    this.reviews.push(review);
    this.timers.set(review.delivery_id, { ticks: between(2, 5), fails: chance(0.2) });
  }

  private advance(review: Review) {
    const timer = this.timers.get(review.delivery_id);
    if (!timer) return;
    if (--timer.ticks > 0) return;

    switch (review.status) {
      case "reviewing":
        if (timer.fails) {
          this.fail(review, timer);
        } else {
          this.complete(review, timer);
        }
        break;
      case "retrying":
        this.update(review, { status: "reviewing", attempt: review.attempt + 1, error: null });
        Object.assign(timer, { ticks: between(2, 4), fails: chance(0.35) });
        break;
      case "awaiting_approval":
        if (chance(0.7)) {
          this.update(review, { status: "approved", note: `approved by @${pick(["maria", "lucas", "sofia"])}` });
        } else {
          this.update(review, { status: "dismissed", note: `dismissed by @${pick(["maria", "lucas"])}` });
        }
        this.timers.delete(review.delivery_id);
        break;
    }
  }

  private fail(review: Review, timer: Timer) {
    const error = pick(ERRORS);
    if (review.attempt >= MAX_ATTEMPTS) {
      this.update(review, { status: "failed", error });
      this.timers.delete(review.delivery_id);
    } else {
      this.update(review, { status: "retrying", error });
      timer.ticks = 2 * review.attempt; // 30 s, then 120 s in the real worker
    }
  }

  private complete(review: Review, timer: Timer) {
    if (chance(0.1)) {
      this.update(review, { status: "skipped", note: pick(["a newer commit was pushed", "no reviewable files"]) });
      this.timers.delete(review.delivery_id);
      return;
    }
    const findings = chance(0.15) ? [] : [...FINDINGS].sort(() => Math.random() - 0.5).slice(0, between(1, 4));
    const approval = chance(0.25);
    this.update(review, {
      status: approval ? "awaiting_approval" : "published",
      summary: findings.length ? pick(SUMMARIES) : "Small, well-scoped change. Nothing worth flagging.",
      findings,
      dropped_findings: between(0, 3),
      secrets_redacted: findings.some((f) => f.title.startsWith("Secret")) ? 1 : 0,
      omitted_files: chance(0.3) ? between(1, 3) : 0,
      input_tokens: between(4_000, 22_000),
      output_tokens: between(400, 1_800),
      llm_calls: between(1, 4),
      tool_calls: between(0, 5),
    });
    if (approval) {
      timer.ticks = between(6, 12);
    } else {
      this.timers.delete(review.delivery_id);
    }
  }

  private update(review: Review, changes: Partial<Review>) {
    Object.assign(review, changes, { updated_at: this.clock() });
  }
}
