// @vitest-environment jsdom
// The date on a proposal card (thought-dates task 5.2): the proposed date, its
// fields, two date choices, and what confirm sends.

// Before any date is read: the browser's zone is west of UTC.
process.env.TZ = "America/Los_Angeles";

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  delta,
  done,
  errorResponse,
  fakeApi,
  json,
  loadout,
  detail,
  proposalEvent,
  streamOf,
  toolEvent,
  type WirePart,
} from "@/test/fake-api";

import { Chat } from "./chat";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/app",
}));

const ZONE = "America/Los_Angeles";
const CONFIRM = "POST /api/conversations/c1/proposals/p1/confirm";
// The model's dates carry the turn's zone; confirm sends the browser's.
const FRIDAY_AT_7 = { start: "2026-10-02T19:00", end: null, time_zone: "Europe/Oslo" };
const NEXT_FRIDAY_AT_7 = { start: "2026-10-09T19:00", end: null, time_zone: "Europe/Oslo" };
const TRIP = { start: "2026-11-03", end: "2026-11-06", time_zone: "Europe/Oslo" };

const DINNER: WirePart = {
  title: "Dinner with Sam",
  summary: "Dinner with Sam.",
  tags: ["sam"],
  category: "task",
  when: FRIDAY_AT_7,
  when_choices: null,
};
const OAT: WirePart = { title: "Oat milk", summary: "Buy oat milk.", tags: ["groceries"], category: "task" };
const OSLO: WirePart = { title: "Oslo trip", summary: "Trip to Oslo.", tags: ["travel"], category: "idea", when: TRIP };
const UNCLEAR: WirePart = { ...DINNER, when: null, when_choices: [FRIDAY_AT_7, NEXT_FRIDAY_AT_7] };

function send(text: string) {
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
}

const proposing = (...parts: WirePart[]) => () =>
  streamOf(
    toolEvent("propose_thought", "start"),
    proposalEvent("p1", parts),
    toolEvent("propose_thought", "end", "Proposed a thought to file"),
    delta("Want to keep it?"),
    done,
  );

const saved = () => json(200, { saved: true, thought_id: "t1", message: "Saved." });

/** The chat with a proposal of these parts, and the requests it made. */
async function proposed(parts: WirePart[], confirm: Parameters<typeof fakeApi>[0][string] = saved) {
  const api = fakeApi({
    "GET /api/settings/models": json(200, loadout()),
    "GET /api/conversations/c1": json(200, detail()),
    "POST /api/chat": proposing(...parts),
    [CONFIRM]: confirm,
  });
  render(<Chat conversationId="c1" />);
  await screen.findByLabelText("Message");
  send("/push it");
  await screen.findByRole("region", { name: /Proposals? to file/ });
  return api;
}

const card = (title: string) => screen.getByRole("group", { name: `Thought to file: ${title}` });
const field = (title: string, label: string) => within(card(title)).queryByLabelText(label);
const button = (title: string, name: string) => within(card(title)).getByRole("button", { name });

function type(title: string, label: string, value: string) {
  fireEvent.change(within(card(title)).getByLabelText(label), { target: { value } });
}

