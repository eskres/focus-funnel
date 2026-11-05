// @vitest-environment jsdom
// The addition card and the "Similar" hint (thought-appending, chat-interface
// spec "An addition is reviewed in the chat").
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { THOUGHT_CHANGED_EVENT } from "@/lib/thoughts";
import {
  delta,
  detail,
  done,
  errorResponse,
  fakeApi,
  json,
  loadout,
  proposalEvent,
  storedMessage,
  streamOf,
  toolEvent,
  wireProposal,
  type WirePart,
  type WireTarget,
} from "@/test/fake-api";

import { CategoriesProvider } from "./categories-context";
import { Chat } from "./chat";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/app",
}));

const CATEGORIES = { fixed: ["task", "idea", "decision", "note", "reference", "event"], added: [] };
const CONFIRM = "POST /api/conversations/c1/proposals/p1/confirm";
// Microseconds, as the server writes them: a client that parsed and wrote the
// date again would drop them, and the server would refuse the version.
const VERSION = "2026-09-20T08:15:00.123456+00:00";

const LOCK: WireTarget = {
  title: "Buy new bike lock",
  summary: "Buy a new lock for the bike.",
  tags: ["bike", "shopping"],
  category: "task",
  created_at: "2025-09-20T08:15:00+00:00",
  updated_at: VERSION,
};

const ADDITION: WirePart = {
  // The server puts the thought's title here; the model's is dropped.
  title: "Buy new bike lock",
  summary: "Buy a new folding lock for the bike, black, under 80 euros.",
  tags: ["bike", "price"],
  category: null,
  add_to: "t1",
  based_on: VERSION,
  target: LOCK,
};

const IDEA: WirePart = {
  title: "Ride to work",
  summary: "Cycle to work twice a week.",
  tags: ["bike", "commute"],
  category: "idea",
  similar: { ...LOCK, title: "Cycle to the office", summary: "Bike to work on dry days.", category: "idea", thought_id: "t9" },
};

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

function api(routes: Parameters<typeof fakeApi>[0] = {}) {
  return fakeApi({
    "GET /api/settings/models": json(200, loadout()),
    "GET /api/settings/categories": json(200, CATEGORIES),
    "GET /api/conversations/c1": json(200, detail()),
    ...routes,
  });
}

async function openChat() {
  render(
    <CategoriesProvider>
      <Chat conversationId="c1" />
    </CategoriesProvider>,
  );
  await screen.findByLabelText("Message");
}

async function proposed() {
  send("/push the lock again");
  return screen.findByRole("group", { name: /^Addition: |^Thought to file: / });
}

const marked = (element: HTMLElement, tag: "ins" | "del") =>
  Array.from(element.querySelectorAll(tag)).map((node) => node.textContent?.trim());

