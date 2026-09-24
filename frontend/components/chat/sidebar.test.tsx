// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fakeApi, json, summary, wireProposal } from "@/test/fake-api";

import { ConversationsProvider } from "./conversations-context";
import { Sidebar } from "./sidebar";

const push = vi.fn();
let pathname = "/app";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  usePathname: () => pathname,
}));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  pathname = "/app";
});

function renderSidebar() {
  return render(
    <ConversationsProvider>
      <Sidebar />
    </ConversationsProvider>,
  );
}

function rowTitles(listName: string) {
  return within(screen.getByRole("list", { name: listName }))
    .getAllByRole("link")
    .map((link) => link.textContent);
}

async function openMenu(title: string) {
  fireEvent.click(await screen.findByRole("button", { name: `Options for ${title}` }));
  return screen.findByRole("menu");
}

const rent = summary("c1", "Rent");
const milk = summary("c2", "Oat milk");
const bikes = summary("c3", "Bikes", { archived: true });

describe("Sidebar", () => {
  it("lists conversations in the order given, newest activity first", async () => {
    fakeApi({ "GET /api/conversations": json(200, { conversations: [milk, rent], archived: [] }) });
    renderSidebar();

    await screen.findByText("Oat milk");
    expect(rowTitles("Recent conversations")).toEqual(["Oat milk", "Rent"]);
    expect(screen.getByRole("link", { name: "Oat milk" })).toHaveAttribute("href", "/app/c2");
    expect(screen.getByText("New conversation").closest("a")).toHaveAttribute("href", "/app");
  });

  it("says there are no conversations yet", async () => {
    fakeApi({ "GET /api/conversations": json(200, { conversations: [], archived: [] }) });
    renderSidebar();

    expect(await screen.findByText("No conversations yet.")).toBeInTheDocument();
  });

  it("marks the open conversation", async () => {
    pathname = "/app/c1";
    fakeApi({ "GET /api/conversations": json(200, { conversations: [milk, rent], archived: [] }) });
    renderSidebar();

    expect(await screen.findByRole("link", { name: "Rent" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Oat milk" })).not.toHaveAttribute("aria-current");
  });

  it("shows archived conversations in their own section", async () => {
    fakeApi({ "GET /api/conversations": json(200, { conversations: [rent], archived: [bikes] }) });
    renderSidebar();

    const toggle = await screen.findByRole("button", { name: "Archived (1)" });
    expect(screen.queryByText("Bikes")).not.toBeInTheDocument();
    fireEvent.click(toggle);
    expect(rowTitles("Archived conversations")).toEqual(["Bikes"]);
  });

  it("renames a conversation", async () => {
    const renamed = { ...rent, title: "Rent plan" };
    const { calls } = fakeApi({
      "GET /api/conversations": [
        json(200, { conversations: [rent], archived: [] }),
        json(200, { conversations: [renamed], archived: [] }),
      ],
      "PATCH /api/conversations/c1": json(200, { ...renamed, messages: [] }),
    });
    renderSidebar();

    fireEvent.click(within(await openMenu("Rent")).getByRole("menuitem", { name: "Rename" }));
    const input = await screen.findByLabelText("Conversation title");
    fireEvent.change(input, { target: { value: "Rent plan" } });
    fireEvent.keyDown(input, { key: "Enter" });

    expect(await screen.findByRole("link", { name: "Rent plan" })).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ title: "Rent plan" });
  });

  it("archives a conversation and moves it to the archived section", async () => {
    const { calls } = fakeApi({
      "GET /api/conversations": [
        json(200, { conversations: [rent, milk], archived: [] }),
        json(200, { conversations: [milk], archived: [{ ...rent, archived: true }] }),
      ],
      "POST /api/conversations/c1/proposal": json(200, { proposal: null }),
      "PATCH /api/conversations/c1": json(200, { ...rent, archived: true, messages: [] }),
    });
    renderSidebar();

    const menu = await openMenu("Rent");
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Archive" }));

    await waitFor(() => expect(rowTitles("Recent conversations")).toEqual(["Oat milk"]));
    expect(screen.queryByRole("region", { name: "Proposal to file" })).not.toBeInTheDocument();
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ archived: true });
    fireEvent.click(screen.getByRole("button", { name: "Archived (1)" }));
    expect(rowTitles("Archived conversations")).toEqual(["Rent"]);
  });

  it("shows the held proposal before archiving, then archives", async () => {
    const held = wireProposal("p1", [{ title: "Rent plan", summary: "Pay rent on the 1st.", tags: ["money"] }], 3);
    const { calls } = fakeApi({
      "GET /api/conversations": [
        json(200, { conversations: [rent, milk], archived: [] }),
        json(200, { conversations: [milk], archived: [{ ...rent, archived: true }] }),
      ],
      "POST /api/conversations/c1/proposal": json(200, { proposal: held }),
      "PATCH /api/conversations/c1": json(200, { ...rent, archived: true, messages: [] }),
    });
    renderSidebar();

    const menu = await openMenu("Rent");
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Archive" }));

    const card = await screen.findByRole("region", { name: "Proposal to file" });
    expect(within(card).getByLabelText("Title")).toHaveValue("Rent plan");
    expect(calls.filter((c) => c.method === "PATCH")).toEqual([]);
    expect(screen.getByRole("dialog").textContent?.toLowerCase()).not.toContain("delete");

    fireEvent.click(screen.getByRole("button", { name: "Archive now" }));

    await waitFor(() => expect(rowTitles("Recent conversations")).toEqual(["Oat milk"]));
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ archived: true });
  });

  it("does not archive when the proposal is cancelled", async () => {
    const held = wireProposal("p1", [{ title: "Rent plan", summary: "Pay rent on the 1st.", tags: [] }], 3);
    const { calls } = fakeApi({
      "GET /api/conversations": json(200, { conversations: [rent], archived: [] }),
      "POST /api/conversations/c1/proposal": json(200, { proposal: held }),
    });
    renderSidebar();

    const menu = await openMenu("Rent");
    fireEvent.click(within(menu).getByRole("menuitem", { name: "Archive" }));
    await screen.findByRole("region", { name: "Proposal to file" });
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    await waitFor(() =>
      expect(screen.queryByRole("region", { name: "Proposal to file" })).not.toBeInTheDocument(),
    );
    expect(calls.filter((c) => c.method === "PATCH")).toEqual([]);
  });

  it("restores an archived conversation", async () => {
    const { calls } = fakeApi({
      "GET /api/conversations": [
        json(200, { conversations: [rent], archived: [bikes] }),
        json(200, { conversations: [{ ...bikes, archived: false }, rent], archived: [] }),
      ],
      "PATCH /api/conversations/c3": json(200, { ...bikes, archived: false, messages: [] }),
    });
    renderSidebar();

    fireEvent.click(await screen.findByRole("button", { name: "Archived (1)" }));
    fireEvent.click(within(await openMenu("Bikes")).getByRole("menuitem", { name: "Restore" }));

    await waitFor(() => expect(rowTitles("Recent conversations")).toEqual(["Bikes", "Rent"]));
    expect(calls.find((c) => c.method === "PATCH")?.body).toEqual({ archived: false });
  });

  it("deletes from the row menu after the same confirmation", async () => {
    pathname = "/app/c1";
    const { calls } = fakeApi({
      "GET /api/conversations": [
        json(200, { conversations: [rent, milk], archived: [] }),
        json(200, { conversations: [milk], archived: [] }),
      ],
      "DELETE /api/conversations/c1": new Response(null, { status: 204 }),
    });
    renderSidebar();

    fireEvent.click(within(await openMenu("Rent")).getByRole("menuitem", { name: "Delete" }));
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent("Delete this conversation?");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete" }));

    await waitFor(() => expect(push).toHaveBeenCalledWith("/app"));
    expect(calls.some((c) => c.method === "DELETE")).toBe(true);
    await waitFor(() => expect(rowTitles("Recent conversations")).toEqual(["Oat milk"]));
  });

  it("changes nothing when a delete is cancelled", async () => {
    const { calls } = fakeApi({
      "GET /api/conversations": json(200, { conversations: [rent], archived: [] }),
    });
    renderSidebar();

    fireEvent.click(within(await openMenu("Rent")).getByRole("menuitem", { name: "Delete" }));
    fireEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(calls.some((c) => c.method === "DELETE")).toBe(false);
    expect(screen.getByRole("link", { name: "Rent" })).toBeInTheDocument();
  });
});

