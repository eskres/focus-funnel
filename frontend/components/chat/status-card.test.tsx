// @vitest-environment jsdom
// A proposal part with `mark`: the status card (thought-status design
// decisions 9 and 10).
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { toProposal } from "@/lib/sse";
import { THOUGHT_CHANGED_EVENT, type ThoughtChanged } from "@/lib/thoughts";
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
import { heldProposalFor, ProposalDialog } from "./proposal-dialog";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/app",
}));

const PLUMBER_NOW: WireTarget = {
  title: "Call the plumber",
  summary: "Ask about the leak under the sink.",
  tags: ["home"],
  category: "task",
  created_at: "2026-09-20T08:00:00Z",
  updated_at: "2026-09-20T08:00:00Z",
};

/** A status part as the server stores it: the thought's title and category, no summary or tags. */
const MARK: WirePart = {
  title: "Call the plumber",
  summary: "",
  tags: [],
  category: "task",
  mark: "t9",
  target: PLUMBER_NOW,
};
const OAT: WirePart = { title: "Oat milk", summary: "Buy oat milk.", tags: ["groceries"], category: "task" };
const CONFIRM = "POST /api/conversations/c1/proposals/p1/confirm";
const marked = () => json(200, { saved: true, thought_id: "t9", message: "Marked done." });

const proposing = (...parts: WirePart[]) => () =>
  streamOf(
    toolEvent("propose_thought", "start"),
    proposalEvent("p1", parts),
    toolEvent("propose_thought", "end", "Proposed marking a thought done"),
    delta("Ready for you to confirm."),
    done,
  );

/** A reopened conversation whose one answer showed the proposal `p1`. */
const reopened = (parts: WirePart[], replacedBy: string | null = null) =>
  detail({
    messages: [
      storedMessage(0, "user", "I called the plumber"),
      storedMessage(1, "assistant", null, {
        tool_calls: [{ id: "a", type: "function", function: { name: "propose_thought", arguments: "{}" } }],
      }),
      storedMessage(2, "tool", "shown", { tool_call_id: "a", details: { proposal_id: "p1" } }),
      storedMessage(3, "assistant", "Ready for you to confirm."),
    ],
    proposals: [wireProposal("p1", parts, 2, replacedBy)],
  });

