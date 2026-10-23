// Server state lives in TanStack Query: it caches each response, polls for
// changes and shares results between components. Components never call fetch.

import { useQuery } from "@tanstack/react-query";
import { fetchReview, fetchReviews, fetchStats, type ReviewStatus } from "./api";

// "Live" updates by polling; Server-Sent Events would push them instead.
export const POLL_MS = 2_000;

export function useReviews(status: ReviewStatus | null) {
  return useQuery({
    queryKey: ["reviews", status],
    queryFn: () => fetchReviews(status),
    refetchInterval: POLL_MS,
    // Keep showing the previous list while a new filter loads, instead of a spinner.
    placeholderData: (previous) => previous,
  });
}

export function useReview(deliveryId: string | null) {
  return useQuery({
    queryKey: ["review", deliveryId],
    queryFn: () => fetchReview(deliveryId!),
    enabled: deliveryId !== null,
    refetchInterval: POLL_MS,
  });
}

export function useStats() {
  return useQuery({ queryKey: ["stats"], queryFn: fetchStats, refetchInterval: POLL_MS });
}
