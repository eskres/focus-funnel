// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiKeySettings } from "./api-key-settings";

type Reply = { status: number; body?: unknown };

function json({ status, body }: Reply) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

// Replies to each fetch call in order and records the requests.
function mockApi(...replies: Reply[]) {
  const fetchMock = vi.fn(async () => json(replies.shift()!));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const saved = { saved: true, last4: "wxyz", saved_at: "2026-09-01T12:00:00Z" };

async function submitKey(value: string) {
  fireEvent.change(await screen.findByPlaceholderText("Paste your Nebius API key"), {
    target: { value },
  });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ApiKeySettings", () => {
  it("shows the no-key state with an input and saves a valid key", async () => {
    const fetchMock = mockApi(
      { status: 200, body: { saved: false } },
      { status: 200, body: { saved: true, last4: "abcd", saved_at: "2026-09-15T08:00:00Z" } },
    );
    render(<ApiKeySettings />);

    expect(await screen.findByText("No API key saved.")).toBeInTheDocument();
    await submitKey("nebius-key-abcd");

    expect(await screen.findByText("abcd")).toBeInTheDocument();
    expect(screen.queryByPlaceholderText("Paste your Nebius API key")).toBeNull();
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/settings/api-key",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ api_key: "nebius-key-abcd" }),
      }),
    );
  });

  it("shows last4 and the save date for a saved key", async () => {
    mockApi({ status: 200, body: saved });
    render(<ApiKeySettings />);

    expect(await screen.findByText("wxyz")).toBeInTheDocument();
    const expectedDate = new Date(saved.saved_at).toLocaleDateString(undefined, {
      dateStyle: "medium",
    });
    expect(screen.getByText(new RegExp(`saved on ${expectedDate}`))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Replace" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Delete" })).toBeInTheDocument();
  });

  it.each([
    ["nebius_key_invalid", 400, "Nebius rejected this API key."],
    ["nebius_unreachable", 502, "The key could not be checked because Nebius did not respond. Try again."],
    ["validation_error", 422, "Enter an API key."],
  ])("shows the %s message", async (code, status, message) => {
    mockApi(
      { status: 200, body: { saved: false } },
      { status, body: { error: { code, message: "backend text" } } },
    );
    render(<ApiKeySettings />);

    await submitKey("some-key");

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
  });

  it("does not send an empty or whitespace-only key", async () => {
    const fetchMock = mockApi({ status: 200, body: { saved: false } });
    render(<ApiKeySettings />);

    await submitKey("   ");

    expect(await screen.findByRole("alert")).toHaveTextContent("Enter an API key.");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("keeps showing the old key when a replacement is rejected", async () => {
    mockApi(
      { status: 200, body: saved },
      { status: 400, body: { error: { code: "nebius_key_invalid", message: "x" } } },
    );
    render(<ApiKeySettings />);

    fireEvent.click(await screen.findByRole("button", { name: "Replace" }));
    await submitKey("fake-key");

    expect(await screen.findByRole("alert")).toHaveTextContent("Nebius rejected this API key.");
    expect(screen.getByText("wxyz")).toBeInTheDocument();
  });

  it("deletes the key and returns to the no-key state", async () => {
    const fetchMock = mockApi({ status: 200, body: saved }, { status: 204 });
    render(<ApiKeySettings />);

    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));

    expect(await screen.findByText("No API key saved.")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Paste your Nebius API key")).toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenLastCalledWith(
        "/api/settings/api-key",
        expect.objectContaining({ method: "DELETE" }),
      ),
    );
  });
});