function api(routes: Parameters<typeof fakeApi>[0] = {}) {
  return fakeApi({
    "GET /api/settings/models": json(200, loadout()),
    "GET /api/settings/categories": json(200, { fixed: ["task", "idea", "note"], added: [] }),
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
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: "I called the plumber" } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
  await screen.findByText("Ready for you to confirm.");
}

function groupNames(): string[] {
  return screen.getAllByRole("group").map((group) => group.getAttribute("aria-label") ?? "");
}

function announce(detail: ThoughtChanged) {
  act(() => {
    window.dispatchEvent(new CustomEvent<ThoughtChanged>(THOUGHT_CHANGED_EVENT, { detail }));
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("a status card", () => {
  it("says Mark done: with the title and category badge, one button, and no fields", async () => {
    api({ "POST /api/chat": proposing(MARK) });
    await openChat();
    await proposed();

    const card = screen.getByRole("group", { name: "Mark done: Call the plumber" });
    expect(card).toHaveTextContent("Mark done:");
    expect(card).toHaveTextContent("Call the plumber");
    expect(within(card).getByText("task")).toBeInTheDocument();
    expect(within(card).getAllByRole("button").map((button) => button.textContent)).toEqual(["Mark done"]);
    expect(within(card).queryByRole("textbox")).not.toBeInTheDocument();
    expect(within(card).queryByRole("combobox")).not.toBeInTheDocument();
    expect(within(card).queryByLabelText("Title")).not.toBeInTheDocument();
    expect(within(card).queryByLabelText("Summary")).not.toBeInTheDocument();
    expect(within(card).queryByLabelText(/Tags/)).not.toBeInTheDocument();
    expect(within(card).queryByLabelText("Category")).not.toBeInTheDocument();
  });

  it("confirms with only its part's index, then says Marked done: with an Open link", async () => {
    const { calls } = api({ "POST /api/chat": proposing(OAT, MARK), [CONFIRM]: marked() });
    await openChat();
    await proposed();
    expect(groupNames().filter((name) => name.startsWith("Thought to file:"))).toEqual([
      "Thought to file: Oat milk",
    ]);

    const card = screen.getByRole("group", { name: "Mark done: Call the plumber" });
    fireEvent.click(within(card).getByRole("button", { name: "Mark done" }));

    const done = await screen.findByRole("group", { name: "Marked done: Call the plumber" });
    expect(calls.filter((call) => call.method === "POST" && call.path.endsWith("/confirm"))).toEqual([
      { method: "POST", path: "/api/conversations/c1/proposals/p1/confirm", body: { parts: [1] } },
    ]);
    expect(within(done).getByRole("status")).toHaveTextContent("Marked done:");
    expect(within(done).getByRole("link", { name: "Open" })).toHaveAttribute("href", "?thought=t9");
    expect(done).not.toHaveTextContent("Saved:");
    expect(within(done).queryByRole("button")).not.toBeInTheDocument();
    expect(groupNames().filter((name) => name.startsWith("Saved:"))).toEqual([]);
    expect(groupNames().filter((name) => name.includes("Call the plumber"))).toEqual([
      "Marked done: Call the plumber",
    ]);
    // The new thought's card still waits.
    expect(screen.getByRole("group", { name: "Thought to file: Oat milk" })).toBeInTheDocument();
  });

  it("says the thought no longer exists on a 404, with no button and no link", async () => {
    api({
      "POST /api/chat": proposing(MARK),
      [CONFIRM]: errorResponse(404, "not_found", "This thought no longer exists."),
    });
    await openChat();
    await proposed();

    const card = screen.getByRole("group", { name: "Mark done: Call the plumber" });
    fireEvent.click(within(card).getByRole("button", { name: "Mark done" }));

    expect(await within(card).findByText("This thought no longer exists.")).toBeInTheDocument();
    expect(within(card).queryByRole("button")).not.toBeInTheDocument();
    expect(within(card).queryByRole("link")).not.toBeInTheDocument();
    expect(card).not.toHaveTextContent("Marked done:");
  });

  it("says the thought no longer exists when its target says deleted", async () => {
    api({ "POST /api/chat": proposing({ ...MARK, target: { deleted: true } }) });
    await openChat();
    await proposed();

    const card = screen.getByRole("group", { name: "Mark done: Call the plumber" });
    expect(within(card).getByText("This thought no longer exists.")).toBeInTheDocument();
    expect(within(card).queryByRole("button")).not.toBeInTheDocument();
    expect(within(card).queryByRole("link")).not.toBeInTheDocument();
  });

  it("shows the server's message on a 500 and keeps the Mark done button", async () => {
    api({
      "POST /api/chat": proposing(MARK),
      [CONFIRM]: errorResponse(500, "internal_error", "Something went wrong."),
    });
    await openChat();
    await proposed();

    const card = screen.getByRole("group", { name: "Mark done: Call the plumber" });
    fireEvent.click(within(card).getByRole("button", { name: "Mark done" }));

    expect(await within(card).findByRole("alert")).toHaveTextContent("Something went wrong.");
    await waitFor(() => expect(within(card).getByRole("button", { name: "Mark done" })).toBeEnabled());
    expect(screen.queryByText("Marked done:")).not.toBeInTheDocument();
    expect(screen.queryByText("This thought no longer exists.")).not.toBeInTheDocument();
  });

  it("shows the client's message when the fetch is rejected, and keeps the button", async () => {
    api({
      "POST /api/chat": proposing(MARK),
      [CONFIRM]: () => Promise.reject(new TypeError("Failed to fetch")),
    });
    await openChat();
    await proposed();

    const card = screen.getByRole("group", { name: "Mark done: Call the plumber" });
    fireEvent.click(within(card).getByRole("button", { name: "Mark done" }));

    expect(await within(card).findByRole("alert")).toHaveTextContent("Failed to fetch");
    await waitFor(() => expect(within(card).getByRole("button", { name: "Mark done" })).toBeEnabled());
    expect(screen.queryByText("Marked done:")).not.toBeInTheDocument();
    expect(screen.queryByText("This thought no longer exists.")).not.toBeInTheDocument();
  });

  it("is named Deleted: once its thought is deleted, before and after a reload", async () => {
    api({ "POST /api/chat": proposing(MARK), [CONFIRM]: marked() });
    await openChat();
    await proposed();
    fireEvent.click(screen.getByRole("button", { name: "Mark done" }));
    await screen.findByRole("group", { name: "Marked done: Call the plumber" });

    announce({ id: "t9", deleted: true });

    const card = await screen.findByRole("group", { name: "Deleted: Call the plumber" });
    expect(card).toHaveTextContent("Deleted:");
    expect(within(card).queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByText("Marked done:")).not.toBeInTheDocument();
    expect(card).not.toHaveTextContent("null");
  });

  it("comes back as Deleted: with no link when its thought was deleted after the mark", async () => {
    api({
      "GET /api/conversations/c1": json(
        200,
        reopened([{ ...MARK, thought_id: "t9", saved_title: null, deleted: true, target: { deleted: true } }]),
      ),
    });
    await openChat();

    const card = await screen.findByRole("group", { name: "Deleted: Call the plumber" });
    expect(within(card).queryByRole("link")).not.toBeInTheDocument();
    expect(screen.queryByText("Marked done:")).not.toBeInTheDocument();
    expect(card).not.toHaveTextContent("null");
    expect(card.textContent?.replace("Deleted:", "").trim()).toBe("Call the plumber");
  });

  it("comes back confirmed with its link, and an unconfirmed one can still be confirmed", async () => {
    const { calls } = api({
      "GET /api/conversations/c1": json(
        200,
        reopened([
          { ...MARK, thought_id: "t9", saved_title: "Call the plumber" },
          {
            ...MARK,
            title: "Renew the passport",
            mark: "t8",
            target: { ...PLUMBER_NOW, title: "Renew the passport" },
          },
        ]),
      ),
      [CONFIRM]: json(200, { saved: true, thought_id: "t8", message: "Marked done." }),
    });
    await openChat();

    const confirmed = await screen.findByRole("group", { name: "Marked done: Call the plumber" });
    expect(within(confirmed).getByRole("link", { name: "Open" })).toHaveAttribute("href", "?thought=t9");
    const waiting = screen.getByRole("group", { name: "Mark done: Renew the passport" });
    fireEvent.click(within(waiting).getByRole("button", { name: "Mark done" }));

    await screen.findByRole("group", { name: "Marked done: Renew the passport" });
    expect(calls.filter((call) => call.path.endsWith("/confirm")).map((call) => call.body)).toEqual([
      { parts: [1] },
    ]);
  });
});

describe("a proposal with a status part", () => {
  it("has no merge button beside a new part", async () => {
    api({ "POST /api/chat": proposing(OAT, MARK) });
    await openChat();
    await proposed();

    expect(screen.getByRole("group", { name: "Thought to file: Oat milk" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Mark done: Call the plumber" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Merge into one" })).not.toBeInTheDocument();
  });

  it("names a group of only marks Proposed status change", async () => {
    api({ "POST /api/chat": proposing(MARK) });
    await openChat();
    await proposed();

    expect(screen.getByRole("region", { name: "Proposed status change" })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /to file/ })).not.toBeInTheDocument();
  });

  it.each([
    ["one new part", [OAT, MARK], "Proposals to file"],
    ["only a new part", [OAT], "Proposal to file"],
  ])("keeps the filing name for a group with %s", async (_case, parts, name) => {
    api({ "POST /api/chat": proposing(...(parts as WirePart[])) });
    await openChat();
    await proposed();

    expect(screen.getByRole("region", { name })).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Proposed status change" })).not.toBeInTheDocument();
  });

  it("comes back as two cards when an addition and a mark on the same thought were both confirmed", async () => {
    api({
      "GET /api/conversations/c1": json(
        200,
        reopened([
          {
            title: "Call the plumber",
            summary: "He comes Tuesday.",
            tags: ["home"],
            category: "task",
            add_to: "t9",
            based_on: PLUMBER_NOW.updated_at,
            target: PLUMBER_NOW,
            thought_id: "t9",
            saved_title: "Call the plumber",
            added: true,
          },
          { ...MARK, thought_id: "t9", saved_title: "Call the plumber" },
        ]),
      ),
    });
    await openChat();

    expect(await screen.findByRole("group", { name: "Added to: Call the plumber" })).toBeInTheDocument();
    expect(screen.getByRole("group", { name: "Marked done: Call the plumber" })).toBeInTheDocument();
    expect(groupNames().filter((name) => name.includes("Call the plumber"))).toHaveLength(2);
    expect(screen.queryByRole("group", { name: "Saved: Call the plumber" })).not.toBeInTheDocument();
  });

  it("still reads new parts saved as one thought as one merged card", async () => {
    api({
      "GET /api/conversations/c1": json(
        200,
        reopened([
          { ...OAT, thought_id: "t1", saved_title: "Oat milk" },
          { ...OAT, title: "Eggs", summary: "Buy eggs.", thought_id: "t1", saved_title: "Oat milk" },
        ]),
      ),
    });
    await openChat();

    expect(await screen.findByRole("group", { name: "Saved: Oat milk" })).toBeInTheDocument();
    expect(screen.getAllByRole("group", { name: /^Saved:/ })).toHaveLength(1);
  });

  it("keeps a replaced proposal's status card shown and folds only the new part, counting one thought", async () => {
    const { calls } = api({
      "GET /api/conversations/c1": json(200, reopened([OAT, MARK], "p2")),
      [CONFIRM]: marked(),
    });
    await openChat();

    const card = await screen.findByRole("group", { name: "Mark done: Call the plumber" });
    expect(screen.queryByRole("group", { name: "Thought to file: Oat milk" })).not.toBeInTheDocument();
    expect(screen.getByText(/A thought to file was replaced by a\s+newer proposal/)).toBeInTheDocument();

    fireEvent.click(within(card).getByRole("button", { name: "Mark done" }));

    await screen.findByRole("group", { name: "Marked done: Call the plumber" });
    expect(calls.filter((call) => call.path.endsWith("/confirm")).map((call) => call.body)).toEqual([
      { parts: [1] },
    ]);
  });
});

describe("the held proposal and status parts", () => {
  const OFFER = "POST /api/conversations/c1/proposal";

  it("heldProposalFor() gives null when the only unsaved part is a status part", async () => {
    fakeApi({
      [OFFER]: json(200, { proposal: wireProposal("p1", [{ ...OAT, thought_id: "t1" }, MARK], 1) }),
    });

    expect(await heldProposalFor("c1")).toBeNull();
  });

  it("heldProposalFor() gives the proposal when a new part is unsaved beside a status part", async () => {
    fakeApi({ [OFFER]: json(200, { proposal: wireProposal("p1", [MARK, OAT], 1) }) });

    expect((await heldProposalFor("c1"))?.id).toBe("p1");
  });

  it("ProposalDialog shows only the new part's card and no Mark done button", async () => {
    const proposal = toProposal(wireProposal("p1", [MARK, OAT], 1))!;
    render(
      <CategoriesProvider>
        <ProposalDialog
          offer={{ conversationId: "c1", proposal, continueLabel: "Archive now", onContinue: () => undefined }}
          onClose={() => undefined}
        />
      </CategoriesProvider>,
    );

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("group", { name: "Thought to file: Oat milk" })).toBeInTheDocument();
    expect(within(dialog).queryByRole("group", { name: /Call the plumber/ })).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Mark done" })).not.toBeInTheDocument();
  });
});
