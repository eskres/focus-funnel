// @vitest-environment jsdom
import { fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  conversationEvent,
  delta,
  done,
  fakeApi,
  json,
  loadout,
  loadoutEntry,
  streamOf,
} from "@/test/fake-api";

import { ConversationsProvider } from "./conversations-context";
import { NewChat } from "./new-chat";
import { Sidebar } from "./sidebar";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => window.location.pathname,
}));

beforeEach(() => {
  window.history.replaceState(null, "", "/app");
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("NewChat", () => {
  it("starts an empty chat on New conversation after a conversation began on the page", async () => {
    const { calls } = fakeApi({
      "GET /api/settings/models": json(
        200,
        loadout([loadoutEntry("vendor/nano", { is_default: true })]),
      ),
      "GET /api/conversations": json(200, { conversations: [], archived: [] }),
      "POST /api/chat": [
        () => streamOf(conversationEvent("c1", "first"), delta("One."), done),
        () => streamOf(conversationEvent("c2", "second"), delta("Two."), done),
      ],
    });
    render(
      <ConversationsProvider>
        <Sidebar />
        <NewChat />
      </ConversationsProvider>,
    );
    await screen.findByRole("option", { name: "vendor/nano" });

    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "first" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findByText("One.");

    fireEvent.click(screen.getByText("New conversation"));

    expect(screen.queryByText("One.")).not.toBeInTheDocument();
    await screen.findByRole("option", { name: "vendor/nano" });
    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "second" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));
    const list = await screen.findByRole("list", { name: "Conversation" });
    await within(list).findByText("Two.");

    const bodies = calls.filter((c) => c.path === "/api/chat").map((c) => c.body);
    // The second message starts its own conversation.
    expect(bodies[1]).not.toHaveProperty("conversation_id");
  });
});
