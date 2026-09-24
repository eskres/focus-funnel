// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { delta, done, fakeApi, json, loadout, proposalEvent, streamOf, toolEvent } from "@/test/fake-api";

import { Chat } from "./chat";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/app",
}));

const PROPOSAL = { title: "Oat milk", summary: "Buy oat milk tomorrow.", tags: ["shopping"] };
const NOT_AVAILABLE = "Saving thoughts is not available yet. Copy the text to keep it.";

function conversation() {
  return {
    id: "c1",
    title: "Milk",
    provider_id: "nebius",
    model: "vendor/nano",
    reasoning_effort: null,
    archived: false,
    last_activity_at: "2026-09-23T10:00:00Z",
    created_at: "2026-09-23T10:00:00Z",
    last_prompt_tokens: null,
    held_proposal: null,
    messages: [],
  };
}

function send(text: string) {
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
}

const proposing = () =>
  streamOf(
    toolEvent("propose_thought", "start"),
    proposalEvent(PROPOSAL),
    toolEvent("propose_thought", "end", "Proposed a thought to file"),
    delta("Want to keep it?"),
    done,
  );

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("ProposalCard", () => {
  it("shows the proposal, confirms the edits, and shows the not-available outcome", async () => {
    const { calls } = fakeApi({
      "GET /api/settings/models": json(200, loadout()),
      "GET /api/conversations/c1": json(200, conversation()),
      "POST /api/chat": proposing,
      "POST /api/conversations/c1/proposal/confirm": (_url, init) =>
        json(200, { saved: false, message: NOT_AVAILABLE, proposal: JSON.parse(String(init.body)) }),
    });
    render(<Chat conversationId="c1" />);
    await screen.findByLabelText("Message");

    send("I need to buy oat milk tomorrow");

    const card = await screen.findByRole("region", { name: "Proposal to file" });
    expect(within(card).getByLabelText("Title")).toHaveValue("Oat milk");
    expect(within(card).getByLabelText("Summary")).toHaveValue("Buy oat milk tomorrow.");
    expect(within(card).getByLabelText(/Tags/)).toHaveValue("shopping");

    fireEvent.change(within(card).getByLabelText("Title"), { target: { value: "Oat and soy milk" } });
    fireEvent.change(within(card).getByLabelText("Summary"), {
      target: { value: "Buy oat and soy milk tomorrow." },
    });
    fireEvent.change(within(card).getByLabelText(/Tags/), { target: { value: "shopping, milk" } });
    fireEvent.click(within(card).getByRole("button", { name: "Confirm" }));

    expect(await within(card).findByText(NOT_AVAILABLE)).toBeInTheDocument();
    expect(calls.find((c) => c.path.endsWith("/proposal/confirm"))?.body).toEqual({
      title: "Oat and soy milk",
      summary: "Buy oat and soy milk tomorrow.",
      tags: ["shopping", "milk"],
    });
    // The text stays, so the user can copy it.
    expect(within(card).getByLabelText("Title")).toHaveValue("Oat and soy milk");
    expect(card.textContent?.toLowerCase()).not.toContain("delete");
  });

  it("keeps the conversation going and holds the proposal when the user sends another message", async () => {
    const { calls } = fakeApi({
      "GET /api/settings/models": json(200, loadout()),
      "GET /api/conversations/c1": json(200, conversation()),
      "POST /api/chat": [proposing, () => streamOf(delta("Soy too, then."), done)],
    });
    render(<Chat conversationId="c1" />);
    await screen.findByLabelText("Message");

    send("I need to buy oat milk tomorrow");
    await screen.findByRole("region", { name: "Proposal to file" });
    send("and soy milk?");

    expect(await screen.findByText("Soy too, then.")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByLabelText("Message")).toBeEnabled());
    expect(screen.getAllByRole("region", { name: "Proposal to file" })).toHaveLength(1);
    expect(calls.filter((c) => c.path.includes("/proposal"))).toEqual([]);
  });
});

describe("the held proposal before an action", () => {
  const held = { ...PROPOSAL, position: 1 };
  const withHistory = () => ({
    ...conversation(),
    held_proposal: held,
    messages: [
      { ...message(0, "user", "I need oat milk") },
      { ...message(1, "assistant", "Noted.") },
    ],
  });

  function message(position: number, role: string, content: string) {
    return {
      id: `m${position}`,
      position,
      role,
      content,
      tool_calls: null,
      tool_call_id: null,
      status: "complete",
      error_code: null,
      compacted: false,
      created_at: "2026-09-23T10:00:00Z",
    };
  }

  it("shows the held proposal before /compact, then sends /compact", async () => {
    const { calls } = fakeApi({
      "GET /api/settings/models": json(200, loadout()),
      "GET /api/conversations/c1": json(200, withHistory()),
      "POST /api/conversations/c1/proposal": json(200, { held_proposal: held }),
      "POST /api/chat": () => streamOf(delta("Summary ready."), done),
    });
    render(<Chat conversationId="c1" />);
    await screen.findByText("Noted.");

    send("/compact");

    const card = await screen.findByRole("region", { name: "Proposal to file" });
    expect(within(card).getByLabelText("Title")).toHaveValue("Oat milk");
    expect(calls.filter((c) => c.path === "/api/chat")).toEqual([]);

    fireEvent.click(screen.getByRole("button", { name: "Compact now" }));

    await waitFor(() =>
      expect(calls.filter((c) => c.path === "/api/chat").map((c) => c.body)).toEqual([
        { message: "/compact", conversation_id: "c1" },
      ]),
    );
  });

  it("sends /compact at once when there is nothing to propose", async () => {
    const { calls } = fakeApi({
      "GET /api/settings/models": json(200, loadout()),
      "GET /api/conversations/c1": json(200, { ...withHistory(), held_proposal: null }),
      "POST /api/conversations/c1/proposal": json(200, { held_proposal: null }),
      "POST /api/chat": () => streamOf(delta("Summary ready."), done),
    });
    render(<Chat conversationId="c1" />);
    await screen.findByText("Noted.");

    send("/compact");

    await waitFor(() => expect(calls.filter((c) => c.path === "/api/chat")).toHaveLength(1));
    expect(screen.queryByRole("region", { name: "Proposal to file" })).not.toBeInTheDocument();
  });

  it("shows the proposal on a topic change, from the proposal event", async () => {
    fakeApi({
      "GET /api/settings/models": json(200, loadout()),
      "GET /api/conversations/c1": json(200, withHistory()),
      "POST /api/chat": proposing,
    });
    render(<Chat conversationId="c1" />);
    await screen.findByText("Noted.");

    send("unrelated: how do taxes work?");

    expect(await screen.findByRole("region", { name: "Proposal to file" })).toBeInTheDocument();
  });

  it("does not show the held proposal when an old conversation is opened", async () => {
    const { calls } = fakeApi({
      "GET /api/settings/models": json(200, loadout()),
      "GET /api/conversations/c1": json(200, {
        ...withHistory(),
        last_activity_at: "2026-01-01T10:00:00Z",
      }),
    });
    render(<Chat conversationId="c1" />);
    await screen.findByText("Noted.");

    expect(screen.queryByRole("region", { name: "Proposal to file" })).not.toBeInTheDocument();
    expect(calls.filter((c) => c.path.includes("/proposal"))).toEqual([]);
  });
});
