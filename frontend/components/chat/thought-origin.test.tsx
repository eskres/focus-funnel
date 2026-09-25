// @vitest-environment jsdom
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { openOriginHere, openThought } from "@/lib/thought-link";
import {
  conversationEvent,
  delta,
  detail,
  done,
  fakeApi,
  json,
  loadout,
  storedMessage,
  streamOf,
  wireProposal,
  type WirePart,
} from "@/test/fake-api";

import { Chat } from "./chat";

const push = vi.hoisted(() => vi.fn());
vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => window.location.pathname,
}));

const OAT: WirePart = { title: "Oat milk", summary: "Buy oat milk.", tags: [], category: "task", thought_id: "t1" };
const EGGS: WirePart = { title: "Eggs", summary: "Buy eggs.", tags: [], category: "task" };

const ORIGIN = {
  conversation_id: "c1",
  conversation_title: "Summer trip",
  archived: false,
  proposal_id: "p1",
  proposed_at: "2026-09-20T08:00:00Z",
};

const thought = (origin: unknown) => ({
  id: "t1",
  title: "Oat milk",
  summary: "Buy oat milk.",
  tags: [],
  category: "task",
  raw_text: null,
  created_at: "2026-09-20T08:00:00Z",
  updated_at: "2026-09-20T08:00:00Z",
  ...(origin === undefined ? {} : { origin }),
});

/** A conversation with two proposals: p1 early, p2 later, and more talk after. */
const stored = (extra: { compacted?: boolean; held?: boolean } = {}) =>
  detail({
    held_proposal_id: extra.held ? "p2" : null,
    messages: [
      storedMessage(0, "user", "/push oat milk", { compacted: extra.compacted ?? false }),
      storedMessage(1, "assistant", "Noted the milk.", { compacted: extra.compacted ?? false }),
      storedMessage(2, "user", "and eggs"),
      storedMessage(3, "assistant", "Noted the eggs."),
      storedMessage(4, "user", "thanks"),
      storedMessage(5, "assistant", "Any time."),
    ],
    proposals: [wireProposal("p1", [OAT], 1), wireProposal("p2", [EGGS], 3)],
  });

function api(routes: Parameters<typeof fakeApi>[0] = {}) {
  return fakeApi({
    "GET /api/settings/models": json(200, loadout()),
    "GET /api/conversations/c1": json(200, stored()),
    "GET /api/thoughts/t1": json(200, thought(ORIGIN)),
    ...routes,
  });
}

function at(address: string) {
  window.history.replaceState(null, "", address);
}

function address() {
  return window.location.pathname + window.location.search;
}

const scroll = vi.fn();

/** The elements scrolled into view, with how. */
function scrolled(): { target: Element; block: string | undefined }[] {
  return scroll.mock.contexts.map((target, index) => ({
    target: target as Element,
    block: (scroll.mock.calls[index][0] as ScrollIntoViewOptions | undefined)?.block,
  }));
}

function group(id: string): HTMLElement {
  const found = screen
    .getByRole("list", { name: "Conversation", hidden: true })
    .querySelector<HTMLElement>(`[data-proposal-id="${id}"]`);
  if (!found) throw new Error(`no group ${id}`);
  return found;
}

async function originSection() {
  const dialog = await screen.findByRole("dialog");
  await within(dialog).findByText("Buy oat milk.");
  return within(dialog).queryByRole("region", { name: "Origin" });
}

beforeEach(() => {
  Element.prototype.scrollIntoView = scroll;
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  scroll.mockReset();
  at("/");
});

