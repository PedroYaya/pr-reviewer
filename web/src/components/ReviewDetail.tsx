import type { Finding } from "../api";
import { formatNumber, SEVERITY_ORDER, timeAgo } from "../format";
import { useReview } from "../queries";
import StatusBadge from "./StatusBadge";

export default function ReviewDetail({ deliveryId }: { deliveryId: string | null }) {
  const { data: review, isPending, isError, error } = useReview(deliveryId);

  if (deliveryId === null) {
    return <section className="panel detail muted empty">Select a review to see its summary and comments.</section>;
  }
  if (isPending) return <section className="panel detail">Loading…</section>;
  if (isError) return <section className="panel detail error-box">Couldn't load the review: {error.message}</section>;

  const findings = [...review.findings].sort(
    (a, b) => SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity),
  );
  const inProgress = review.status === "reviewing" || review.status === "retrying";

  return (
    <section className="panel detail" aria-label="Review detail">
      <div className="detail-head">
        <h2>
          {review.owner}/{review.repo} #{review.pr_number}
        </h2>
        <StatusBadge status={review.status} />
      </div>
      <p className="muted small">
        Commit <code>{review.head_sha?.slice(0, 7) ?? "—"}</code> · attempt {review.attempt} · updated{" "}
        {timeAgo(review.updated_at)}
      </p>

      {review.error && (
        <div className="error-box">
          <strong>{review.status === "failed" ? "Failed, moved to the dead-letter queue" : "Last attempt failed"}</strong>
          <code className="block">{review.error}</code>
        </div>
      )}
      {review.note && <p className="note">{review.note}</p>}

      {inProgress && !review.summary && <p className="muted">The agent is still working on this review…</p>}

      {review.summary && (
        <>
          <h3>Summary</h3>
          <p>{review.summary}</p>

          <dl className="metrics">
            <Metric label="Input tokens" value={formatNumber(review.input_tokens)} />
            <Metric label="Output tokens" value={formatNumber(review.output_tokens)} />
            <Metric label="LLM calls" value={review.llm_calls} />
            <Metric label="Tool calls" value={review.tool_calls} />
            <Metric label="Dropped by guardrails" value={review.dropped_findings} />
            <Metric label="Files left out" value={review.omitted_files} />
          </dl>

          <h3>Comments ({findings.length})</h3>
          {findings.length === 0 && <p className="muted">No problems found.</p>}
          <ul className="findings">
            {findings.map((finding, index) => (
              <FindingCard key={index} finding={finding} />
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function Metric({ label, value }: { label: string; value: string | number }) {
  return (
    <div>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </div>
  );
}

function FindingCard({ finding }: { finding: Finding }) {
  return (
    <li className={`finding finding-${finding.severity}`}>
      <div className="finding-head">
        <span className={`severity severity-${finding.severity}`}>{finding.severity}</span>
        <span className="muted small">{finding.category}</span>
        <code className="location">
          {finding.path}:{finding.line}
        </code>
      </div>
      <p className="finding-title">{finding.title}</p>
      <p className="small">{finding.explanation}</p>
      {finding.suggestion && <code className="block suggestion">{finding.suggestion}</code>}
    </li>
  );
}
