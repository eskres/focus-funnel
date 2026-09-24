// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fakeApi, json } from "@/test/fake-api";

import { niceTicks, tickDecimals } from "./usage-chart";
import { UsageSection } from "./usage-settings";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

const empty = { cost_usd: 0, tokens: 0, unknown_cost_calls: 0, calls: 0 };

function day(n: number, extra: Record<string, number> = {}) {
  const date = new Date(Date.UTC(2026, 8, 1 + n)).toISOString().slice(0, 10);
  return { date, ...empty, ...extra };
}

function report(days: number, used: Record<number, Record<string, number>> = {}, extra = {}) {
  const list = Array.from({ length: days }, (_, n) => day(n, used[n]));
  const calls = list.reduce((sum, d) => sum + d.calls, 0);
  return {
    days: list,
    by_model: calls
      ? [
          { provider_id: "nebius", model: "vendor/big", cost_usd: 0.012, tokens: 9000, unknown_cost_calls: 0, calls: 2 },
          { provider_id: "nebius", model: "vendor/nano", cost_usd: 0.00012, tokens: 910, unknown_cost_calls: 1, calls: 3 },
        ]
      : [],
    month: { start: "2026-09-01", cost_usd: 0.01212, tokens: 9910, unknown_cost_calls: 1, calls },
    warning: null,
    consoles: [],
    ...extra,
  };
}

const used = { 3: { cost_usd: 0.012, tokens: 9000, calls: 2 }, 5: { cost_usd: 0.00012, tokens: 910, calls: 3, unknown_cost_calls: 1 } };

describe("UsageSection", () => {
  it("draws a bar per day with the month total, the split by model, and the estimate label", async () => {
    fakeApi({ "GET /api/usage": json(200, report(30, used)) });
    render(<UsageSection />);

    expect(await screen.findAllByTestId("usage-bar")).toHaveLength(30);
    expect(document.querySelectorAll("[data-testid=usage-bar] path")).toHaveLength(2);
    expect(screen.getByTestId("month-total")).toHaveTextContent("$0.012");
    expect(screen.getByText("September so far (estimate)")).toBeInTheDocument();
    expect(screen.getByText(/from the providers' list prices/)).toBeInTheDocument();
    const byModel = screen.getByRole("table", { name: "Spend by model" });
    expect(within(byModel).getByText("vendor/big")).toBeInTheDocument();
    expect(within(byModel).getByText("$0.00012*")).toBeInTheDocument();
    expect(screen.getByText(/Some calls have no listed price/)).toBeInTheDocument();
    expect(screen.getByText(/1 with unknown cost counted in tokens only/)).toBeInTheDocument();
  });

  it("shows a bar's values on hover and focus", async () => {
    fakeApi({ "GET /api/usage": json(200, report(30, used)) });
    render(<UsageSection />);
    const bars = await screen.findAllByTestId("usage-bar");

    fireEvent.pointerEnter(bars[3]);
    const tooltip = screen.getByRole("tooltip");
    expect(tooltip).toHaveTextContent("$0.012");
    expect(tooltip).toHaveTextContent("Sep 4 · 9,000 tokens");

    fireEvent.pointerLeave(bars[3]);
    fireEvent.focus(bars[5]);
    expect(screen.getByRole("tooltip")).toHaveTextContent("1 with unknown cost");
    expect(bars[5]).toHaveAccessibleName(
      "$0.00012 on Sep 6, 910 tokens, 1 call with unknown cost",
    );
  });

  it("says that nothing has been used yet", async () => {
    fakeApi({ "GET /api/usage": json(200, report(30)) });
    render(<UsageSection />);

    expect(await screen.findByText("Nothing has been used yet.")).toBeInTheDocument();
    expect(screen.queryAllByTestId("usage-bar")).toHaveLength(0);
    expect(screen.queryByRole("table", { name: "Spend by model" })).not.toBeInTheDocument();
  });

  it("refetches when the period changes", async () => {
    const { calls } = fakeApi({
      "GET /api/usage": (url) =>
        json(200, report(Number(url.searchParams.get("days")), { 1: { cost_usd: 1, tokens: 5, calls: 1 } })),
    });
    render(<UsageSection />);
    expect(await screen.findAllByTestId("usage-bar")).toHaveLength(30);

    fireEvent.click(screen.getByRole("button", { name: "90 days" }));

    await waitFor(() => expect(screen.getAllByTestId("usage-bar")).toHaveLength(90));
    expect(calls.map((c) => c.path)).toEqual(["/api/usage?days=30", "/api/usage?days=90"]);
    expect(screen.getByRole("button", { name: "90 days" })).toHaveAttribute("aria-pressed", "true");
  });

  it("shows no balance, and links the provider's console for it", async () => {
    fakeApi({
      "GET /api/usage": json(
        200,
        report(30, used, {
          consoles: [{ provider_id: "nebius", label: "Nebius Token Factory", url: "https://tokenfactory.nebius.com/" }],
        }),
      ),
    });
    render(<UsageSection />);

    const link = await screen.findByRole("link", { name: "Nebius Token Factory" });
    expect(link).toHaveAttribute("href", "https://tokenfactory.nebius.com/");
    expect(screen.getByText(/balance is only shown in your provider's console/)).toBeInTheDocument();
    expect(screen.queryByText(/balance:/i)).not.toBeInTheDocument();
  });

  it("shows the warning threshold and whether it was passed", async () => {
    fakeApi({
      "GET /api/usage": json(200, report(30, used, { warning: { unit: "usd", amount: 0.01, reached: true } })),
    });
    render(<UsageSection />);

    expect(await screen.findByText(/Warning threshold: \$0\.01\./)).toBeInTheDocument();
    expect(screen.getByText("Reached this month.")).toBeInTheDocument();
  });
});

describe("niceTicks", () => {
  it("rounds to clean steps from zero", () => {
    expect(niceTicks(0)).toEqual([0]);
    expect(niceTicks(0.012)).toEqual([0, 0.005, 0.01, 0.015]);
    expect(niceTicks(7)).toEqual([0, 2.5, 5, 7.5]);
  });

  it("labels the ticks with the places their step needs", () => {
    expect(tickDecimals([0, 0.005, 0.01, 0.015])).toBe(3);
    expect(tickDecimals([0, 0.0025, 0.005])).toBe(4);
    expect(tickDecimals([0, 2.5, 5, 7.5])).toBe(2);
  });
});
