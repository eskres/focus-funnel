// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

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
} from "@/test/fake-api";

import { CategoriesProvider } from "./categories-context";
import { Chat } from "./chat";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/app",
}));

const OAT: WirePart = { title: "Oat milk", summary: "Buy oat milk.", tags: ["groceries"], category: "task" };
const EGGS: WirePart = {
  title: "Eggs",
  summary: "Buy eggs.",
  tags: ["groceries", "breakfast"],
  category: "note",
};
const DENTIST: WirePart = { title: "Dentist", summary: "Book the dentist.", tags: ["health"], category: "task" };
const CATEGORIES = { fixed: ["task", "idea", "decision", "note", "reference"], added: ["recipe"] };
const CONFIRM = "POST /api/conversations/c1/proposals/p1/confirm";

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

function card(title: string) {
  return screen.getByRole("group", { name: `Thought to file: ${title}` });
}

const saved = (thoughtId: string) => () => json(200, { saved: true, thought_id: thoughtId, message: "Saved." });

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/");
});

describe("a proposal card", () => {
  it("shows the fields and a category choice with None and the user's categories", async () => {
    api({ "POST /api/chat": proposing(OAT) });
    await openChat();

    send("/push buy oat milk");

    const group = await screen.findByRole("region", { name: "Proposal to file" });
    const oat = within(group).getByRole("group", { name: "Thought to file: Oat milk" });
    expect(within(oat).getByLabelText("Title")).toHaveValue("Oat milk");
    expect(within(oat).getByLabelText("Summary")).toHaveValue("Buy oat milk.");
    expect(within(oat).getByLabelText(/Tags/)).toHaveValue("groceries");
    const category = within(oat).getByLabelText("Category");
    expect(category).toHaveValue("task");
    await waitFor(() =>
      expect(within(category).getAllByRole("option").map((o) => o.textContent)).toEqual([
        "None",
        "task",
        "idea",
        "decision",
        "note",
        "reference",
        "recipe",
      ]),
    );
    // One thing: one card, and nothing to merge.
    expect(screen.queryByRole("button", { name: "Merge into one" })).not.toBeInTheDocument();
  });

  it("confirms the edited card and shows it as saved, with a link to the thought", async () => {
    const { calls } = api({ "POST /api/chat": proposing(OAT), [CONFIRM]: saved("t1") });
    await openChat();
    send("/push buy oat milk");
    await screen.findByRole("region", { name: "Proposal to file" });
    const oat = card("Oat milk");

    fireEvent.change(within(oat).getByLabelText("Title"), { target: { value: "Oat and soy milk" } });
    fireEvent.change(within(oat).getByLabelText("Summary"), { target: { value: "Buy both." } });
    fireEvent.change(within(oat).getByLabelText(/Tags/), { target: { value: "groceries, milk" } });
    fireEvent.change(within(oat).getByLabelText("Category"), { target: { value: "decision" } });
    fireEvent.click(within(oat).getByRole("button", { name: "Confirm" }));

    const done = await screen.findByRole("group", { name: "Saved: Oat and soy milk" });
    expect(within(done).getByRole("link", { name: "Open" })).toHaveAttribute("href", "?thought=t1");
    expect(calls.find((c) => c.path.endsWith("/confirm"))?.body).toEqual({
      parts: [0],
      title: "Oat and soy milk",
      summary: "Buy both.",
      tags: ["groceries", "milk"],
      category: "decision",
    });
  });

  it("sends no category when None is picked", async () => {
    const { calls } = api({ "POST /api/chat": proposing(OAT), [CONFIRM]: saved("t1") });
    await openChat();
    send("/push buy oat milk");
    await screen.findByRole("region", { name: "Proposal to file" });

    fireEvent.change(within(card("Oat milk")).getByLabelText("Category"), { target: { value: "" } });
    fireEvent.click(within(card("Oat milk")).getByRole("button", { name: "Confirm" }));

    await screen.findByRole("group", { name: "Saved: Oat milk" });
    expect((calls.find((c) => c.path.endsWith("/confirm"))?.body as { category: unknown }).category).toBeNull();
  });

  it("keeps the text and shows the server's message when a field is refused", async () => {
    api({
      "POST /api/chat": proposing(OAT),
      [CONFIRM]: errorResponse(422, "validation_error", "title: must be at most 200 characters"),
    });
    await openChat();
    send("/push buy oat milk");
    await screen.findByRole("region", { name: "Proposal to file" });
    const long = "x".repeat(201);

    fireEvent.change(within(card("Oat milk")).getByLabelText("Title"), { target: { value: long } });
    fireEvent.click(within(card("Oat milk")).getByRole("button", { name: "Confirm" }));

    expect(await within(card("Oat milk")).findByRole("alert")).toHaveTextContent(
      "title: must be at most 200 characters",
    );
    expect(within(card("Oat milk")).getByLabelText("Title")).toHaveValue(long);
  });

  it("keeps the conversation going and holds the proposal when the user sends another message", async () => {
    const { calls } = api({
      "POST /api/chat": [proposing(OAT), () => streamOf(delta("Soy too, then."), done)],
    });
    await openChat();

    send("I need to buy oat milk tomorrow");
    await screen.findByRole("region", { name: "Proposal to file" });
    send("and soy milk?");

    expect(await screen.findByText("Soy too, then.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Message")).toBeEnabled());
    expect(screen.getAllByRole("region", { name: "Proposal to file" })).toHaveLength(1);
    expect(calls.filter((c) => c.path.includes("/proposal"))).toEqual([]);
  });
});

