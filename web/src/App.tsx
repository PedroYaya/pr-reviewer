import { useState } from "react";
import type { ReviewStatus } from "./api";
import ReviewDetail from "./components/ReviewDetail";
import ReviewList from "./components/ReviewList";
import StatsBar from "./components/StatsBar";

// Client state is just two values, so plain useState is enough: no global store.
// Everything that comes from the server is in TanStack Query (see queries.ts).
export default function App() {
  const [status, setStatus] = useState<ReviewStatus | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);

  return (
    <div className="app">
      <header className="header">
        <div>
          <h1>PR Reviewer</h1>
          <p className="muted">AI reviews as they happen</p>
        </div>
        <span className="live">
          <span className="live-dot" /> Live
        </span>
      </header>

      <StatsBar selected={status} onSelect={setStatus} />

      <main className="layout">
        <ReviewList status={status} selectedId={selectedId} onSelect={setSelectedId} />
        <ReviewDetail deliveryId={selectedId} />
      </main>
    </div>
  );
}
