// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  compactDraftEvent,
  compactModelsEvent,
  delta,
  done,
  errorEvent,
  fakeApi,
  json,
  loadout,
  loadoutEntry,
  noticeEvent,
  storedMessage,
  streamOf,
  usageEvent,
} from "@/test/fake-api";

import { Chat } from "./chat";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/app",
}));

const NANO = "vendor/nano";
const BIG = "vendor/big";
const settings = loadout([loadoutEntry(NANO, { is_default: true }), loadoutEntry(BIG)]);
const TEN = Array.from({ length: 10 }, (_, n) =>
  storedMessage(n, n % 2 === 0 ? "user" : "assistant", `message ${n}`),
);

function conversation(extra: Record<string, unknown> = {}) {
  return {
    id: "c1",
    title: "Rent",
    provider_id: "nebius",
    model: NANO,
    reasoning_effort: null,
    archived: false,
    last_activity_at: "2026-09-23T10:00:00Z",
    created_at: "2026-09-23T10:00:00Z",
    last_prompt_tokens: 1000,
    held_proposal: null,
    context: { tokens: 1000, estimated: false, context_length: 131072 },
    messages: TEN,
    ...extra,
  };
}

function send(text: string) {
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
}

function figure() {
  return screen.getByTestId("context-figure").textContent;
}

const nothingHeld = json(200, { held_proposal: null });

beforeEach(() => {
  window.history.replaceState(null, "", "/app/c1");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("the context meter", () => {
  it("shows the stored figure and follows the usage event", async () => {
    fakeApi({
      "GET /api/settings/models": json(200, settings),
      "GET /api/conversations/c1": json(200, conversation()),
      "POST /api/chat": () => streamOf(delta("Ok."), usageEvent(98_000, 131072), done),
    });
    render(<Chat conversationId="c1" />);
    await screen.findByText("message 9");
    expect(figure()).toBe("1k of 131.1k tokens");
    expect(screen.getByRole("meter", { name: "Context used" })).toHaveAttribute(
      "aria-valuenow",
      "1000",
    );

    send("more");

    await waitFor(() => expect(figure()).toBe("98k of 131.1k tokens"));
  });

  it("shows the tokens with no limit when the context length is unknown", async () => {
    fakeApi({
      "GET /api/settings/models": json(200, settings),
      "GET /api/conversations/c1": json(
        200,
        conversation({ context: { tokens: 1500, estimated: false, context_length: null } }),
      ),
    });
    render(<Chat conversationId="c1" />);
    await screen.findByText("message 9");

    expect(figure()).toBe("1.5k tokens in use");
    expect(screen.queryByRole("meter")).not.toBeInTheDocument();
  });

  it("is marked as an estimate against the new limit after a model switch", async () => {
    const { calls } = fakeApi({
      "GET /api/settings/models": json(200, settings),
      "GET /api/conversations/c1": json(200, conversation()),
      "GET /api/providers/nebius/models": json(200, {
        models: [
          { id: NANO, context_length: 131072, features: { tool_calling: "supported" } },
          { id: BIG, context_length: 262144, features: { tool_calling: "supported" } },
        ],
      }),
      "POST /api/chat": () => streamOf(delta("Ok."), usageEvent(1200, 262144), done),
    });
    render(<Chat conversationId="c1" />);
    await screen.findByText("message 9");

    fireEvent.change(screen.getByLabelText("Model"), {
      target: { value: `nebius\u0000${BIG}` },
    });

    await waitFor(() => expect(figure()).toBe("About 1k of 262.1k tokens (estimate)"));
    expect(calls.some((c) => c.path === "/api/providers/nebius/models")).toBe(true);

    send("next");

    await waitFor(() => expect(figure()).toBe("1.2k of 262.1k tokens"));
  });

  it("shows a conversation over a smaller model's limit", async () => {
    fakeApi({
      "GET /api/settings/models": json(200, settings),
      "GET /api/conversations/c1": json(
        200,
        conversation({ context: { tokens: 20_000, estimated: true, context_length: 8192 } }),
      ),
    });
    render(<Chat conversationId="c1" />);
    await screen.findByText("message 9");

    expect(figure()).toBe("About 20k of 8.2k tokens, over the limit (estimate)");
  });
});

describe("the compact suggestion", () => {
  it("appears after the notice, never blocks sending, and starts /compact", async () => {
    const { calls } = fakeApi({
      "GET /api/settings/models": json(200, settings),
      "GET /api/conversations/c1": json(200, conversation()),
      "POST /api/conversations/c1/proposal": nothingHeld,
      "POST /api/chat": [
        () =>
          streamOf(
            delta("Ok."),
            usageEvent(95_000, 131072),
            noticeEvent({ kind: "compact_suggested", prompt_tokens: 95_000, context_length: 131072 }),
            done,
          ),
        () => streamOf(compactDraftEvent("We agreed on 900.", 3), done),
      ],
    });
    render(<Chat conversationId="c1" />);
    await screen.findByText("message 9");

    send("more");

    const notice = await screen.findByText(/This conversation is getting long\. 72%/);
    expect(notice).toBeInTheDocument();
    expect(screen.queryByText(/delete/i)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Message")).not.toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Compact now" }));

    expect(await screen.findByLabelText("Summary")).toHaveValue("We agreed on 900.");
    expect(calls.filter((c) => c.path === "/api/chat").at(-1)?.body).toEqual({
      message: "/compact",
      conversation_id: "c1",
    });
  });
});

