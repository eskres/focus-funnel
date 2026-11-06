// @vitest-environment jsdom
import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { connectorsListing, errorResponse, fakeApi, json, wireConnector } from "@/test/fake-api";

import SettingsPage from "./page";

// The page reads the mode per request on the server: outside demo mode unless a test sets it.
const mode = vi.hoisted(() => ({
  demo: null as { keyTtlMinutes: number; keyMaxHours: number } | null,
}));
vi.mock("@/lib/demo-settings", () => ({ demoSettings: async () => mode.demo }));
vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));
// The demo bar in the header uses the router; nothing here navigates.
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), refresh: vi.fn() }),
  usePathname: () => "/settings",
}));

afterEach(() => {
  mode.demo = null;
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

  it("puts Export directly above Your data", async () => {
    await renderPage(errorResponse(404, "not_found", "Not found."));

    const exportHeading = screen.getByRole("heading", { name: "Export" });
    const yourData = screen.getByText("Your data");
    expect(
      exportHeading.compareDocumentPosition(yourData) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    // Nothing else sits between them: the next card is "Your data".
    const exportCard = exportHeading.closest("[data-slot=card]");
    expect(exportCard?.nextElementSibling?.contains(yourData)).toBe(true);
  });

  it("offers Export and none of the delete choices in demo mode", async () => {
    mode.demo = { keyTtlMinutes: 30, keyMaxHours: 4 };
    const api = fakeApi({
      "GET /api/me": json(200, { id: "u1", mode: "demo", expires_at: "2026-09-25T12:00:00Z" }),
      "GET /api/connectors": errorResponse(404, "not_found", "Not found."),
    });
    render(await SettingsPage());

    await waitFor(() => expect(api.calls.some((c) => c.path === "/api/me")).toBe(true));
    expect(await screen.findByRole("heading", { name: "Export" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download JSON" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download Markdown" })).toBeInTheDocument();
    for (const label of ["Delete content", "Delete usage history", "Delete account"]) {
      expect(screen.queryByRole("button", { name: label })).toBeNull();
      expect(screen.queryByText(label)).toBeNull();
    }
    expect(screen.queryByText("Your data")).toBeNull();
  });
});