describe("a split proposal", () => {
  it("shows one card per part, with a merge button, and stores nothing", async () => {
    const { calls } = api({ "POST /api/chat": proposing(OAT, DENTIST, EGGS) });
    await openChat();

    send("/push buy oat milk, book the dentist, and buy eggs");

    const group = await screen.findByRole("region", { name: "Proposals to file" });
    expect(
      within(group).getAllByRole("group").map((g) => g.getAttribute("aria-label")),
    ).toEqual(["Thought to file: Oat milk", "Thought to file: Dentist", "Thought to file: Eggs"]);
    expect(within(group).getByRole("button", { name: "Merge into one" })).toBeInTheDocument();
    expect(calls.filter((c) => c.path.includes("/proposals/"))).toEqual([]);
  });

  it("confirms one part, and the other cards still wait", async () => {
    const { calls } = api({ "POST /api/chat": proposing(OAT, DENTIST, EGGS), [CONFIRM]: saved("t2") });
    await openChat();
    send("/push three things");
    await screen.findByRole("region", { name: "Proposals to file" });

    fireEvent.click(within(card("Dentist")).getByRole("button", { name: "Confirm" }));

    await screen.findByRole("group", { name: "Saved: Dentist" });
    expect((calls.find((c) => c.path.endsWith("/confirm"))?.body as { parts: number[] }).parts).toEqual([1]);
    expect(card("Oat milk")).toBeInTheDocument();
    expect(card("Eggs")).toBeInTheDocument();
    // A part is saved, so merging is no longer offered.
    expect(screen.queryByRole("button", { name: "Merge into one" })).not.toBeInTheDocument();
  });

  it("merges into one card with no request: first title and category, both summaries, tags once", async () => {
    const { calls } = api({ "POST /api/chat": proposing(OAT, EGGS), [CONFIRM]: saved("t1") });
    await openChat();
    send("/push oat milk and eggs");
    await screen.findByRole("region", { name: "Proposals to file" });
    const before = calls.length;

    fireEvent.click(screen.getByRole("button", { name: "Merge into one" }));

    expect(calls).toHaveLength(before);
    const merged = await screen.findByRole("group", { name: "Thought to file: Oat milk" });
    expect(screen.queryByRole("group", { name: "Thought to file: Eggs" })).not.toBeInTheDocument();
    expect(within(merged).getByLabelText("Title")).toHaveValue("Oat milk");
    expect(within(merged).getByLabelText("Summary")).toHaveValue("Buy oat milk.\n\nBuy eggs.");
    expect(within(merged).getByLabelText(/Tags/)).toHaveValue("groceries, breakfast");
    expect(within(merged).getByLabelText("Category")).toHaveValue("task");
    expect(screen.queryByRole("button", { name: "Merge into one" })).not.toBeInTheDocument();

    fireEvent.click(within(merged).getByRole("button", { name: "Confirm" }));

    await screen.findByRole("group", { name: "Saved: Oat milk" });
    const confirms = calls.filter((c) => c.path.endsWith("/confirm"));
    expect(confirms).toHaveLength(1);
    expect((confirms[0].body as { parts: number[] }).parts).toEqual([0, 1]);
  });
});