/** Confirms the card and answers the `when` it sent. */
async function confirmedWhen(calls: { path: string; body: unknown }[], title: string, savedAs = title) {
  fireEvent.click(button(title, "Confirm"));
  await screen.findByRole("group", { name: `Saved: ${savedAs}` });
  const body = calls.find((c) => c.path.endsWith("/confirm"))?.body as Record<string, unknown>;
  expect(body).toHaveProperty("when");
  return body.when;
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("a proposal card's date", () => {
  it("shows the proposed date in the fields, with the title and the rest", async () => {
    await proposed([DINNER]);

    expect(field("Dinner with Sam", "Title")).toHaveValue("Dinner with Sam");
    expect(field("Dinner with Sam", "Start date")).toHaveValue("2026-10-02");
    expect(field("Dinner with Sam", "Start time")).toHaveValue("19:00");
    expect(field("Dinner with Sam", "End date")).not.toBeInTheDocument();
    expect(within(card("Dinner with Sam")).queryByRole("button", { name: "Add date" })).not.toBeInTheDocument();
  });

  it("shows a trip's start and end with no times", async () => {
    await proposed([OSLO]);

    expect(field("Oslo trip", "Start date")).toHaveValue("2026-11-03");
    expect(field("Oslo trip", "Start time")).toHaveValue("");
    expect(field("Oslo trip", "End date")).toHaveValue("2026-11-06");
    // No start time, so no end time.
    expect(field("Oslo trip", "End time")).not.toBeInTheDocument();
  });

  it("offers Add date when there is none, and confirms no date as null", async () => {
    const { calls } = await proposed([OAT]);

    expect(button("Oat milk", "Add date")).toBeInTheDocument();
    expect(field("Oat milk", "Start date")).not.toBeInTheDocument();

    expect(await confirmedWhen(calls, "Oat milk")).toBeNull();
  });

  it("sends a date added on the card with the browser's zone", async () => {
    const { calls } = await proposed([OAT]);

    fireEvent.click(button("Oat milk", "Add date"));
    type("Oat milk", "Start date", "2026-10-05");

    expect(await confirmedWhen(calls, "Oat milk")).toEqual({ start: "2026-10-05", end: null, time_zone: ZONE });
  });

  it("sends a changed time to confirm, with the browser's zone", async () => {
    const { calls } = await proposed([DINNER]);

    type("Dinner with Sam", "Start time", "19:30");

    expect(await confirmedWhen(calls, "Dinner with Sam")).toEqual({
      start: "2026-10-02T19:30",
      end: null,
      time_zone: ZONE,
    });
  });

  it("sends a cleared date as null", async () => {
    const { calls } = await proposed([DINNER]);

    fireEvent.click(button("Dinner with Sam", "Clear date"));

    expect(field("Dinner with Sam", "Start date")).not.toBeInTheDocument();
    expect(button("Dinner with Sam", "Add date")).toBeInTheDocument();
    expect(await confirmedWhen(calls, "Dinner with Sam")).toBeNull();
  });

  it("starts the end time as the start time", async () => {
    const { calls } = await proposed([DINNER]);

    fireEvent.click(button("Dinner with Sam", "Add end"));

    expect(field("Dinner with Sam", "End date")).toHaveValue("2026-10-02");
    expect(field("Dinner with Sam", "End time")).toHaveValue("19:00");
    type("Dinner with Sam", "End time", "22:00");
    expect(await confirmedWhen(calls, "Dinner with Sam")).toEqual({
      start: "2026-10-02T19:00",
      end: "2026-10-02T22:00",
      time_zone: ZONE,
    });
  });

  it("gives an end the start time once the start gets one", async () => {
    await proposed([OSLO]);

    type("Oslo trip", "Start time", "08:15");

    expect(field("Oslo trip", "End date")).toHaveValue("2026-11-06");
    expect(field("Oslo trip", "End time")).toHaveValue("08:15");
  });

  it("shows a refused date on the card and keeps what the user typed", async () => {
    await proposed(
      [DINNER],
      errorResponse(422, "validation_error", "when: the end must not be before the start"),
    );

    fireEvent.click(button("Dinner with Sam", "Add end"));
    type("Dinner with Sam", "End date", "2026-10-01");
    fireEvent.click(button("Dinner with Sam", "Confirm"));

    expect(await within(card("Dinner with Sam")).findByRole("alert")).toHaveTextContent(
      "when: the end must not be before the start",
    );
    expect(field("Dinner with Sam", "Start date")).toHaveValue("2026-10-02");
    expect(field("Dinner with Sam", "End date")).toHaveValue("2026-10-01");
    expect(field("Dinner with Sam", "End time")).toHaveValue("19:00");
    expect(button("Dinner with Sam", "Confirm")).toBeEnabled();
  });

  it("keeps the first part's date on a merge", async () => {
    const { calls } = await proposed([DINNER, OSLO]);

    fireEvent.click(screen.getByRole("button", { name: "Merge into one" }));

    const merged = await screen.findByRole("group", { name: "Thought to file: Dinner with Sam" });
    expect(within(merged).getByLabelText("Start date")).toHaveValue("2026-10-02");
    expect(within(merged).getByLabelText("Start time")).toHaveValue("19:00");
    expect(within(merged).queryByLabelText("End date")).not.toBeInTheDocument();
    expect(await confirmedWhen(calls, "Dinner with Sam")).toEqual({
      start: "2026-10-02T19:00",
      end: null,
      time_zone: ZONE,
    });
    expect((calls.find((c) => c.path.endsWith("/confirm"))?.body as { parts: number[] }).parts).toEqual([0, 1]);
  });

  it("keeps the first part's date choices on a merge", async () => {
    await proposed([UNCLEAR, OAT]);

    fireEvent.click(screen.getByRole("button", { name: "Merge into one" }));

    const merged = await screen.findByRole("group", { name: "Thought to file: Dinner with Sam" });
    expect(within(merged).getByRole("button", { name: "Fri 2 Oct, 19:00" })).toBeInTheDocument();
    expect(within(merged).getByRole("button", { name: "Fri 9 Oct, 19:00" })).toBeInTheDocument();
    expect(within(merged).getByRole("button", { name: "Confirm" })).toBeDisabled();
  });
});

describe("a proposal card with two date choices", () => {
  it("shows both choices and No date, with no fields, and Confirm off until a pick", async () => {
    await proposed([UNCLEAR]);

    const choices = within(card("Dinner with Sam")).getByRole("group", { name: "Which date?" });
    expect(within(choices).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Fri 2 Oct, 19:00",
      "Fri 9 Oct, 19:00",
      "No date",
    ]);
    expect(field("Dinner with Sam", "Start date")).not.toBeInTheDocument();
    expect(within(card("Dinner with Sam")).queryByRole("button", { name: "Add date" })).not.toBeInTheDocument();
    expect(button("Dinner with Sam", "Confirm")).toBeDisabled();
  });

  it("fills the fields with a pick, which confirm sends as an object", async () => {
    const { calls } = await proposed([UNCLEAR]);

    fireEvent.click(button("Dinner with Sam", "Fri 9 Oct, 19:00"));

    expect(button("Dinner with Sam", "Fri 9 Oct, 19:00")).toHaveAttribute("aria-pressed", "true");
    expect(field("Dinner with Sam", "Start date")).toHaveValue("2026-10-09");
    expect(field("Dinner with Sam", "Start time")).toHaveValue("19:00");
    expect(button("Dinner with Sam", "Confirm")).toBeEnabled();
    expect(await confirmedWhen(calls, "Dinner with Sam")).toEqual({
      start: "2026-10-09T19:00",
      end: null,
      time_zone: ZONE,
    });
  });

  it("clears the fields for No date, which confirm sends as null", async () => {
    const { calls } = await proposed([UNCLEAR]);

    fireEvent.click(button("Dinner with Sam", "Fri 2 Oct, 19:00"));
    expect(field("Dinner with Sam", "Start date")).toHaveValue("2026-10-02");
    fireEvent.click(button("Dinner with Sam", "No date"));

    expect(field("Dinner with Sam", "Start date")).not.toBeInTheDocument();
    expect(button("Dinner with Sam", "Add date")).toBeInTheDocument();
    await waitFor(() => expect(button("Dinner with Sam", "Confirm")).toBeEnabled());
    expect(await confirmedWhen(calls, "Dinner with Sam")).toBeNull();
  });

  it("lets the user adjust a picked date before confirming", async () => {
    const { calls } = await proposed([UNCLEAR]);

    fireEvent.click(button("Dinner with Sam", "Fri 2 Oct, 19:00"));
    type("Dinner with Sam", "Start time", "19:30");

    expect(await confirmedWhen(calls, "Dinner with Sam")).toEqual({
      start: "2026-10-02T19:30",
      end: null,
      time_zone: ZONE,
    });
  });
});
