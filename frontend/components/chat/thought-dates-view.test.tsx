// @vitest-environment jsdom
// A thought's date in the sheet's view mode (thought-dates task 5.3): the
// "Dated thought", "Trip over several days", and "No date" scenarios of the
// thought-detail-view delta.

// Before any date is read: the browser's zone is west of UTC, so a date shown
// through `new Date("2026-10-02")` would read as the day before.
process.env.TZ = "America/Los_Angeles";

import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { openThought } from "@/lib/thought-link";
import { fakeApi, json } from "@/test/fake-api";

import { ThoughtSheet } from "./thought-sheet";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => window.location.pathname,
}));

const THOUGHT = {
  id: "t1",
  title: "Dinner with Sam",
  summary: "Dinner with Sam at the new place.",
  tags: ["sam"],
  category: "task",
  raw_text: null,
  when: null,
  created_at: "2026-09-28T08:00:00Z",
  updated_at: "2026-09-29T08:00:00Z",
  origin: null,
};

/** The sheet open on a thought, once it has loaded. */
async function openSheet(thought: object, title = THOUGHT.title) {
  fakeApi({ "GET /api/thoughts/t1": json(200, thought) });
  window.history.replaceState(null, "", "/app");
  openThought("t1");
  render(<ThoughtSheet />);
  const sheet = await screen.findByRole("dialog", { name: title });
  await within(sheet).findByRole("button", { name: "Edit" });
  return sheet;
}

/** The filed and changed line. */
const stamps = (sheet: HTMLElement) => within(sheet).getByText(/^Filed .* · changed /);
const dateLine = (sheet: HTMLElement) => within(sheet).queryByText(/^When: /);

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("a thought's date in the sheet", () => {
  it("shows a dated thought's day and time apart from the filed and changed dates", async () => {
    const sheet = await openSheet({
      ...THOUGHT,
      when: { start: "2026-10-02T19:00", end: null, time_zone: "Europe/Oslo" },
    });

    const line = dateLine(sheet);
    expect(line).toHaveTextContent(/^When: Fri 2 Oct 2026, 19:00$/);
    // Its own line: the filed and changed dates say nothing of it, and it of them.
    expect(stamps(sheet)).not.toHaveTextContent(/When|2 Oct|19:00/);
    expect(line).not.toContainElement(stamps(sheet));
    expect(stamps(sheet)).not.toContainElement(line);
  });

  it("shows a trip's start and end", async () => {
    const sheet = await openSheet(
      { ...THOUGHT, title: "Oslo trip", when: { start: "2026-11-03", end: "2026-11-06", time_zone: "Europe/Oslo" } },
      "Oslo trip",
    );

    expect(dateLine(sheet)).toHaveTextContent(/^When: Tue 3 Nov 2026 – Fri 6 Nov 2026$/);
    expect(stamps(sheet)).toBeInTheDocument();
  });

  it("shows no date for a thought with none", async () => {
    const sheet = await openSheet(THOUGHT);

    expect(dateLine(sheet)).not.toBeInTheDocument();
    expect(within(sheet).queryByText(/When/)).not.toBeInTheDocument();
    expect(stamps(sheet)).toBeInTheDocument();
  });

  it("shows no date for a thought from an older server, which sends no `when`", async () => {
    const older: Record<string, unknown> = { ...THOUGHT };
    delete older.when;
    const sheet = await openSheet(older);

    expect(dateLine(sheet)).not.toBeInTheDocument();
  });
});
