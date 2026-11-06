// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DemoProvider } from "@/components/demo/demo-context";
import { EXPORT_NOT_STARTED, ExportSection } from "@/components/export-settings";
import { DEMO_EXPIRED_EVENT } from "@/lib/api";
import { redirectToLogin } from "@/lib/redirect-to-login";
import { fakeApi, json } from "@/test/fake-api";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

const RUNNING = "An export in this format is already running. Try again when it has finished.";
const runningBody = JSON.stringify({ error: { code: "export_running", message: RUNNING } });

function frames(): HTMLIFrameElement[] {
  return Array.from(document.querySelectorAll("iframe"));
}

function press(label: string) {
  fireEvent.click(screen.getByRole("button", { name: label }));
}

/** Fills a frame's document as a refusal would, then fires its `load`. */
function loadFrame(frame: HTMLIFrameElement, html: string) {
  // jsdom loads no frame source, so the frame starts with an empty document.
  const doc = frame.contentDocument!;
  const root = doc.documentElement ?? doc.appendChild(doc.createElement("html"));
  root.innerHTML = `<head></head><body>${html}</body>`;
  fireEvent.load(frame);
}

function renderSection() {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  const view = render(<ExportSection />);
  return { fetchMock, ...view };
}

describe("Export", () => {
  it("shows its title, text, and both buttons", () => {
    renderSection();

    expect(screen.getByRole("heading", { name: "Export" })).toBeInTheDocument();
    expect(
      screen.getByText(
        "Download all your thoughts with their dates, status, tags, category, summary, raw text, where they came from, and their additions.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download JSON" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Download Markdown" })).toBeInTheDocument();
    expect(frames()).toHaveLength(0);
  });

  it("downloads each format through a hidden frame, with no fetch", () => {
    const { fetchMock } = renderSection();

    press("Download JSON");
    expect(frames()).toHaveLength(1);
    expect(frames()[0]).toHaveAttribute("src", "/api/me/export?format=json");
    expect(frames()[0].hidden).toBe(true);

    press("Download Markdown");
    expect(frames()).toHaveLength(2);
    expect(frames()[1]).toHaveAttribute("src", "/api/me/export?format=markdown");
    expect(frames()[1].hidden).toBe(true);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("keeps every earlier frame as it is and adds one per press", () => {
    renderSection();

    press("Download JSON");
    const first = frames()[0];
    press("Download JSON");
    expect(frames()).toHaveLength(2);
    expect(frames()[0]).toBe(first);
    expect(first).toBeInTheDocument();
    expect(first).toHaveAttribute("src", "/api/me/export?format=json");
    expect(frames()[1]).not.toBe(first);
    expect(frames()[1]).toHaveAttribute("src", "/api/me/export?format=json");

    const second = frames()[1];
    press("Download Markdown");
    expect(frames()).toHaveLength(3);
    expect(frames()[0]).toBe(first);
    expect(frames()[1]).toBe(second);
    expect(first).toHaveAttribute("src", "/api/me/export?format=json");
    expect(second).toHaveAttribute("src", "/api/me/export?format=json");
    expect(frames()[2]).toHaveAttribute("src", "/api/me/export?format=markdown");
  });

  it("removes every frame when the section unmounts", () => {
    const { unmount } = renderSection();
    press("Download JSON");
    press("Download Markdown");
    press("Download JSON");
    expect(frames()).toHaveLength(3);

    unmount();
    expect(frames()).toHaveLength(0);
  });

  it("shows a refusal's message from the frame's body", async () => {
    renderSection();
    press("Download JSON");

    loadFrame(frames()[0], runningBody);

    expect(await screen.findByRole("alert")).toHaveTextContent(RUNNING);
  });

  it("reads the refusal from a pre with other text beside it", async () => {
    renderSection();
    press("Download JSON");

    loadFrame(
      frames()[0],
      `<div>Raw · Pretty print</div><pre>${runningBody}</pre><p>More viewer text</p>`,
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(RUNNING);
    expect(alert).not.toHaveTextContent("Pretty print");
  });

  it("shows that the demo session ended for demo_session_expired", async () => {
    renderSection();
    const heard = vi.fn();
    window.addEventListener(DEMO_EXPIRED_EVENT, heard);
    try {
      press("Download JSON");
      loadFrame(
        frames()[0],
        JSON.stringify({
          error: { code: "demo_session_expired", message: "Your demo session has ended." },
        }),
      );
      await waitFor(() => expect(heard).toHaveBeenCalledTimes(1));
    } finally {
      window.removeEventListener(DEMO_EXPIRED_EVENT, heard);
    }
  });

  it("sends a logged-out user to log in, with no alert", async () => {
    renderSection();
    press("Download Markdown");

    loadFrame(
      frames()[0],
      JSON.stringify({ error: { code: "unauthenticated", message: "Log in again." } }),
    );

    await waitFor(() => expect(redirectToLogin).toHaveBeenCalledWith("/settings"));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("says the export could not start for text that is not JSON", async () => {
    renderSection();
    press("Download JSON");

    loadFrame(frames()[0], "<h1>Something went wrong</h1>");

    expect(await screen.findByRole("alert")).toHaveTextContent(EXPORT_NOT_STARTED);
    expect(EXPORT_NOT_STARTED).toBe("The export could not start. Try again.");
  });

  it("ignores a load with an empty body", async () => {
    renderSection();
    press("Download JSON");

    loadFrame(frames()[0], "");
    loadFrame(frames()[0], "  \n ");

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("ignores a load whose document throws on reading", async () => {
    renderSection();
    press("Download JSON");

    Object.defineProperty(frames()[0], "contentDocument", {
      get() {
        throw new DOMException("Blocked a frame from accessing a cross-origin frame.", "SecurityError");
      },
    });
    fireEvent.load(frames()[0]);

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("ignores a load whose document is null", async () => {
    renderSection();
    press("Download JSON");

    Object.defineProperty(frames()[0], "contentDocument", { value: null });
    fireEvent.load(frames()[0]);

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("clears an earlier alert on a new press", async () => {
    renderSection();
    press("Download JSON");
    loadFrame(frames()[0], runningBody);
    expect(await screen.findByRole("alert")).toHaveTextContent(RUNNING);

    press("Download Markdown");

    expect(screen.queryByRole("alert")).toBeNull();
    expect(frames()).toHaveLength(2);
  });

  it("renders the same inside DemoProvider with demo settings", async () => {
    const api = fakeApi({
      "GET /api/me": json(200, { id: "u1", mode: "demo", expires_at: "2026-09-25T12:00:00Z" }),
    });
    render(
      <DemoProvider settings={{ keyTtlMinutes: 30, keyMaxHours: 4 }}>
        <ExportSection />
      </DemoProvider>,
    );

    await waitFor(() => expect(api.calls.some((call) => call.path === "/api/me")).toBe(true));
    expect(screen.getByRole("heading", { name: "Export" })).toBeInTheDocument();
    expect(screen.getByText(/Download all your thoughts with their dates/)).toBeInTheDocument();
    press("Download JSON");
    press("Download Markdown");
    expect(frames().map((frame) => frame.getAttribute("src"))).toEqual([
      "/api/me/export?format=json",
      "/api/me/export?format=markdown",
    ]);
    expect(api.calls.map((call) => call.path)).toEqual(["/api/me"]);
  });
});