const saved = (thoughtId: string, message = "Added.") => () =>
  json(200, { saved: true, thought_id: thoughtId, message });

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("an addition card", () => {
  it("says Add to with the thought's current title, and has no title field", async () => {
    api({ "POST /api/chat": proposing(ADDITION) });
    await openChat();

    const card = await proposed();

    expect(card).toHaveAccessibleName("Addition: Buy new bike lock");
    expect(within(card).getByText("Add to:")).toBeInTheDocument();
    expect(within(card).getByText("Buy new bike lock")).toBeInTheDocument();
    expect(within(card).queryByLabelText("Title")).not.toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Confirm" })).not.toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Add" })).toBeEnabled();
    expect(within(card).getByRole("button", { name: "File as new" })).toBeInTheDocument();
  });

  it("shows Now and After, with removed and added words marked as the user edits", async () => {
    api({ "POST /api/chat": proposing(ADDITION) });
    await openChat();
    const card = await proposed();

    const now = within(card).getByRole("region", { name: "Now" });
    expect(now).toHaveTextContent("Buy a new lock for the bike.");
    expect(within(card).getByLabelText("After")).toHaveValue(ADDITION.summary);
    const changes = within(card).getByLabelText("Changes");
    expect(marked(changes, "ins")).toEqual(["folding", "bike, black, under 80 euros."]);
    expect(marked(now, "del")).toEqual(["bike."]);

    fireEvent.change(within(card).getByLabelText("After"), {
      target: { value: "Buy a new red lock for the bike." },
    });

    expect(marked(within(card).getByLabelText("Changes"), "ins")).toEqual(["red"]);
    expect(marked(now, "del")).toEqual([]);
    fireEvent.change(within(card).getByLabelText("After"), { target: { value: "Buy a lock." } });
    expect(marked(now, "del")).toEqual(["new lock for the bike."]);
    expect(marked(within(card).getByLabelText("Changes"), "ins")).toEqual(["lock."]);
  });

  it("pre-fills the current tags then the new ones, and the model's category, else the current one", async () => {
    api({
      "POST /api/chat": proposing(ADDITION, {
        ...ADDITION,
        add_to: "t2",
        category: "note",
        tags: ["shopping", "lock"],
        target: { ...LOCK, title: "Lock colours", category: "idea" },
      }),
    });
    await openChat();
    send("/push the lock again");

    const first = await screen.findByRole("group", { name: "Addition: Buy new bike lock" });
    expect(within(first).getByLabelText(/Tags/)).toHaveValue("bike, shopping, price");
    expect(within(first).getByLabelText("Category")).toHaveValue("task");
    const second = screen.getByRole("group", { name: "Addition: Lock colours" });
    expect(within(second).getByLabelText(/Tags/)).toHaveValue("bike, shopping, lock");
    expect(within(second).getByLabelText("Category")).toHaveValue("note");
    // Each card adds to its own thought, so the proposal is not merged.
    expect(screen.queryByRole("button", { name: "Merge into one" })).not.toBeInTheDocument();
  });

  it("adds with mode add, the thought, and its version as the server sent it, then says Added to", async () => {
    const { calls } = api({ "POST /api/chat": proposing(ADDITION), [CONFIRM]: saved("t1") });
    await openChat();
    const card = await proposed();
    fireEvent.change(within(card).getByLabelText(/Tags/), { target: { value: "bike, price" } });

    fireEvent.click(within(card).getByRole("button", { name: "Add" }));

    const added = await screen.findByRole("group", { name: "Added to: Buy new bike lock" });
    expect(within(added).getByRole("link", { name: "Open" })).toHaveAttribute(
      "href",
      expect.stringContaining("thought=t1"),
    );
    expect(calls.find((call) => call.path.endsWith("/confirm"))?.body).toEqual({
      parts: [0],
      title: "Buy new bike lock",
      summary: ADDITION.summary,
      tags: ["bike", "price"],
      category: "task",
      mode: "add",
      add_to: "t1",
      based_on: VERSION,
    });
  });

  it("turns into a normal card with File as new, and files a new thought", async () => {
    const { calls } = api({ "POST /api/chat": proposing(ADDITION), [CONFIRM]: saved("t5", "Saved.") });
    await openChat();
    const card = await proposed();

    fireEvent.click(within(card).getByRole("button", { name: "File as new" }));

    const normal = screen.getByRole("group", { name: "Thought to file: Buy new bike lock" });
    expect(within(normal).getByLabelText("Title")).toHaveValue("Buy new bike lock");
    expect(within(normal).getByLabelText("Summary")).toHaveValue(ADDITION.summary);
    expect(within(normal).getByLabelText(/Tags/)).toHaveValue("bike, shopping, price");
    fireEvent.change(within(normal).getByLabelText("Title"), { target: { value: "Bike lock prices" } });
    fireEvent.click(within(normal).getByRole("button", { name: "Confirm" }));

    expect(await screen.findByRole("group", { name: "Saved: Bike lock prices" })).toBeInTheDocument();
    const body = calls.find((call) => call.path.endsWith("/confirm"))?.body as Record<string, unknown>;
    expect(body).toMatchObject({ parts: [0], title: "Bike lock prices" });
    expect(body).not.toHaveProperty("mode");
    expect(body).not.toHaveProperty("add_to");
  });

  it("offers File as new when the thought is gone (404)", async () => {
    api({
      "POST /api/chat": proposing(ADDITION),
      [CONFIRM]: errorResponse(
        404,
        "not_found",
        "The thought this adds to no longer exists. File it as a new thought instead.",
      ),
    });
    await openChat();
    const card = await proposed();

    fireEvent.click(within(card).getByRole("button", { name: "Add" }));

    expect(
      await within(card).findByText(
        "The thought this adds to no longer exists. File it as a new thought instead.",
      ),
    ).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Add" })).not.toBeInTheDocument();
    fireEvent.click(within(card).getByRole("button", { name: "File as new" }));
    expect(screen.getByRole("group", { name: "Thought to file: Buy new bike lock" })).toBeInTheDocument();
  });

  it("shows a deleted target from the server as gone, with File as new", async () => {
    api({ "POST /api/chat": proposing({ ...ADDITION, target: { deleted: true } }) });
    await openChat();
    const card = await proposed();

    expect(within(card).getByText(/no longer exists/)).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Add" })).not.toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "File as new" })).toBeInTheDocument();
  });

  it("updates the Now column on a 409, keeps the user's text, and adds against the new version", async () => {
    const changed = {
      id: "t1",
      title: "Buy a bike lock",
      summary: "Buy a new lock for the bike. Ask at the shop.",
      tags: ["bike"],
      category: "task",
      updated_at: "2026-09-21T09:00:00.654321+00:00",
    };
    const { calls } = api({
      "POST /api/chat": proposing(ADDITION),
      [CONFIRM]: [
        json(409, {
          error: {
            code: "thought_changed",
            message: "The thought changed after this addition was proposed. Review its current version and add again.",
            thought: changed,
          },
        }),
        saved("t1"),
      ],
    });
    await openChat();
    const card = await proposed();
    fireEvent.change(within(card).getByLabelText("After"), { target: { value: "My own words." } });

    fireEvent.click(within(card).getByRole("button", { name: "Add" }));

    expect(await within(card).findByRole("alert")).toHaveTextContent(/changed after this addition was proposed/);
    expect(within(card).getByRole("region", { name: "Now" })).toHaveTextContent(changed.summary);
    expect(within(card).getByText("Buy a bike lock")).toBeInTheDocument();
    expect(within(card).getByLabelText("After")).toHaveValue("My own words.");

    fireEvent.click(within(card).getByRole("button", { name: "Add" }));

    expect(await screen.findByRole("group", { name: "Added to: Buy a bike lock" })).toBeInTheDocument();
    const confirms = calls.filter((call) => call.path.endsWith("/confirm"));
    expect(confirms.map((call) => (call.body as { based_on: string }).based_on)).toEqual([
      VERSION,
      changed.updated_at,
    ]);
  });

  it("says Added to, or Addition undone, when the conversation is reopened", async () => {
    api({
      "GET /api/conversations/c1": json(200, {
        ...detail(),
        messages: [
          storedMessage(0, "user", "/push the lock again"),
          storedMessage(1, "assistant", null, {
            tool_calls: [{ id: "c", type: "function", function: { name: "propose_thought", arguments: "{}" } }],
          }),
          storedMessage(2, "tool", "shown", { tool_call_id: "c", details: { proposal_id: "p1" } }),
          storedMessage(3, "assistant", "Added."),
        ],
        proposals: [
          wireProposal("p1", [
            { ...ADDITION, thought_id: "t1", saved_title: "Buy new bike lock", added: true },
            { ...ADDITION, add_to: "t2", thought_id: "t2", saved_title: "Lock colours", added: true, undone: true },
          ]),
        ],
      }),
    });
    await openChat();

    const added = await screen.findByRole("group", { name: "Added to: Buy new bike lock" });
    expect(within(added).getByRole("link", { name: "Open" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Addition undone: Lock colours" })).toBeInTheDocument();
  });

  it("says Addition undone once the sheet undoes it", async () => {
    api({ "POST /api/chat": proposing(ADDITION), [CONFIRM]: saved("t1") });
    await openChat();
    const card = await proposed();
    fireEvent.click(within(card).getByRole("button", { name: "Add" }));
    await screen.findByRole("group", { name: "Added to: Buy new bike lock" });

    act(() => {
      window.dispatchEvent(
        new CustomEvent(THOUGHT_CHANGED_EVENT, { detail: { id: "t1", title: "Buy new bike lock", undone: "p9" } }),
      );
    });
    expect(screen.getByRole("group", { name: "Added to: Buy new bike lock" })).toBeInTheDocument();

    act(() => {
      window.dispatchEvent(
        new CustomEvent(THOUGHT_CHANGED_EVENT, { detail: { id: "t1", title: "Buy new bike lock", undone: "p1" } }),
      );
    });
    expect(screen.getByRole("group", { name: "Addition undone: Buy new bike lock" })).toBeInTheDocument();
  });
});

describe("the Similar hint", () => {
  const filed = new Date(LOCK.created_at).toLocaleDateString(undefined, { dateStyle: "medium" });

  it("names the match and its filing date, and turns the card into an addition card", async () => {
    const { calls } = api({ "POST /api/chat": proposing(IDEA), [CONFIRM]: saved("t9") });
    await openChat();
    const card = await proposed();

    const hint = within(card).getByRole("note", { name: "Similar thought" });
    expect(hint).toHaveTextContent(`Similar: Cycle to the office, filed ${filed}`);

    fireEvent.click(within(hint).getByRole("button", { name: "Add to it instead" }));

    const addition = screen.getByRole("group", { name: "Addition: Cycle to the office" });
    expect(within(addition).getByText("Add to:")).toBeInTheDocument();
    expect(within(addition).queryByLabelText("Title")).not.toBeInTheDocument();
    expect(within(addition).getByRole("region", { name: "Now" })).toHaveTextContent("Bike to work on dry days.");
    expect(within(addition).getByLabelText("After")).toHaveValue(
      "Bike to work on dry days.\n\nCycle to work twice a week.",
    );
    expect(marked(within(addition).getByLabelText("Changes"), "ins")).toEqual(["Cycle to work twice a week."]);
    expect(within(addition).getByLabelText(/Tags/)).toHaveValue("bike, shopping, commute");

    fireEvent.click(within(addition).getByRole("button", { name: "Add" }));

    expect(await screen.findByRole("group", { name: "Added to: Cycle to the office" })).toBeInTheDocument();
    expect(calls.find((call) => call.path.endsWith("/confirm"))?.body).toMatchObject({
      mode: "add",
      add_to: "t9",
      based_on: VERSION,
    });
  });

  it("adds a card with date choices without a pick, and sends no date (thought-dates)", async () => {
    const choices = [
      { start: "2026-10-09", end: null, time_zone: "UTC" },
      { start: "2026-10-16", end: null, time_zone: "UTC" },
    ];
    const { calls } = api({
      "POST /api/chat": proposing({ ...IDEA, when: null, when_choices: choices }),
      [CONFIRM]: saved("t9"),
    });
    await openChat();
    const card = await proposed();
    expect(within(card).getByRole("group", { name: "Which date?" })).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Confirm" })).toBeDisabled();

    fireEvent.click(within(card).getByRole("button", { name: "Add to it instead" }));

    // An addition keeps its thought's date: no choices, and Add needs no pick.
    const addition = screen.getByRole("group", { name: "Addition: Cycle to the office" });
    expect(within(addition).queryByRole("group", { name: "Which date?" })).not.toBeInTheDocument();
    fireEvent.click(within(addition).getByRole("button", { name: "Add" }));

    expect(await screen.findByRole("group", { name: "Added to: Cycle to the office" })).toBeInTheDocument();
    const body = calls.find((call) => call.path.endsWith("/confirm"))?.body as Record<string, unknown>;
    expect(body).toMatchObject({ mode: "add", add_to: "t9" });
    expect(body).not.toHaveProperty("when");
  });

  it("goes back to the card as proposed with File as new", async () => {
    api({ "POST /api/chat": proposing(IDEA) });
    await openChat();
    const card = await proposed();
    fireEvent.click(within(card).getByRole("button", { name: "Add to it instead" }));

    fireEvent.click(screen.getByRole("button", { name: "File as new" }));

    const back = screen.getByRole("group", { name: "Thought to file: Ride to work" });
    expect(within(back).getByLabelText("Title")).toHaveValue("Ride to work");
    expect(within(back).getByLabelText("Summary")).toHaveValue("Cycle to work twice a week.");
  });

  it("hides Merge while a card is an addition", async () => {
    api({ "POST /api/chat": proposing(IDEA, { ...IDEA, title: "Helmet", similar: null }) });
    await openChat();
    send("/push bike things");
    await screen.findByRole("group", { name: "Thought to file: Ride to work" });
    expect(screen.getByRole("button", { name: "Merge into one" })).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Add to it instead" }));

    await waitFor(() => expect(screen.queryByRole("button", { name: "Merge into one" })).not.toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "File as new" }));
    expect(screen.getByRole("button", { name: "Merge into one" })).toBeInTheDocument();
  });
});