describe("the /compact dialog", () => {
  function compactedDetail(summary: string) {
    return conversation({
      last_prompt_tokens: null,
      context: { tokens: 300, estimated: true, context_length: 131072 },
      messages: [
        ...TEN.map((m, n) => ({ ...m, compacted: n <= 3 })),
        storedMessage(10, "summary", summary),
      ],
    });
  }

  it("accepts the edited draft through the compaction endpoint", async () => {
    const { calls } = fakeApi({
      "GET /api/settings/models": json(200, settings),
      "GET /api/conversations/c1": json(200, conversation()),
      "POST /api/conversations/c1/proposal": nothingHeld,
      "POST /api/chat": () => streamOf(compactDraftEvent("We agreed on 900.", 3), done),
      "POST /api/conversations/c1/compaction": json(200, compactedDetail("Rent is 900 a month.")),
    });
    render(<Chat conversationId="c1" />);
    await screen.findByText("message 9");

    send("/compact");
    const summary = await screen.findByLabelText("Summary");
    fireEvent.change(summary, { target: { value: "Rent is 900 a month." } });
    fireEvent.click(screen.getByRole("button", { name: "Accept summary" }));

    await waitFor(() =>
      expect(calls.find((c) => c.path === "/api/conversations/c1/compaction")?.body).toEqual({
        summary: "Rent is 900 a month.",
        through_position: 3,
      }),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    const shown = screen.getByRole("region", { name: "Summary of earlier messages" });
    expect(within(shown).getByText("Rent is 900 a month.")).toBeInTheDocument();
    expect(screen.getAllByText("Compacted")).toHaveLength(4);
    expect(screen.getByText("message 0")).toBeInTheDocument();
    expect(figure()).toBe("About 300 of 131.1k tokens (estimate)");
    // The /compact command is not added to the conversation.
    expect(screen.queryByText("/compact", { selector: "p" })).not.toBeInTheDocument();
  });

  it("changes nothing when cancelled", async () => {
    const { calls } = fakeApi({
      "GET /api/settings/models": json(200, settings),
      "GET /api/conversations/c1": json(200, conversation()),
      "POST /api/conversations/c1/proposal": nothingHeld,
      "POST /api/chat": () => streamOf(compactDraftEvent("We agreed on 900.", 3), done),
    });
    render(<Chat conversationId="c1" />);
    await screen.findByText("message 9");

    send("/compact");
    await screen.findByLabelText("Summary");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(calls.some((c) => c.path.endsWith("/compaction"))).toBe(false);
    expect(screen.queryByText("Compacted")).not.toBeInTheDocument();
    expect(figure()).toBe("1k of 131.1k tokens");
    expect(screen.getByLabelText("Message")).not.toBeDisabled();
  });

  it("shows a failed summary and changes nothing", async () => {
    fakeApi({
      "GET /api/settings/models": json(200, settings),
      "GET /api/conversations/c1": json(200, conversation()),
      "POST /api/conversations/c1/proposal": nothingHeld,
      "POST /api/chat": () =>
        streamOf(errorEvent("provider_unreachable", "Couldn't reach Nebius. Try again.")),
    });
    render(<Chat conversationId="c1" />);
    await screen.findByText("message 9");

    send("/compact");

    expect(
      await screen.findByText("Couldn't reach Nebius. Try again. Nothing in the conversation changed."),
    ).toBeInTheDocument();
    expect(screen.queryByText("Compacted")).not.toBeInTheDocument();
  });

  it("asks the user to choose a larger loadout model when the conversation is too long", async () => {
    const { calls } = fakeApi({
      "GET /api/settings/models": json(200, settings),
      "GET /api/conversations/c1": json(200, conversation()),
      "POST /api/conversations/c1/proposal": nothingHeld,
      "POST /api/chat": [
        () =>
          streamOf(
            compactModelsEvent(8192, [
              { model: NANO, context_length: 131072 },
              { model: BIG, context_length: 262144 },
            ]),
            done,
          ),
        () => streamOf(compactDraftEvent("Written by the big one.", 3, BIG), done),
      ],
    });
    render(<Chat conversationId="c1" />);
    await screen.findByText("message 9");

    send("/compact");

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/too long for its model \(8\.2k tokens\)/)).toBeInTheDocument();
    expect(within(dialog).getByText("131.1k tokens")).toBeInTheDocument();
    expect(within(dialog).getByText("262.1k tokens")).toBeInTheDocument();
    const write = within(dialog).getByRole("button", { name: "Write the summary" });
    expect(write).toBeDisabled();
    expect(calls.filter((c) => c.path === "/api/chat")).toHaveLength(1);

    fireEvent.click(within(dialog).getByRole("radio", { name: new RegExp(BIG) }));
    fireEvent.click(write);

    expect(await screen.findByLabelText("Summary")).toHaveValue("Written by the big one.");
    expect(screen.getByText(`Written by ${BIG}.`)).toBeInTheDocument();
    expect(calls.filter((c) => c.path === "/api/chat").at(-1)?.body).toEqual({
      message: "/compact",
      conversation_id: "c1",
      compact_model: { provider_id: "nebius", model: BIG },
    });
  });

  it("says so when no loadout model is large enough", async () => {
    fakeApi({
      "GET /api/settings/models": json(200, settings),
      "GET /api/conversations/c1": json(200, conversation()),
      "POST /api/conversations/c1/proposal": nothingHeld,
      "POST /api/chat": () => streamOf(compactModelsEvent(8192, []), done),
    });
    render(<Chat conversationId="c1" />);
    await screen.findByText("message 9");

    send("/compact");

    expect(await screen.findByText(/No model in your loadout has a large enough context/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Write the summary" })).not.toBeInTheDocument();
    expect(screen.queryByText(/delete/i)).not.toBeInTheDocument();
  });
});

describe("the usage warning notice", () => {
  it.each([
    [{ unit: "usd", amount: 5 }, "$5.00"],
    [{ unit: "tokens", amount: 2_000_000 }, "2,000,000 tokens"],
  ])("names the threshold %j and keeps the chat going", async (threshold, named) => {
    fakeApi({
      "GET /api/settings/models": json(200, settings),
      "GET /api/conversations/c1": json(200, conversation()),
      "POST /api/chat": () =>
        streamOf(
          delta("Ok."),
          noticeEvent({ kind: "usage_warning", ...threshold, month_cost_usd: 5.1, month_tokens: 1 }),
          done,
        ),
    });
    render(<Chat conversationId="c1" />);
    await screen.findByText("message 9");

    send("more");

    expect(
      await screen.findByText(
        `Your usage this month has reached your warning threshold of ${named}. You can keep chatting.`,
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "See usage" })).toHaveAttribute("href", "/settings#usage");
    expect(screen.getByLabelText("Message")).not.toBeDisabled();

    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText(/warning threshold/)).not.toBeInTheDocument();
  });
});