describe("a reopened conversation", () => {
  const stored = () =>
    detail({
      messages: [
        storedMessage(0, "user", "/push oat milk and eggs"),
        storedMessage(1, "assistant", null, {
          tool_calls: [{ id: "c", type: "function", function: { name: "propose_thought", arguments: "{}" } }],
        }),
        storedMessage(2, "tool", "shown", { tool_call_id: "c", details: { proposal_id: "p1" } }),
        storedMessage(3, "assistant", "Want to keep them?"),
      ],
      proposals: [wireProposal("p1", [{ ...OAT, thought_id: "t1" }, EGGS])],
    });

  it("shows a saved card as saved with its link, and an unsaved card as editable", async () => {
    const { calls } = api({
      "GET /api/conversations/c1": json(200, stored()),
      [CONFIRM]: saved("t2"),
    });
    await openChat();

    const done = await screen.findByRole("group", { name: "Saved: Oat milk" });
    expect(within(done).getByRole("link", { name: "Open" })).toHaveAttribute("href", "?thought=t1");
    expect(screen.queryByRole("button", { name: "Merge into one" })).not.toBeInTheDocument();

    fireEvent.click(within(card("Eggs")).getByRole("button", { name: "Confirm" }));

    await screen.findByRole("group", { name: "Saved: Eggs" });
    expect((calls.find((c) => c.path.endsWith("/confirm"))?.body as { parts: number[] }).parts).toEqual([1]);
  });

  it("shows merged parts as one saved card", async () => {
    api({
      "GET /api/conversations/c1": json(200, {
        ...stored(),
        proposals: [wireProposal("p1", [{ ...OAT, thought_id: "t1" }, { ...EGGS, thought_id: "t1" }])],
      }),
    });
    await openChat();

    expect(await screen.findByRole("group", { name: "Saved: Oat milk" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: /Eggs/ })).not.toBeInTheDocument();
  });

  it("shows a proposal offered before an action with the answer it followed", async () => {
    api({
      "GET /api/conversations/c1": json(200, {
        ...stored(),
        messages: [storedMessage(0, "user", "I must buy eggs"), storedMessage(1, "assistant", "Noted.")],
        proposals: [wireProposal("p1", [EGGS], 1)],
      }),
    });
    await openChat();

    const answer = (await screen.findByText("Noted.")).closest("li")!;
    expect(within(answer).getByRole("group", { name: "Thought to file: Eggs" })).toBeInTheDocument();
  });
});

