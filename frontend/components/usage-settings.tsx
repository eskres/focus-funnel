"use client";

import { useEffect, useState } from "react";

import { formatThreshold } from "@/components/chat/chat-notices";
import { useDemo } from "@/components/demo/demo-context";
import { UsageChart } from "@/components/usage-chart";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { USAGE_DELETED } from "@/lib/account";
import { ApiError, UnauthenticatedError } from "@/lib/api";
import { redirectToLogin } from "@/lib/redirect-to-login";
import {
  USAGE_PERIODS,
  formatUsd,
  getUsage,
  saveCap,
  type CapState,
  type SpendCap,
  type UsageReport,
} from "@/lib/usage";

function monthName(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en", {
    month: "long",
    timeZone: "UTC",
  });
}

/** A UTC day as "1 December 2026". */
function longDate(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString("en-GB", {
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "UTC",
  });
}

/** The first day of the month after the one `monthStart` begins, as an ISO date. */
function nextMonthStart(monthStart: string): string {
  const start = new Date(`${monthStart}T00:00:00Z`);
  return new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 1))
    .toISOString()
    .slice(0, 10);
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
  // Bumped when the usage history is deleted from the "Your data" section.
  const [reloads, setReloads] = useState(0);

  useEffect(() => {
    const onDeleted = () => setReloads((count) => count + 1);
    window.addEventListener(USAGE_DELETED, onDeleted);
    return () => window.removeEventListener(USAGE_DELETED, onDeleted);
  }, []);

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
  }, [days, reloads]);

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
            <SpendCapForm
              cap={report.cap}
              resetsOn={report.cap?.resets_on ?? nextMonthStart(report.month.start)}
              onSaved={(cap) => setReport((current) => current && { ...current, cap })}
            />

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
  const { month, warning, cap } = report;
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
      {cap && (
        <p className={cap.reached ? "text-xs font-medium" : "text-xs"}>
          {`Spend cap: ${formatThreshold(cap)}. ${cap.reached ? "Reached this month." : "Not reached."}`}
        </p>
      )}
    </div>
  );
}

/**
 * The monthly spend cap, saved on its own: new chat messages are refused once
 * the month's usage reaches it. The form keeps what the user typed when the
 * report reloads, and starts from the cap the first report loaded.
 */
function SpendCapForm({
  cap,
  resetsOn,
  onSaved,
}: {
  cap: CapState | null;
  /** The first day of the next month in UTC, when the cap counts from zero. */
  resetsOn: string;
  onSaved: (cap: CapState | null) => void;
}) {
  const demo = useDemo();
  const [unit, setUnit] = useState<"" | SpendCap["unit"]>(cap?.unit ?? "");
  const [amount, setAmount] = useState(cap ? String(cap.amount) : "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  async function save() {
    setSaved(false);
    let next: SpendCap | null = null;
    if (unit) {
      const value = Number(amount);
      if (amount.trim() === "" || Number.isNaN(value) || value <= 0) {
        setError("The spend cap needs an amount above zero.");
        return;
      }
      // Tokens are whole, and a token cap is shown as a whole number.
      if (unit === "tokens" && !Number.isInteger(value)) {
        setError("A token cap needs a whole number.");
        return;
      }
      next = { unit, amount: value };
    }
    setBusy(true);
    setError(null);
    try {
      onSaved(await saveCap(next));
      setSaved(true);
    } catch (caught) {
      if (caught instanceof UnauthenticatedError) {
        redirectToLogin("/settings");
        return;
      }
      setError(caught instanceof ApiError ? caught.message : "Could not save the spend cap.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <fieldset className="flex flex-col gap-1 text-sm">
      <legend className="font-medium">Monthly spend cap</legend>
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label="Spend cap unit"
          className="rounded-md border bg-background px-2 py-1 text-sm"
          value={unit}
          disabled={busy}
          onChange={(event) => {
            setUnit(event.target.value as "" | SpendCap["unit"]);
            setSaved(false);
          }}
        >
          <option value="">No cap</option>
          <option value="usd">Estimated dollars</option>
          <option value="tokens">Tokens</option>
        </select>
        {unit && (
          <Input
            type="number"
            aria-label="Spend cap amount"
            className="w-36"
            min={0}
            step={unit === "usd" ? "0.01" : "1000"}
            placeholder={unit === "usd" ? "5.00" : "2000000"}
            value={amount}
            onChange={(event) => {
              setAmount(event.target.value);
              setSaved(false);
            }}
            disabled={busy}
          />
        )}
        <Button type="button" size="sm" variant="outline" onClick={save} disabled={busy}>
          {busy ? "Saving…" : "Save cap"}
        </Button>
      </div>
      <p className="text-xs text-muted-foreground">
        New chat messages are refused once this month&apos;s usage reaches the cap. It resets on{" "}
        {longDate(resetsOn)} (UTC). Calls with unknown cost count in tokens only.
        {!demo && " Deleting your usage history makes the cap count from zero again for this month."}
      </p>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      {saved && <p className="text-xs text-muted-foreground">Saved.</p>}
    </fieldset>
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
