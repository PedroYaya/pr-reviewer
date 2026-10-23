import type { ReviewStatus } from "../api";
import { STATUS_LABELS } from "../format";

export default function StatusBadge({ status }: { status: ReviewStatus }) {
  return <span className={`badge badge-${status}`}>{STATUS_LABELS[status]}</span>;
}
