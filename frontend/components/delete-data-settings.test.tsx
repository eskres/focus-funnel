// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DeleteDataSection } from "@/components/delete-data-settings";
import { DemoProvider } from "@/components/demo/demo-context";
import { USAGE_DELETED, logOut } from "@/lib/account";
import { errorResponse, fakeApi, json } from "@/test/fake-api";

vi.mock("@/lib/account", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/account")>()),
  logOut: vi.fn(),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

const deleted = () => new Response(null, { status: 204 });

function openDialog(label: string) {
  fireEvent.click(screen.getByRole("button", { name: label }));
  return screen.getByRole("dialog");
}

describe("Your data", () => {
  it("offers content, usage history, and account as separate choices", () => {
    fakeApi({});
    render(<DeleteDataSection />);

    for (const label of ["Delete content", "Delete usage history", "Delete account"]) {
      expect(screen.getByRole("button", { name: label })).toBeInTheDocument();
    }
  });

  it("says what is deleted and does nothing on cancel", () => {
    const api = fakeApi({});
    render(<DeleteDataSection />);

    const dialog = openDialog("Delete account");
    expect(within(dialog).getByText(/filed thoughts and their search index/)).toBeInTheDocument();
    expect(within(dialog).getByText(/cannot be undone/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(api.calls).toHaveLength(0);
    expect(logOut).not.toHaveBeenCalled();
  });

  it("deletes the content and stays logged in", async () => {
    const api = fakeApi({ "DELETE /api/me/content": deleted() });
    render(<DeleteDataSection />);

    const dialog = openDialog("Delete content");
    expect(within(dialog).getByText(/usage history stay/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete content" }));

    expect(await within(dialog).findByRole("button", { name: "Deleted" })).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull(), { timeout: 2000 });
    expect(screen.queryByRole("status")).toBeNull();
    expect(api.calls.map((call) => `${call.method} ${call.path}`)).toEqual(["DELETE /api/me/content"]);
    expect(logOut).not.toHaveBeenCalled();
  });

  it("deletes the usage history, tells the usage section, and stays logged in", async () => {
    const api = fakeApi({ "DELETE /api/me/usage": deleted() });
    const heard = vi.fn();
    window.addEventListener(USAGE_DELETED, heard);
    render(<DeleteDataSection />);

    fireEvent.click(
      within(openDialog("Delete usage history")).getByRole("button", { name: "Delete usage history" }),
    );

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull(), { timeout: 2000 });
    expect(api.calls.map((call) => `${call.method} ${call.path}`)).toEqual(["DELETE /api/me/usage"]);
    expect(heard).toHaveBeenCalledTimes(1);
    expect(logOut).not.toHaveBeenCalled();
    window.removeEventListener(USAGE_DELETED, heard);
  });

  it("deletes the account with a spinner, then a tick, then logs out", async () => {
    let answer!: (response: Response) => void;
    const api = fakeApi({ "DELETE /api/me": () => new Promise<Response>((resolve) => (answer = resolve)) });
    render(<DeleteDataSection />);

    const dialog = openDialog("Delete account");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete account" }));

    const spinner = await within(dialog).findByRole("button", { name: "Deleting…" });
    expect(spinner).toBeDisabled();
    expect(spinner).toHaveClass("bg-amber-600/10");
    answer(deleted());
    const tick = await within(dialog).findByRole("button", { name: "Deleted" });
    expect(tick).toHaveClass("bg-green-600/10");
    expect(logOut).not.toHaveBeenCalled();

    await waitFor(() => expect(logOut).toHaveBeenCalledTimes(1), { timeout: 2000 });
    expect(api.calls.map((call) => `${call.method} ${call.path}`)).toEqual(["DELETE /api/me"]);
  });

  it("keeps the user on the page with the error", async () => {
    fakeApi({ "DELETE /api/me": errorResponse(503, "service_unavailable", "The database is down.") });
    render(<DeleteDataSection />);

    const dialog = openDialog("Delete account");
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete account" }));

    expect(await within(dialog).findByText("The database is down.")).toBeInTheDocument();
    expect(logOut).not.toHaveBeenCalled();
    expect(within(dialog).getByRole("button", { name: "Delete account" })).toBeEnabled();
  });

  it("is not offered in demo mode", async () => {
    const api = fakeApi({
      "GET /api/me": json(200, { id: "u1", mode: "demo", expires_at: "2026-09-25T12:00:00Z" }),
    });
    render(
      <DemoProvider settings={{ keyTtlMinutes: 30, keyMaxHours: 4 }}>
        <DeleteDataSection />
      </DemoProvider>,
    );

    await waitFor(() => expect(api.calls.some((call) => call.path === "/api/me")).toBe(true));
    expect(screen.queryByRole("button", { name: /Delete/ })).toBeNull();
  });
});
