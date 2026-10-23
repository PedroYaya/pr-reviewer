import type { ReviewStatus, Severity } from "./api";

export const STATUS_LABELS: Record<ReviewStatus, string> = {
  reviewing: "Reviewing",
  retrying: "Retrying",
  failed: "Failed",
  skipped: "Skipped",
  published: "Published",
  awaiting_approval: "Awaiting approval",
  approved: "Approved",
  dismissed: "Dismissed",
};

export const STATUS_ORDER: ReviewStatus[] = [
  "reviewing", "retrying", "awaiting_approval", "published", "approved", "dismissed", "skipped", "failed",
];

export const SEVERITY_ORDER: Severity[] = ["critical", "major", "minor", "nit"];

const relative = new Intl.RelativeTimeFormat("en", { numeric: "auto" });

export function timeAgo(unixSeconds: number, now = Date.now() / 1000): string {
  const seconds = Math.round(unixSeconds - now);
  if (Math.abs(seconds) < 60) return relative.format(seconds, "second");
  const minutes = Math.round(seconds / 60);
  if (Math.abs(minutes) < 60) return relative.format(minutes, "minute");
  return relative.format(Math.round(minutes / 60), "hour");
}

export const formatNumber = new Intl.NumberFormat("en").format;