describe("the held proposal before an action", () => {
  const withHistory = () =>
    detail({
      held_proposal_id: "p1",
      messages: [storedMessage(0, "user", "I need oat milk"), storedMessage(1, "assistant", "Noted.")],
    });

  it("shows the held proposal before /compact, then sends /compact", async () => {
    const { calls } = api({
      "GET /api/conversations/c1": json(200, withHistory()),
      "POST /api/conversations/c1/proposal": json(200, { proposal: wireProposal("p1", [OAT], 1) }),
      "POST /api/chat": () => streamOf(delta("Summary ready."), done),
    });
    await openChat();
    await screen.findByText("Noted.");

    send("/compact");

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Title")).toHaveValue("Oat milk");
    expect(calls.filter((c) => c.path === "/api/chat")).toEqual([]);

    fireEvent.click(screen.getByRole("button", { name: "Compact now" }));

    await waitFor(() =>
      expect(calls.filter((c) => c.path === "/api/chat").map((c) => c.body)).toEqual([
        { message: "/compact", conversation_id: "c1" },
      ]),
    );
  });

  it("offers only the part not saved", async () => {
    api({
      "GET /api/conversations/c1": json(200, withHistory()),
      "POST /api/conversations/c1/proposal": json(200, {
        proposal: wireProposal("p1", [{ ...OAT, thought_id: "t1" }, DENTIST], 1),
      }),
    });
    await openChat();
    await screen.findByText("Noted.");

    send("/compact");

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByRole("group", { name: "Thought to file: Dentist" })).toBeInTheDocument();
    expect(within(dialog).queryByText("Oat milk")).not.toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "Merge into one" })).not.toBeInTheDocument();
  });

  it("sends /compact at once when there is nothing to propose", async () => {
    const { calls } = api({
      "GET /api/conversations/c1": json(200, withHistory()),
      "POST /api/conversations/c1/proposal": json(200, { proposal: null }),
      "POST /api/chat": () => streamOf(delta("Summary ready."), done),
    });
    await openChat();
    await screen.findByText("Noted.");

    send("/compact");

    await waitFor(() => expect(calls.filter((c) => c.path === "/api/chat")).toHaveLength(1));
    expect(screen.queryByText("Before you go on")).not.toBeInTheDocument();
  });

  it("does not show the held proposal when an old conversation is opened", async () => {
    const { calls } = api({
      "GET /api/conversations/c1": json(200, { ...withHistory(), last_activity_at: "2026-01-01T10:00:00Z" }),
    });
    await openChat();
    await screen.findByText("Noted.");

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(calls.filter((c) => c.path.includes("/proposal"))).toEqual([]);
  });
});

describe("a replaced proposal", () => {
  it("folds a replaced card away when a later proposal replaces it, and it can still be confirmed", async () => {
    const { calls } = api({
      "POST /api/chat": [
        proposing(OAT),
        () =>
          streamOf(
            toolEvent("propose_thought", "start"),
            proposalEvent("p2", [{ ...OAT, title: "Oat and soy milk" }], 5, "p1"),
            toolEvent("propose_thought", "end", "Proposed a thought to file"),
            delta("Now, taxes."),
            done,
          ),
      ],
      [CONFIRM]: saved("t1"),
    });
    await openChat();
    send("I need oat milk");
    await screen.findByRole("group", { name: "Thought to file: Oat milk" });
    await waitFor(() => expect(screen.getByLabelText("Message")).toBeEnabled());

    send("unrelated: how do taxes work?");

    expect(await screen.findByRole("group", { name: "Thought to file: Oat and soy milk" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Thought to file: Oat milk" })).not.toBeInTheDocument();
    expect(screen.getByText(/A thought to file was replaced by a\s+newer proposal/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    fireEvent.click(within(card("Oat milk")).getByRole("button", { name: "Confirm" }));

    await screen.findByRole("group", { name: "Saved: Oat milk" });
    expect(calls.filter((c) => c.path.endsWith("/proposals/p1/confirm"))).toHaveLength(1);
  });

  it("shows a replaced proposal folded when the conversation is reopened, with its saved parts in view", async () => {
    api({
      "GET /api/conversations/c1": json(
        200,
        detail({
          messages: [
            storedMessage(0, "user", "/push oat milk and eggs"),
            storedMessage(1, "assistant", null, {
              tool_calls: [{ id: "c", type: "function", function: { name: "propose_thought", arguments: "{}" } }],
            }),
            storedMessage(2, "tool", "shown", { tool_call_id: "c", details: { proposal_id: "p1" } }),
            storedMessage(3, "assistant", "Ready to check."),
          ],
          proposals: [wireProposal("p1", [{ ...OAT, thought_id: "t1" }, EGGS], 2, "p2")],
        }),
      ),
    });
    await openChat();

    expect(await screen.findByRole("group", { name: "Saved: Oat milk" })).toBeInTheDocument();
    expect(screen.queryByRole("group", { name: "Thought to file: Eggs" })).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(card("Eggs")).toBeInTheDocument();
  });
});
