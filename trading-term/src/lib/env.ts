const OPS_API_URL =
  (typeof window !== "undefined"
    ? window.ENV?.NEXT_PUBLIC_OPS_API_URL
    : undefined) ??
  process.env.NEXT_PUBLIC_OPS_API_URL ??
  "/api/backend";

export const env = {
  opsApiUrl: OPS_API_URL.replace(/\/+$/, ""),
  pollIntervalMs: 10_000,
  dashboardPollIntervalMs: 7_000,
  requestTimeoutMs: 10_000,
  staleThresholdMs: 30_000,
  heartbeatStaleThresholdSec: 120,
  analyticsPollIntervalMs: 3_000,
} as const;

declare global {
  interface Window {
    ENV?: { NEXT_PUBLIC_OPS_API_URL?: string };
  }
}