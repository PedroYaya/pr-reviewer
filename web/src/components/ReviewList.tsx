import type { Review, ReviewStatus } from "../api";
import { SEVERITY_ORDER, timeAgo } from "../format";
import { useReviews } from "../queries";
import StatusBadge from "./StatusBadge";

interface Props {
  status: ReviewStatus | null;
  selectedId: string | null;
  onSelect: (deliveryId: string) => void;
}

export default function ReviewList({ status, selectedId, onSelect }: Props) {
  const { data: reviews, isPending, isError, error } = useReviews(status);

  if (isPending) return <section className="panel list">Loading reviews…</section>;
  if (isError) return <section className="panel list error-box">Couldn't load reviews: {error.message}</section>;

  return (
    <section className="panel list" aria-label="Reviews">
      {reviews.length === 0 && <p className="muted empty">No reviews with this status yet.</p>}
      <ul>
        {reviews.map((review) => (
          <li key={review.delivery_id}>
            <button
              className={`row ${review.delivery_id === selectedId ? "selected" : ""}`}
              onClick={() => onSelect(review.delivery_id)}
            >
              <div className="row-top">
                <span className="pr">
                  {review.owner}/{review.repo} <strong>#{review.pr_number}</strong>
                </span>
                <StatusBadge status={review.status} />
              </div>
              <div className="row-bottom muted">
                <code>{review.head_sha?.slice(0, 7) ?? "—"}</code>
                <SeverityCounts review={review} />
                {review.attempt > 1 && <span>attempt {review.attempt}</span>}
                <span className="time">{timeAgo(review.updated_at)}</span>
              </div>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

function SeverityCounts({ review }: { review: Review }) {
  if (review.findings.length === 0) return null;
  return (
    <span className="severity-counts">
      {SEVERITY_ORDER.map((severity) => {
        const count = review.findings.filter((f) => f.severity === severity).length;
        return count ? (
          <span key={severity} className={`dot dot-${severity}`} title={`${count} ${severity}`}>
            {count}
          </span>
        ) : null;
      })}
    </span>
  );
}
