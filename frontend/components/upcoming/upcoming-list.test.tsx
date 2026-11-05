// @vitest-environment jsdom
// The Upcoming page (thought-dates task 5.5): day headings, item fields,
// opening an item in the sheet, and the list after the sheet closes.

// Before any date is read: the browser's zone is west of UTC.
process.env.TZ = "America/Los_Angeles";

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { errorResponse, fakeApi, json } from "@/test/fake-api";

import { byDay, itemTime, UpcomingList } from "./upcoming-list";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => window.location.pathname,
}));

const ZONE = "America/Los_Angeles";
const UPCOMING = "GET /api/thoughts/upcoming";

const when = (start: string, end: string | null = null) => ({ start, end, time_zone: ZONE });
const item = (id: string, title: string, start: string, extra: Record<string, unknown> = {}) => ({
  id,
  title,
  category: null,
  when: when(start),
  ...extra,
});

const TRIP = item("t-trip", "Oslo trip", "2026-09-29", { when: when("2026-09-29", "2026-10-02"), category: "idea" });
const TODAY_CALL = item("t-call", "Call the plumber", "2026-09-30", { category: "task" });
const TOMORROW = item("t-gym", "Gym", "2026-10-01T07:30");
const DINNER = item("t-dinner", "Dinner with Sam", "2026-10-02T19:00", { category: "event" });
const MONDAY = item("t-dentist", "Dentist", "2026-10-05T09:30", {
  when: when("2026-10-05T09:30", "2026-10-05T10:15"),
  category: "task",
});

const thought = (from: { id: string; title: string; category: string | null; when: unknown }) => ({
  id: from.id,
  title: from.title,
  summary: `About ${from.title}.`,
  tags: [],
  category: from.category,
  raw_text: null,
  when: from.when,
  created_at: "2026-09-20T08:00:00Z",
  updated_at: "2026-09-21T08:00:00Z",
  origin: null,
});

beforeEach(() => {
  // Wednesday 30 September 2026, 10:00 in California. Only Date is faked, so
  // promises and the testing library's waiting still run.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date(2026, 8, 30, 10, 0));
  window.history.replaceState(null, "", "/app/upcoming");
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/");
});

async function openPage() {
  render(<UpcomingList />);
  await waitFor(() => expect(screen.queryByText("Loading…")).not.toBeInTheDocument());
}

const headings = () => screen.getAllByRole("heading", { level: 2 }).map((h) => h.textContent);
const day = (heading: string) => screen.getByRole("region", { name: heading });
const itemButton = (title: string) => screen.getByRole("button", { name: new RegExp(title) });

