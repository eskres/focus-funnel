// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DeleteDataSection } from "@/components/delete-data-settings";
import { DemoProvider } from "@/components/demo/demo-context";
import { logOut } from "@/lib/account";
import { errorResponse, fakeApi, json } from "@/test/fake-api";

vi.mock("@/lib/account", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/account")>()),
  logOut: vi.fn(),
}));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

function openDialog() {
  fireEvent.click(screen.getByRole("button", { name: "Delete my data" }));
  return screen.getByRole("dialog");
}

describe("Delete my data", () => {
  it("says what is deleted and does nothing on cancel", () => {
    const api = fakeApi({});
    render(<DeleteDataSection />);

    const dialog = openDialog();
    expect(within(dialog).getByText(/filed thoughts and their search index/)).toBeInTheDocument();
    expect(within(dialog).getByText(/cannot be undone/)).toBeInTheDocument();
    fireEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));

    expect(api.calls).toHaveLength(0);
    expect(logOut).not.toHaveBeenCalled();
  });

  it("deletes, then logs out", async () => {
    const api = fakeApi({ "DELETE /api/me": new Response(null, { status: 204 }) });
    render(<DeleteDataSection />);

    fireEvent.click(within(openDialog()).getByRole("button", { name: "Delete everything" }));

    await waitFor(() => expect(logOut).toHaveBeenCalledTimes(1));
    expect(api.calls.map((call) => `${call.method} ${call.path}`)).toEqual(["DELETE /api/me"]);
  });

  it("keeps the user on the page with the error", async () => {
    fakeApi({ "DELETE /api/me": errorResponse(503, "service_unavailable", "The database is down.") });
    render(<DeleteDataSection />);

    const dialog = openDialog();
    fireEvent.click(within(dialog).getByRole("button", { name: "Delete everything" }));

    expect(await within(dialog).findByText("The database is down.")).toBeInTheDocument();
    expect(logOut).not.toHaveBeenCalled();
    expect(within(dialog).getByRole("button", { name: "Delete everything" })).toBeEnabled();
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
    expect(screen.queryByRole("button", { name: "Delete my data" })).toBeNull();
  });
});
