// Contract with the reviewer service (pr_reviewer/reviewer/history.py).
// The mocks implement the same contract, so switching to the real API changes nothing here.

export type ReviewStatus =
  | "reviewing"
  | "retrying"
  | "failed"
  | "skipped"
  | "published"
  | "awaiting_approval"
  | "approved"
  | "dismissed";

export type Severity = "critical" | "major" | "minor" | "nit";

export interface Finding {
  path: string;
  line: number;
  severity: Severity;
  category: "bug" | "security" | "performance" | "maintainability" | "style" | "testing";
  confidence: "high" | "medium" | "low";
  title: string;
  explanation: string;
  suggestion: string | null;
}

export interface Review {
  delivery_id: string;
  owner: string;
  repo: string;
  pr_number: number;
  head_sha: string | null;
  status: ReviewStatus;
  attempt: number;
  summary: string | null;
  findings: Finding[];
  dropped_findings: number;
  secrets_redacted: number;
  omitted_files: number;
  input_tokens: number;
  output_tokens: number;
  llm_calls: number;
  tool_calls: number;
  note: string | null;
  error: string | null;
  // Unix seconds, as stored by the backend.
  enqueued_at: number;
  updated_at: number;
}

export type Stats = Partial<Record<ReviewStatus, number>>;

async function getJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`${response.status} ${response.statusText} from ${url}`);
  }
  return response.json() as Promise<T>;
}

export function fetchReviews(status: ReviewStatus | null): Promise<Review[]> {
  const params = new URLSearchParams({ limit: "100" });
  if (status) params.set("status", status);
  return getJson(`/api/reviews?${params}`);
}

export function fetchReview(deliveryId: string): Promise<Review> {
  return getJson(`/api/reviews/${encodeURIComponent(deliveryId)}`);
}

export function fetchStats(): Promise<Stats> {
  return getJson("/api/stats");
}
