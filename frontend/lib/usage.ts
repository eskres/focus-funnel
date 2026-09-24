// Typed client for the usage report (`/api/usage`).
import { apiFetch } from "@/lib/api";

export type UsageTotals = {
  cost_usd: number;
  tokens: number;
  /** Calls whose cost is unknown: no listed price, or no reported tokens. */
  unknown_cost_calls: number;
  calls: number;
};

export type UsageReport = {
  /** Every day of the period in UTC, oldest first. */
  days: (UsageTotals & { date: string })[];
  by_model: (UsageTotals & { provider_id: string; model: string })[];
  month: UsageTotals & { start: string };
  warning: { unit: "usd" | "tokens"; amount: number; reached: boolean } | null;
  consoles: { provider_id: string; label: string; url: string }[];
};

export const USAGE_PERIODS = [7, 30, 90] as const;

export function getUsage(days: number): Promise<UsageReport> {
  return apiFetch<UsageReport>(`/api/usage?days=${days}`);
}

/**
 * Dollars with two significant digits under a dollar ($0.50, $0.012, $0.00012),
 * and cents above. `decimals` fixes the places, for axis ticks that share a step.
 */
export function formatUsd(value: number, decimals?: number): string {
  const places =
    decimals ??
    (value > 0 && value < 1 ? Math.min(Math.max(2, 1 - Math.floor(Math.log10(value))), 10) : 2);
  return value.toLocaleString("en", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: places,
    maximumFractionDigits: places,
  });
}
