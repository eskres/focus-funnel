// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ProvidersSettings } from "./providers-settings";

type Reply = { status: number; body?: unknown };

function json({ status, body }: Reply) {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

const nebius = {
  id: "nebius",
  label: "Nebius Token Factory",
  key_url: "https://tokenfactory.nebius.com/project/api-keys",
  notice: "Nebius does not use your prompts to train models.",
  key_required: true,
  is_custom: false,
  key_saved: false,
};

const nvidia = {
  id: "nvidia",
  label: "NVIDIA",
  key_url: "https://build.nvidia.com/settings/api-keys",
  notice: "NVIDIA logs API calls.",
  key_required: true,
  is_custom: false,
  key_saved: false,
};

const custom = {
  id: "custom",
  label: "Custom provider",
  key_url: "",
  notice: "This is a custom endpoint you supplied.",
  key_required: false,
  is_custom: true,
  key_saved: false,
};

function listResponse(providers: unknown[], customProviderAllowed = true): Reply {
  return {
    status: 200,
    body: { providers, custom_provider_allowed: customProviderAllowed },
  };
}

// Routes fetch calls by method + path prefix, in the order given. Each
// matcher is consumed once its predicate matches, so calls that don't need
// to be order-sensitive can still be asserted against directly.
function mockApi(...replies: Reply[]) {
  const queue = [...replies];
  const fetchMock = vi.fn(async () => json(queue.shift()!));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ProvidersSettings", () => {
  it("renders a card for every preset with its key link and notice", async () => {
    mockApi(listResponse([nebius, nvidia]));
    render(<ProvidersSettings />);

    expect(await screen.findByText("Nebius Token Factory")).toBeInTheDocument();
    expect(screen.getByText("NVIDIA")).toBeInTheDocument();
    expect(
      screen.getAllByRole("link", { name: "Get a key" }).map((a) => a.getAttribute("href")),
    ).toEqual([nebius.key_url, nvidia.key_url]);
  });

  it("saving sends the key to that provider's endpoint", async () => {
    const fetchMock = mockApi(
      listResponse([nebius]),
      { status: 200, body: { ...nebius, key_saved: true, key_last4: "abcd", key_saved_at: "2026-09-15T08:00:00Z" } },
    );
    render(<ProvidersSettings />);

    fireEvent.click(await screen.findByRole("button", { name: "Read data-handling notice" }));
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.change(screen.getByPlaceholderText("Paste your Nebius Token Factory API key"), {
      target: { value: "nb-secret-abcd" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("abcd")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenLastCalledWith(
      "/api/providers/nebius/key",
      expect.objectContaining({
        method: "PUT",
        body: JSON.stringify({ key: "nb-secret-abcd" }),
      }),
    );
  });

  it("shows a saved key's last 4 characters and date", async () => {
    mockApi(
      listResponse([
        { ...nebius, key_saved: true, key_last4: "wxyz", key_saved_at: "2026-09-01T12:00:00Z" },
      ]),
    );
    render(<ProvidersSettings />);

    expect(await screen.findByText("wxyz")).toBeInTheDocument();
    const expectedDate = new Date("2026-09-01T12:00:00Z").toLocaleDateString(undefined, {
      dateStyle: "medium",
    });
    expect(screen.getByText(new RegExp(`saved on ${expectedDate}`))).toBeInTheDocument();
  });

  it("a refused key shows its reason and keeps the earlier state", async () => {
    mockApi(
      listResponse([
        { ...nebius, key_saved: true, key_last4: "wxyz", key_saved_at: "2026-09-01T12:00:00Z" },
      ]),
      { status: 400, body: { error: { code: "provider_key_invalid", message: "Nebius rejected this API key." } } },
    );
    render(<ProvidersSettings />);

    fireEvent.click(await screen.findByRole("button", { name: "Replace" }));
    fireEvent.change(screen.getByPlaceholderText("Paste your Nebius Token Factory API key"), {
      target: { value: "bad-key" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Nebius rejected this API key.");
    expect(screen.getByText("wxyz")).toBeInTheDocument();
  });

  it("does not send an empty key for a provider that needs one", async () => {
    const fetchMock = mockApi(listResponse([nebius]));
    render(<ProvidersSettings />);

    fireEvent.click(
      await screen.findByRole("button", { name: "Save" }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent("Enter an API key.");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("deletes the key and returns to the no-key state", async () => {
    const fetchMock = mockApi(
      listResponse([
        { ...nebius, key_saved: true, key_last4: "wxyz", key_saved_at: "2026-09-01T12:00:00Z" },
      ]),
      { status: 204 },
    );
    render(<ProvidersSettings />);

    fireEvent.click(await screen.findByRole("button", { name: "Delete" }));

    expect(await screen.findByText("No API key saved.")).toBeInTheDocument();
    await waitFor(() =>
      expect(fetchMock).toHaveBeenLastCalledWith(
        "/api/providers/nebius/key",
        expect.objectContaining({ method: "DELETE" }),
      ),
    );
  });

  // --- 7.3: data-handling notice ---

  it("blocks saving until the notice is accepted, for a provider's first key", async () => {
    const fetchMock = mockApi(listResponse([nebius]));
    render(<ProvidersSettings />);

    fireEvent.change(await screen.findByPlaceholderText("Paste your Nebius Token Factory API key"), {
      target: { value: "nb-secret-abcd" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Read the notice above before saving a key.",
    );
    // Only the initial GET has happened; the PUT was blocked client-side.
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("saves once the notice is accepted", async () => {
    const fetchMock = mockApi(
      listResponse([nebius]),
      { status: 200, body: { ...nebius, key_saved: true, key_last4: "abcd", key_saved_at: "2026-09-15T08:00:00Z" } },
    );
    render(<ProvidersSettings />);

    fireEvent.click(await screen.findByRole("button", { name: "Read data-handling notice" }));
    expect(screen.getByText(nebius.notice)).toBeInTheDocument();

    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.change(screen.getByPlaceholderText("Paste your Nebius Token Factory API key"), {
      target: { value: "nb-secret-abcd" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(await screen.findByText("abcd")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("the notice stays readable after a key is saved", async () => {
    mockApi(
      listResponse([
        { ...nebius, key_saved: true, key_last4: "wxyz", key_saved_at: "2026-09-01T12:00:00Z" },
      ]),
    );
    render(<ProvidersSettings />);

    fireEvent.click(await screen.findByRole("button", { name: "Read data-handling notice" }));
    expect(screen.getByText(nebius.notice)).toBeInTheDocument();
  });

  // --- 7.4: custom provider card ---

  it("shows a base URL field for the custom provider and sends it", async () => {
    const fetchMock = mockApi(
      listResponse([custom]),
      {
        status: 200,
        body: { ...custom, key_saved: false, base_url: "http://localhost:11434/v1/" },
      },
    );
    render(<ProvidersSettings />);

    fireEvent.click(await screen.findByRole("button", { name: "Read data-handling notice" }));
    fireEvent.click(screen.getByRole("checkbox"));
    fireEvent.change(screen.getByPlaceholderText("http://localhost:11434/v1"), {
      target: { value: "http://localhost:11434/v1/" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(fetchMock).toHaveBeenLastCalledWith(
        "/api/providers/custom/key",
        expect.objectContaining({
          method: "PUT",
          body: JSON.stringify({ key: "", base_url: "http://localhost:11434/v1/" }),
        }),
      ),
    );
  });

  it("tells the user to include /v1 and to use host.docker.internal from Docker", async () => {
    mockApi(listResponse([custom]));
    render(<ProvidersSettings />);

    fireEvent.click(await screen.findByRole("button", { name: "Read data-handling notice" }));

    expect(screen.getByText(/include the \/v1 path/i)).toBeInTheDocument();
    expect(screen.getByText(/host\.docker\.internal/)).toBeInTheDocument();
  });

  it("hides the custom provider card when the server says custom is off", async () => {
    mockApi(listResponse([nebius], false));
    render(<ProvidersSettings />);

    await screen.findByText("Nebius Token Factory");
    expect(screen.queryByText("Custom provider")).toBeNull();
  });
});
