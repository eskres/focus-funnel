// @vitest-environment jsdom
// Editing a thought's date in the sheet (thought-dates task 4.2): the set,
// clear, and end-before-start scenarios of the thought-detail-view delta.

// Before any date is read: the browser's zone is west of UTC, so a date shown
// through `new Date("2026-10-05")` would read as the day before.
process.env.TZ = "America/Los_Angeles";

import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { openThought } from "@/lib/thought-link";
import { errorResponse, fakeApi, json } from "@/test/fake-api";

import { ThoughtSheet } from "./thought-sheet";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => window.location.pathname,
}));

const ZONE = "America/Los_Angeles";
const THOUGHT = {
  id: "t1",
  title: "Call the plumber",
  summary: "Call the plumber about the kitchen tap.",
  tags: ["home"],
  category: "task",
  raw_text: null,
  when: null,
  created_at: "2026-09-20T08:00:00Z",
  updated_at: "2026-09-21T08:00:00Z",
  origin: null,
};
const DINNER = { start: "2026-10-02T19:00", end: null, time_zone: "Europe/Oslo" };
const TRIP = { start: "2026-11-03", end: "2026-11-06", time_zone: "Europe/Oslo" };
const PATCH = "PATCH /api/thoughts/t1";

type Call = { method: string; path: string; body: unknown };
const changes = (calls: Call[]) => calls.filter((c) => c.method !== "GET");

function api(thought: object, routes: Parameters<typeof fakeApi>[0] = {}) {
  return fakeApi({ "GET /api/thoughts/t1": json(200, thought), ...routes });
}

/** The sheet open on t1, once the thought has loaded. */
async function openSheet(title = THOUGHT.title) {
  window.history.replaceState(null, "", "/app/upcoming");
  openThought("t1");
  render(<ThoughtSheet />);
  const sheet = await screen.findByRole("dialog", { name: title });
  await within(sheet).findByRole("button", { name: "Edit" });
  return sheet;
}

function startEdit(sheet: HTMLElement) {
  fireEvent.click(within(sheet).getByRole("button", { name: "Edit" }));
  return within(sheet).getByRole("region", { name: "Edit thought" });
}

function type(form: HTMLElement, label: string, value: string) {
  fireEvent.change(within(form).getByLabelText(label), { target: { value } });
}

const dateLine = (sheet: HTMLElement) => within(sheet).queryByText(/^When: /);

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("editing a thought's date in the sheet", () => {
  it("sets a start on a thought with no date, with no time and no end", async () => {
    const answer = { ...THOUGHT, when: { start: "2026-10-05", end: null, time_zone: ZONE } };
    const { calls } = api(THOUGHT, { [PATCH]: json(200, answer) });
    const sheet = await openSheet();
    expect(dateLine(sheet)).not.toBeInTheDocument();
    const form = startEdit(sheet);
    expect(within(form).queryByLabelText("Start date")).not.toBeInTheDocument();

    fireEvent.click(within(form).getByRole("button", { name: "Add date" }));
    type(form, "Start date", "2026-10-05");
    expect(within(form).getByLabelText("Start time")).toHaveValue("");
    expect(within(form).queryByLabelText("End date")).not.toBeInTheDocument();
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    await within(sheet).findByRole("button", { name: "Edit" });
    expect(changes(calls)).toEqual([
      { method: "PATCH", path: "/api/thoughts/t1", body: { when: { start: "2026-10-05", end: null, time_zone: ZONE } } },
    ]);
    // Monday as written, not Sunday, though the browser is west of UTC.
    expect(dateLine(sheet)).toHaveTextContent(/^When: Mon 5 Oct 2026$/);
    expect(within(sheet).getByText(/^Filed .* · changed /)).toBeInTheDocument();
  });

  it("fills the fields with the current date, and starts the end time as the start time", async () => {
    const { calls } = api({ ...THOUGHT, when: DINNER }, { [PATCH]: json(200, { ...THOUGHT, when: DINNER }) });
    const sheet = await openSheet();
    expect(dateLine(sheet)).toHaveTextContent("When: Fri 2 Oct 2026, 19:00");
    const form = startEdit(sheet);

    expect(within(form).getByLabelText("Start date")).toHaveValue("2026-10-02");
    expect(within(form).getByLabelText("Start time")).toHaveValue("19:00");
    fireEvent.click(within(form).getByRole("button", { name: "Add end" }));
    expect(within(form).getByLabelText("End date")).toHaveValue("2026-10-02");
    expect(within(form).getByLabelText("End time")).toHaveValue("19:00");
    type(form, "End time", "21:30");
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    await within(sheet).findByRole("button", { name: "Edit" });
    expect(changes(calls)).toEqual([
      {
        method: "PATCH",
        path: "/api/thoughts/t1",
        body: { when: { start: "2026-10-02T19:00", end: "2026-10-02T21:30", time_zone: ZONE } },
      },
    ]);
  });

  it("sends no date when only another field changed", async () => {
    const { calls } = api({ ...THOUGHT, when: DINNER }, { [PATCH]: json(200, { ...THOUGHT, when: DINNER }) });
    const sheet = await openSheet();
    const form = startEdit(sheet);

    type(form, "Title", "Call the plumber today");
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    await within(sheet).findByRole("button", { name: "Edit" });
    expect(changes(calls)).toEqual([
      { method: "PATCH", path: "/api/thoughts/t1", body: { title: "Call the plumber today" } },
    ]);
  });

  it("clears the date of a dated thought", async () => {
    const { calls } = api({ ...THOUGHT, when: TRIP }, { [PATCH]: json(200, { ...THOUGHT, when: null }) });
    const sheet = await openSheet();
    expect(dateLine(sheet)).toHaveTextContent("When: Tue 3 Nov 2026 – Fri 6 Nov 2026");
    const form = startEdit(sheet);

    fireEvent.click(within(form).getByRole("button", { name: "Clear date" }));
    expect(within(form).queryByLabelText("Start date")).not.toBeInTheDocument();
    expect(within(form).getByRole("button", { name: "Add date" })).toBeInTheDocument();
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    await within(sheet).findByRole("button", { name: "Edit" });
    expect(changes(calls)).toEqual([{ method: "PATCH", path: "/api/thoughts/t1", body: { when: null } }]);
    expect(dateLine(sheet)).not.toBeInTheDocument();
  });

  it("shows the refusal naming the date, keeps the input, and the thought unchanged, for an end before the start", async () => {
    const { calls } = api(
      { ...THOUGHT, when: TRIP },
      { [PATCH]: errorResponse(422, "validation_error", "when: the end must not be before the start") },
    );
    const sheet = await openSheet();
    const form = startEdit(sheet);

    type(form, "End date", "2026-11-01");
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));

    expect(await within(form).findByRole("alert")).toHaveTextContent("when: the end must not be before the start");
    expect(changes(calls)).toEqual([
      {
        method: "PATCH",
        path: "/api/thoughts/t1",
        body: { when: { start: "2026-11-03", end: "2026-11-01", time_zone: ZONE } },
      },
    ]);
    // Still editing, with what the user typed.
    expect(within(form).getByLabelText("Start date")).toHaveValue("2026-11-03");
    expect(within(form).getByLabelText("End date")).toHaveValue("2026-11-01");
    expect(within(form).getByRole("button", { name: "Save" })).toBeEnabled();
    // The sheet still shows the date as it is stored.
    expect(dateLine(sheet)).toHaveTextContent("When: Tue 3 Nov 2026 – Fri 6 Nov 2026");
  });
});