describe("the origin in the thought sheet", () => {
  it("shows the conversation's title, the proposal date, and a link that can be copied", async () => {
    at("/app/c1?thought=t1");
    api({ "GET /api/thoughts/t1": json(200, thought({ ...ORIGIN, conversation_id: "c2" })) });
    render(<Chat conversationId="c1" />);

    const origin = (await originSection())!;

    expect(within(origin).getByText("From")).toBeInTheDocument();
    expect(within(origin).getByRole("link", { name: "Summer trip" })).toHaveAttribute(
      "href",
      "/app/c2?proposal=p1",
    );
    expect(within(origin).getByText(/^proposed .*2026/)).toBeInTheDocument();
    expect(within(origin).queryByText("Archived")).not.toBeInTheDocument();
  });

  it("says when the conversation is archived", async () => {
    at("/app/c1?thought=t1");
    api({ "GET /api/thoughts/t1": json(200, thought({ ...ORIGIN, archived: true })) });
    render(<Chat conversationId="c1" />);

    expect(within((await originSection())!).getByText("Archived")).toBeInTheDocument();
  });

  it.each([
    ["null", null],
    ["missing", undefined],
  ])("is absent when the origin is %s", async (_case, origin) => {
    at("/app/c1?thought=t1");
    api({ "GET /api/thoughts/t1": json(200, thought(origin)) });
    render(<Chat conversationId="c1" />);

    expect(await originSection()).toBeNull();
    expect(screen.getByRole("dialog").textContent).not.toMatch(/From/);
  });

  it("opens another conversation with the router", async () => {
    at("/app/c1?thought=t1");
    api({ "GET /api/thoughts/t1": json(200, thought({ ...ORIGIN, conversation_id: "c2" })) });
    render(<Chat conversationId="c1" />);

    fireEvent.click(within((await originSection())!).getByRole("link", { name: "Summer trip" }));

    expect(push).toHaveBeenCalledWith("/app/c2?proposal=p1");
  });

  it("in the open conversation, closes the sheet, keeps the text, and scrolls to the card", async () => {
    at("/app/c1");
    const { calls } = api();
    render(<Chat conversationId="c1" />);
    await screen.findByText("Any time.");
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "half-written" } });
    act(() => openThought("t1"));
    const origin = (await originSection())!;
    scroll.mockClear();

    fireEvent.click(within(origin).getByRole("link", { name: "Summer trip" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(address()).toBe("/app/c1?proposal=p1");
    expect(push).not.toHaveBeenCalled();
    expect(screen.getByLabelText("Message")).toHaveValue("half-written");
    expect(scrolled()).toEqual([{ target: group("p1"), block: "center" }]);
    expect(calls.filter((c) => c.path === "/api/conversations/c1")).toHaveLength(1);

    window.history.back();
    await screen.findByRole("dialog");
    expect(address()).toBe("/app/c1?thought=t1");
  });

  it("works in a new conversation still on the /app route", async () => {
    at("/app");
    api({
      "POST /api/chat": () =>
        streamOf(conversationEvent("c9", "Milk"), delta("Noted."), done),
      "GET /api/thoughts/t1": json(200, thought({ ...ORIGIN, conversation_id: "c9" })),
    });
    render(<Chat />);
    await screen.findByLabelText("Message");
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "oat milk" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Noted.");
    await waitFor(() => expect(screen.getByLabelText("Message")).toBeEnabled());
    expect(address()).toBe("/app/c9");
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "half-written" } });
    act(() => openThought("t1"));

    fireEvent.click(within((await originSection())!).getByRole("link", { name: "Summer trip" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(address()).toBe("/app/c9?proposal=p1");
    expect(push).not.toHaveBeenCalled();
    expect(screen.getByText("Noted.")).toBeInTheDocument();
    expect(screen.getByLabelText("Message")).toHaveValue("half-written");
  });
});

describe("a conversation opened at a proposal card", () => {
  it("scrolls the named card into view and marks it for a moment, instead of the end", async () => {
    at("/app/c1?proposal=p1");
    api();
    render(<Chat conversationId="c1" />);
    await screen.findByText("Any time.");

    expect(scrolled()).toEqual([{ target: group("p1"), block: "center" }]);
    expect(group("p1")).toHaveAttribute("data-marked");
    expect(group("p2")).not.toHaveAttribute("data-marked");
    await waitFor(() => expect(group("p1")).not.toHaveAttribute("data-marked"), { timeout: 3000 });
  });

  it("skips the end scroll for that load only", async () => {
    at("/app/c1?proposal=p1");
    api({ "POST /api/chat": () => streamOf(delta("Sure."), done) });
    render(<Chat conversationId="c1" />);
    await screen.findByText("Any time.");
    scroll.mockClear();

    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "one more" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("Sure.");

    expect(scrolled().length).toBeGreaterThan(0);
    expect(scrolled().every((s) => s.block === "end")).toBe(true);
  });

  it("finds a card among compacted messages", async () => {
    at("/app/c1?proposal=p1");
    api({ "GET /api/conversations/c1": json(200, stored({ compacted: true })) });
    render(<Chat conversationId="c1" />);
    await screen.findByText("Any time.");

    expect(group("p1").closest("li")).toHaveTextContent("Compacted");
    expect(scrolled()).toEqual([{ target: group("p1"), block: "center" }]);
    expect(group("p1")).toHaveAttribute("data-marked");
  });

  it("opens as usual when the proposal is not in the conversation", async () => {
    at("/app/c1?proposal=nope");
    api();
    render(<Chat conversationId="c1" />);
    await screen.findByText("Any time.");

    expect(scrolled().map((s) => s.block)).toEqual(["end"]);
    expect(document.querySelector("[data-marked]")).toBeNull();
  });

  it("scrolls again on a new origin click in the same conversation, without reloading", async () => {
    at("/app/c1");
    const { calls } = api();
    render(<Chat conversationId="c1" />);
    await screen.findByText("Any time.");
    scroll.mockClear();

    act(() => openOriginHere("c1", "p2"));
    expect(scrolled()).toEqual([{ target: group("p2"), block: "center" }]);

    act(() => openOriginHere("c1", "p2"));
    act(() => openOriginHere("c1", "p1"));
    expect(scrolled().map((s) => s.target)).toEqual([group("p2"), group("p2"), group("p1")]);
    expect(calls.filter((c) => c.path === "/api/conversations/c1")).toHaveLength(1);
  });

  it("never targets the held-proposal dialog's copy of a card", async () => {
    at("/app/c1");
    api({
      "GET /api/conversations/c1": json(200, stored({ held: true })),
      "POST /api/conversations/c1/proposal": json(200, { proposal: wireProposal("p2", [EGGS], 3) }),
    });
    render(<Chat conversationId="c1" />);
    await screen.findByText("Any time.");
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "/compact" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("group", { name: "Thought to file: Eggs" })).toBeInTheDocument();
    expect(dialog.querySelector("[data-proposal-id]")).toBeNull();
    scroll.mockClear();

    act(() => openOriginHere("c1", "p2"));

    expect(scrolled()).toEqual([{ target: group("p2"), block: "center" }]);
    expect(dialog.contains(group("p2"))).toBe(false);
  });
});
