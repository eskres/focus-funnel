// @vitest-environment jsdom
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { Chat } from "@/components/chat/chat";
import { DemoBar } from "@/components/demo/demo-bar";
import { DemoProvider } from "@/components/demo/demo-context";
import { apiFetch } from "@/lib/api";
import { delta, done, errorResponse, fakeApi, json, loadout, loadoutEntry, streamOf } from "@/test/fake-api";

const replace = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace }),
  usePathname: () => "/app",
}));
vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));

const SETTINGS = { keyTtlMinutes: 30, keyMaxHours: 4 };
const EXPIRES = "2026-09-25T12:00:00Z";
const NEBIUS_NOTICE = "Nebius does not use your prompts or outputs to train models.";
const providers = {
  providers: [
    { id: "nebius", label: "Nebius Token Factory", notice: NEBIUS_NOTICE },
    { id: "openrouter", label: "OpenRouter", notice: "OpenRouter passes prompts to the model's host." },
  ],
  custom_provider_allowed: false,
};

const me = (accepted: boolean) =>
  json(200, { id: "u1", created_at: EXPIRES, mode: "demo", expires_at: EXPIRES, demo_notice_accepted: accepted });

function renderChat() {
  return render(
    <DemoProvider settings={SETTINGS}>
      <Chat />
    </DemoProvider>,
  );
}

function sendMessage(text: string) {
  fireEvent.change(screen.getByLabelText("Message"), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: "Send" }));
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

describe("the demo notice", () => {
  it("blocks the first message until the visitor accepts, then sends it", async () => {
    const api = fakeApi({
      "GET /api/me": me(false),
      "GET /api/settings/models": json(200, loadout([loadoutEntry("vendor/nano", { is_default: true })])),
      "GET /api/providers": json(200, providers),
      "POST /api/demo/notice": new Response(null, { status: 204 }),
      "POST /api/chat": () => streamOf(delta("Hello!"), done),
    });
    renderChat();
    await waitFor(() => expect(api.calls.some((c) => c.path === "/api/me")).toBe(true));
    await waitFor(() => expect(api.calls.some((c) => c.path === "/api/settings/models")).toBe(true));

    sendMessage("buy milk");

    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Whoever runs this server can technically read/)).toBeInTheDocument();
    expect(within(dialog).getByText(/30 minutes without use or 4 hours/)).toBeInTheDocument();
    // The chosen model's provider notice, and not another provider's.
    expect(await within(dialog).findByText(NEBIUS_NOTICE)).toBeInTheDocument();
    expect(within(dialog).queryByText(/OpenRouter passes/)).toBeNull();
    expect(api.calls.filter((c) => c.path === "/api/chat")).toHaveLength(0);

    fireEvent.click(within(dialog).getByRole("button", { name: "I accept" }));

    await waitFor(() => expect(api.calls.filter((c) => c.path === "/api/chat")).toHaveLength(1));
    const order = api.calls.map((c) => `${c.method} ${c.path}`);
    expect(order.indexOf("POST /api/demo/notice")).toBeLessThan(order.indexOf("POST /api/chat"));
    expect(api.calls.find((c) => c.path === "/api/chat")?.body).toMatchObject({ message: "buy milk" });
    expect(await screen.findByText("Hello!")).toBeInTheDocument();
  });

  it("does not send the message when the visitor closes the notice", async () => {
    const api = fakeApi({
      "GET /api/me": me(false),
      "GET /api/settings/models": json(200, loadout()),
      "GET /api/providers": json(200, providers),
    });
    renderChat();
    await waitFor(() => expect(api.calls.some((c) => c.path === "/api/me")).toBe(true));

    sendMessage("hello");
    fireEvent.click(await screen.findByRole("button", { name: "Not now" }));

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(api.calls.filter((c) => c.path === "/api/chat")).toHaveLength(0);
  });

  it("is not shown again once accepted in this session", async () => {
    const api = fakeApi({
      "GET /api/me": me(true),
      "GET /api/settings/models": json(200, loadout()),
      "POST /api/chat": () => streamOf(delta("Hi"), done),
    });
    renderChat();
    await waitFor(() => expect(api.calls.some((c) => c.path === "/api/me")).toBe(true));
    // Let the notice state from /api/me land.
    await act(async () => undefined);

    sendMessage("hello");

    await waitFor(() => expect(api.calls.filter((c) => c.path === "/api/chat")).toHaveLength(1));
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});

describe("the demo bar", () => {
  function renderBar() {
    return render(
      <DemoProvider settings={SETTINGS}>
        <DemoBar />
      </DemoProvider>,
    );
  }

  it("shows when the session and its data are deleted", async () => {
    fakeApi({ "GET /api/me": me(true) });
    renderBar();
    const expected = new Date(EXPIRES).toLocaleString(undefined, {
      weekday: "short",
      day: "numeric",
      month: "short",
      hour: "2-digit",
      minute: "2-digit",
    });
    expect(await screen.findByText(`Demo: your data is deleted at ${expected}`)).toBeInTheDocument();
  });

  it("lets the visitor read the notice again", async () => {
    fakeApi({ "GET /api/me": me(true), "GET /api/providers": json(200, providers) });
    renderBar();
    fireEvent.click(screen.getByRole("button", { name: "Demo notice" }));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText(NEBIUS_NOTICE)).toBeInTheDocument();
    expect(within(dialog).queryByRole("button", { name: "I accept" })).toBeNull();
  });

  it("asks before End demo deletes anything", async () => {
    const api = fakeApi({
      "GET /api/me": me(true),
      "DELETE /api/demo/session": new Response(null, { status: 204 }),
    });
    renderBar();

    fireEvent.click(screen.getByRole("button", { name: "End demo" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/deleted for good/)).toBeInTheDocument();
    expect(api.calls.some((c) => c.method === "DELETE")).toBe(false);

    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(api.calls.some((c) => c.method === "DELETE")).toBe(false);

    fireEvent.click(screen.getByRole("button", { name: "End demo" }));
    fireEvent.click(await screen.findByRole("button", { name: "End demo and delete" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/demo/ended"));
    expect(api.calls.filter((c) => c.method === "DELETE").map((c) => c.path)).toEqual(["/api/demo/session"]);
  });
});

describe("an expired demo session", () => {
  const expired = () => errorResponse(401, "demo_session_expired", "Your demo session has ended.");

  it("shows the expired page with a Start again button", async () => {
    fakeApi({ "GET /api/me": expired() });
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, origin: "http://localhost", assign });
    render(
      <DemoProvider settings={SETTINGS}>
        <p>the app</p>
      </DemoProvider>,
    );

    expect(await screen.findByText("Your demo session has ended")).toBeInTheDocument();
    expect(screen.queryByText("the app")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Start again" }));
    expect(String(assign.mock.calls[0][0])).toBe("http://localhost/app");
  });

  it("shows the page when any later call finds the session expired", async () => {
    fakeApi({ "GET /api/me": me(true), "GET /api/conversations": expired() });
    render(
      <DemoProvider settings={SETTINGS}>
        <p>the app</p>
      </DemoProvider>,
    );
    expect(await screen.findByText("the app")).toBeInTheDocument();

    await act(async () => {
      await apiFetch("/api/conversations").catch(() => undefined);
    });

    expect(await screen.findByText("Your demo session has ended")).toBeInTheDocument();
  });

  it("renders the app unchanged outside demo mode", async () => {
    render(
      <DemoProvider settings={null}>
        <p>the app</p>
      </DemoProvider>,
    );
    expect(screen.getByText("the app")).toBeInTheDocument();
  });
});