describe("Sidebar with the chat", () => {
  it("moves an archived conversation back to the main list when a message is sent in it", async () => {
    const { Chat } = await import("./chat");
    const { delta, done, loadout, loadoutEntry, storedMessage, streamOf } = await import(
      "@/test/fake-api"
    );
    pathname = "/app/c3";
    fakeApi({
      "GET /api/conversations": [
        json(200, { conversations: [rent], archived: [bikes] }),
        json(200, { conversations: [{ ...bikes, archived: false }, rent], archived: [] }),
      ],
      "GET /api/settings/models": json(200, loadout([loadoutEntry("vendor/nano", { is_default: true })])),
      "GET /api/conversations/c3": json(200, {
        ...bikes,
        last_prompt_tokens: null,
        held_proposal_id: null,
    proposals: [],
        messages: [storedMessage(0, "user", "bikes?"), storedMessage(1, "assistant", "Yes.")],
      }),
      "POST /api/chat": () => streamOf(delta("Back again."), done),
    });
    render(
      <ConversationsProvider>
        <Sidebar />
        <Chat conversationId="c3" />
      </ConversationsProvider>,
    );
    await screen.findByText("Yes.");
    expect(rowTitles("Recent conversations")).toEqual(["Rent"]);

    fireEvent.change(screen.getByLabelText("Message"), { target: { value: "more bikes" } });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await screen.findByText("Back again.");
    await waitFor(() => expect(rowTitles("Recent conversations")).toEqual(["Bikes", "Rent"]));
  });
});
