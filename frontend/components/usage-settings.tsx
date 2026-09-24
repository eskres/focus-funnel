"use client";

import { useEffect, useState } from "react";

import { formatThreshold } from "@/components/chat/chat-notices";
import { UsageChart } from "@/components/usage-chart";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError, UnauthenticatedError } from "@/lib/api";
import { redirectToLogin } from "@/lib/redirect-to-login";
import { USAGE_PERIODS, formatUsd, getUsage, type UsageReport } from "@/lib/usage";

function monthName(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en", {
    month: "long",
    timeZone: "UTC",
  });
}

/**
 * Estimated spend: a daily bar chart for a chosen period, the split by model,
 * and the month so far. The account balance is not shown, because providers
 * do not report it to an API key; the section links to their consoles.
 */
export function UsageSection() {
  const [days, setDays] = useState<number>(30);
  const [report, setReport] = useState<UsageReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getUsage(days).then(
      (loaded) => {
        if (cancelled) return;
        setReport(loaded);
        setError(null);
        setLoading(false);
      },
      (caught: unknown) => {
        if (cancelled) return;
        if (caught instanceof UnauthenticatedError) {
          redirectToLogin("/settings");
          return;
        }
        setError(caught instanceof ApiError ? caught.message : "Could not load the usage.");
        setLoading(false);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [days]);

  function choose(period: number) {
    if (period === days) return;
    // The last report stays on screen, dimmed, while the next one loads.
    setLoading(true);
    setDays(period);
  }

  const periodUsed = report?.days.some((day) => day.calls > 0) ?? false;
  const neverUsed = report !== null && !periodUsed && report.month.calls === 0;

  return (
    <Card id="usage">
      <CardHeader>
        <CardTitle>Usage</CardTitle>
        <CardDescription>
          Estimated spend per day (UTC), from the providers&apos; list prices, for calls made through
          this app.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div role="group" aria-label="Period" className="flex gap-1">
          {USAGE_PERIODS.map((period) => (
            <Button
              key={period}
              type="button"
              size="xs"
              variant={period === days ? "secondary" : "ghost"}
              aria-pressed={period === days}
              onClick={() => choose(period)}
            >
              {period} days
            </Button>
          ))}
        </div>

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}
        {!report && !error && <p className="text-sm text-muted-foreground">Loading usage…</p>}

        {report && (
          <div
            className={`flex flex-col gap-4 transition-opacity ${loading ? "opacity-50" : ""}`}
            aria-busy={loading}
          >
            <MonthTotal report={report} />

            {neverUsed ? (
              <p className="text-sm text-muted-foreground">Nothing has been used yet.</p>
            ) : periodUsed ? (
              <UsageChart days={report.days} />
            ) : (
              <p className="text-sm text-muted-foreground">Nothing was used in this period.</p>
            )}

            {report.by_model.length > 0 && (
              <table className="w-full text-left text-sm tabular-nums" aria-label="Spend by model">
                <thead className="text-xs text-muted-foreground">
                  <tr>
                    <th className="font-medium">Model</th>
                    <th className="text-right font-medium">Estimated spend</th>
                    <th className="text-right font-medium">Tokens</th>
                  </tr>
                </thead>
                <tbody>
                  {report.by_model.map((row) => (
                    <tr key={`${row.provider_id}:${row.model}`}>
                      <td className="max-w-56 truncate" title={row.model}>
                        {row.model}
                      </td>
                      <td className="text-right">
                        {formatUsd(row.cost_usd)}
                        {row.unknown_cost_calls > 0 && "*"}
                      </td>
                      <td className="text-right">{row.tokens.toLocaleString("en")}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {report.by_model.some((row) => row.unknown_cost_calls > 0) && (
              <p className="text-xs text-muted-foreground">
                * Some calls have no listed price or reported tokens. They are counted in tokens
                only, so the estimate leaves them out.
              </p>
            )}

            <Balance consoles={report.consoles} />
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function MonthTotal({ report }: { report: UsageReport }) {
  const { month, warning } = report;
  return (
    <div className="flex flex-col gap-1">
      <p className="text-xs text-muted-foreground">{monthName(month.start)} so far (estimate)</p>
      <p className="text-2xl font-semibold" data-testid="month-total">
        {formatUsd(month.cost_usd)}
      </p>
      <p className="text-xs text-muted-foreground">
        {month.tokens.toLocaleString("en")} tokens in {month.calls.toLocaleString("en")}{" "}
        {month.calls === 1 ? "call" : "calls"}
        {month.unknown_cost_calls > 0 &&
          `, ${month.unknown_cost_calls} with unknown cost counted in tokens only`}
      </p>
      {warning && (
        <p className="text-xs">
          Warning threshold: {formatThreshold(warning)}.{" "}
          {warning.reached ? (
            <span className="font-medium">Reached this month.</span>
          ) : (
            "Not reached this month."
          )}
        </p>
      )}
    </div>
  );
}

function Balance({ consoles }: { consoles: UsageReport["consoles"] }) {
  if (consoles.length === 0) {
    return (
      <p className="text-xs text-muted-foreground">
        Your account balance is only shown in your provider&apos;s console.
      </p>
    );
  }
  return (
    <p className="text-xs text-muted-foreground">
      Your account balance is only shown in your provider&apos;s console:{" "}
      {consoles.map((link, index) => (
        <span key={link.provider_id}>
          {index > 0 && ", "}
          <a
            href={link.url}
            target="_blank"
            rel="noreferrer"
            className="underline underline-offset-2 hover:text-foreground"
          >
            {link.label}
          </a>
        </span>
      ))}
      .
    </p>
  );
}
