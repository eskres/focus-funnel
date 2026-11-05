// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { connectorsListing, errorResponse, fakeApi, json, wireConnector } from "@/test/fake-api";

import SettingsPage from "./page";

// Outside demo mode; the page reads the mode per request on the server.
vi.mock("@/lib/demo-settings", () => ({ demoSettings: async () => null }));
vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

// The other sections' requests are not routed: they show their own load errors.
async function renderPage(connectors: Response) {
  const api = fakeApi({ "GET /api/connectors": connectors });
  render(await SettingsPage());
  await screen.findByRole("heading", { name: "Settings" });
  await waitFor(() => expect(api.calls.some((c) => c.path === "/api/connectors")).toBe(true));
  return api;
}

describe("Settings page", () => {
  it("shows no Connectors section when GET /api/connectors responds 404", async () => {
    await renderPage(errorResponse(404, "not_found", "Not found."));

    // Let the failed listing settle before looking.
    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByRole("heading", { name: "Connectors" })).toBeNull();
    expect(screen.queryByText(/Connectors let the chat/)).toBeNull();
    expect(screen.getByText("Your data")).toBeInTheDocument();
  });

  it("shows the Connectors section when connectors are on", async () => {
    await renderPage(json(200, connectorsListing([wireConnector("c1", "calendar")])));

    expect(await screen.findByRole("heading", { name: "Connectors" })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "calendar" })).toBeInTheDocument();
  });
});
