import type { ReviewStatus } from "../api";
import { STATUS_LABELS, STATUS_ORDER } from "../format";
import { useStats } from "../queries";

interface Props {
  selected: ReviewStatus | null;
  onSelect: (status: ReviewStatus | null) => void;
}

/** Counts per status; each one doubles as a filter for the list. */
export default function StatsBar({ selected, onSelect }: Props) {
  const { data: stats = {} } = useStats();
  const total = Object.values(stats).reduce((sum, n) => sum + (n ?? 0), 0);

  return (
    <nav className="stats" aria-label="Filter by status">
      <button className={`stat ${selected === null ? "active" : ""}`} onClick={() => onSelect(null)}>
        <span className="stat-count">{total}</span>
        <span className="stat-label">All</span>
      </button>
      {STATUS_ORDER.map((status) => (
        <button
          key={status}
          className={`stat stat-${status} ${selected === status ? "active" : ""}`}
          onClick={() => onSelect(selected === status ? null : status)}
        >
          <span className="stat-count">{stats[status] ?? 0}</span>
          <span className="stat-label">{STATUS_LABELS[status]}</span>
        </button>
      ))}
    </nav>
  );
}