describe("the Upcoming page", () => {
  it("asks for the browser's local today", async () => {
    const { calls } = fakeApi({ [UPCOMING]: json(200, { items: [], more: false }) });
    // 03:00 UTC on 1 October is still 30 September in California.
    vi.setSystemTime(new Date(Date.UTC(2026, 9, 1, 3, 0)));

    await openPage();

    expect(calls.map((c) => c.path)).toEqual(["/api/thoughts/upcoming?from=2026-09-30"]);
  });

  it("groups by day under Today, Tomorrow, and the weekday and date", async () => {
    fakeApi({ [UPCOMING]: json(200, { items: [TRIP, TODAY_CALL, TOMORROW, DINNER, MONDAY], more: false }) });

    await openPage();

    expect(headings()).toEqual(["Today", "Tomorrow", "Friday 2 October", "Monday 5 October"]);
    // The trip started yesterday, so it is listed under Today.
    expect(within(day("Today")).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "until Fri 2 OctOslo tripidea",
      "Call the plumbertask",
    ]);
    expect(within(day("Tomorrow")).getByRole("button")).toHaveTextContent("07:30Gym");
    expect(within(day("Monday 5 October")).getByRole("button")).toHaveTextContent("09:30 – 10:15Dentisttask");
    expect(screen.queryByText(/coming up than this page shows/)).not.toBeInTheDocument();
  });

  it("shows an item's time, title, and category", async () => {
    fakeApi({ [UPCOMING]: json(200, { items: [DINNER], more: false }) });

    await openPage();

    const dinner = within(day("Friday 2 October")).getByRole("button");
    expect(within(dinner).getByText("19:00")).toBeInTheDocument();
    expect(within(dinner).getByText("Dinner with Sam")).toBeInTheDocument();
    expect(within(dinner).getByText("event")).toBeInTheDocument();
  });

  it("says when nothing is coming up", async () => {
    fakeApi({ [UPCOMING]: json(200, { items: [], more: false }) });

    await openPage();

    expect(screen.getByText("Nothing is coming up.")).toBeInTheDocument();
    expect(screen.queryAllByRole("heading", { level: 2 })).toEqual([]);
  });

  it("says when more exist than the page shows", async () => {
    fakeApi({ [UPCOMING]: json(200, { items: [DINNER], more: true }) });

    await openPage();

    expect(screen.getByText("More dated thoughts are coming up than this page shows.")).toBeInTheDocument();
  });

  it("says so when the list cannot be loaded", async () => {
    fakeApi({ [UPCOMING]: errorResponse(500, "internal_error", "Something went wrong.") });

    await openPage();

    expect(screen.getByRole("alert")).toHaveTextContent("The list could not be loaded. Try again.");
  });

  it("opens an item in the sheet over the list, with the address naming it", async () => {
    fakeApi({
      [UPCOMING]: json(200, { items: [TODAY_CALL, DINNER], more: false }),
      "GET /api/thoughts/t-dinner": json(200, thought(DINNER)),
    });
    await openPage();

    fireEvent.click(itemButton("Dinner with Sam"));

    const sheet = await screen.findByRole("dialog", { name: "Dinner with Sam" });
    expect(await within(sheet).findByText("When: Fri 2 Oct 2026, 19:00")).toBeInTheDocument();
    expect(window.location.pathname + window.location.search).toBe("/app/upcoming?thought=t-dinner");
    // The list stays behind it.
    expect(itemButton("Call the plumber")).toBeInTheDocument();
  });

  it("drops an item whose date moved to the past once the sheet closes", async () => {
    let moved = false;
    const lastWeek = when("2026-09-21T19:00");
    const { calls } = fakeApi({
      [UPCOMING]: () => json(200, { items: moved ? [TODAY_CALL] : [TODAY_CALL, DINNER], more: false }),
      "GET /api/thoughts/t-dinner": () => json(200, thought(moved ? { ...DINNER, when: lastWeek } : DINNER)),
      "PATCH /api/thoughts/t-dinner": () => {
        moved = true;
        return json(200, thought({ ...DINNER, when: lastWeek }));
      },
    });
    await openPage();

    fireEvent.click(itemButton("Dinner with Sam"));
    const sheet = await screen.findByRole("dialog", { name: "Dinner with Sam" });
    fireEvent.click(await within(sheet).findByRole("button", { name: "Edit" }));
    const form = within(sheet).getByRole("region", { name: "Edit thought" });
    fireEvent.change(within(form).getByLabelText("Start date"), { target: { value: "2026-09-21" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save" }));
    expect(await within(sheet).findByText("When: Mon 21 Sep 2026, 19:00")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ when: lastWeek });

    fireEvent.click(within(sheet).getByRole("button", { name: "Close" }));

    await waitFor(() => expect(screen.queryByRole("button", { name: /Dinner with Sam/ })).not.toBeInTheDocument());
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(itemButton("Call the plumber")).toBeInTheDocument();
    expect(calls.filter((c) => c.path.startsWith("/api/thoughts/upcoming")).at(-1)?.path).toBe(
      "/api/thoughts/upcoming?from=2026-09-30",
    );
  });

  it("loads the list again when the sheet closes, with no change made", async () => {
    const { calls } = fakeApi({
      [UPCOMING]: json(200, { items: [DINNER], more: false }),
      "GET /api/thoughts/t-dinner": json(200, thought(DINNER)),
    });
    await openPage();
    const loads = () => calls.filter((c) => c.path.startsWith("/api/thoughts/upcoming")).length;
    expect(loads()).toBe(1);

    fireEvent.click(itemButton("Dinner with Sam"));
    const sheet = await screen.findByRole("dialog", { name: "Dinner with Sam" });
    expect(loads()).toBe(1);
    fireEvent.click(within(sheet).getByRole("button", { name: "Close" }));

    await waitFor(() => expect(loads()).toBe(2));
  });
});

describe("an item's time", () => {
  it("is the start time, a same-day range, the end of a span over days, or nothing", () => {
    expect(itemTime(when("2026-10-02T19:00"))).toBe("19:00");
    expect(itemTime(when("2026-10-05T09:30", "2026-10-05T10:15"))).toBe("09:30 – 10:15");
    expect(itemTime(when("2026-11-03", "2026-11-06"))).toBe("until Fri 6 Nov");
    expect(itemTime(when("2026-11-03T08:00", "2026-11-06T18:00"))).toBe("until Fri 6 Nov, 18:00");
    expect(itemTime(when("2026-10-02"))).toBe("");
  });

  it("groups items that started before today under today", () => {
    expect(byDay([TRIP, TODAY_CALL, DINNER], "2026-09-30").map((d) => [d.day, d.items.length])).toEqual([
      ["2026-09-30", 2],
      ["2026-10-02", 1],
    ]);
  });
});
