// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const sdk = vi.hoisted(() => ({
  initializeApp: vi.fn(() => ({ name: "app" })),
  deleteApp: vi.fn(async () => undefined),
  initializeAuth: vi.fn(() => ({ name: "auth" })),
  signInWithPopup: vi.fn(),
  signInWithEmailAndPassword: vi.fn(),
  signOut: vi.fn(async () => undefined),
  GoogleAuthProvider: vi.fn(),
  inMemoryPersistence: { type: "NONE" },
  browserPopupRedirectResolver: {},
}));

vi.mock("firebase/app", () => ({ initializeApp: sdk.initializeApp, deleteApp: sdk.deleteApp }));
vi.mock("firebase/auth", () => sdk);

const assign = vi.fn();
vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: assign }) }));

import { FirebaseLogin } from "./firebase-login";

const CONFIG = { apiKey: "web-key", authDomain: "p.firebaseapp.com", projectId: "p" };
const user = {
  getIdToken: vi.fn(async () => "firebase-id-token"),
  refreshToken: "firebase-refresh-token",
};

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockResolvedValue(Response.json({ redirect: "/app/abc" }));
  sdk.signInWithPopup.mockResolvedValue({ user });
  sdk.signInWithEmailAndPassword.mockResolvedValue({ user });
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

function postedBody() {
  expect(fetchMock).toHaveBeenCalledTimes(1);
  const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
  expect(url).toBe("/auth/firebase/session");
  expect(init.method).toBe("POST");
  return JSON.parse(init.body as string);
}

describe("FirebaseLogin", () => {
  it("uses in-memory persistence", async () => {
    render(<FirebaseLogin firebaseConfig={CONFIG} returnTo="/app/abc" />);
    fireEvent.click(screen.getByRole("button", { name: "Continue with Google" }));

    await waitFor(() => expect(sdk.signOut).toHaveBeenCalled());
    expect(sdk.initializeApp).toHaveBeenCalledWith(CONFIG, expect.any(String));
    expect(sdk.initializeAuth).toHaveBeenCalledWith(
      expect.anything(),
      expect.objectContaining({ persistence: sdk.inMemoryPersistence }),
    );
  });

  it("posts the tokens after Google sign-in, signs out, and goes to returnTo", async () => {
    render(<FirebaseLogin firebaseConfig={CONFIG} returnTo="/app/abc" />);
    fireEvent.click(screen.getByRole("button", { name: "Continue with Google" }));

    await waitFor(() => expect(assign).toHaveBeenCalledWith("/app/abc"));
    expect(postedBody()).toEqual({
      idToken: "firebase-id-token",
      refreshToken: "firebase-refresh-token",
      returnTo: "/app/abc",
    });
    expect(sdk.signOut).toHaveBeenCalledTimes(1);
    expect(sdk.signOut.mock.invocationCallOrder[0]).toBeGreaterThan(
      fetchMock.mock.invocationCallOrder[0],
    );
  });

  it("posts the tokens after email-and-password sign-in", async () => {
    render(<FirebaseLogin firebaseConfig={CONFIG} returnTo="/app" />);
    fireEvent.change(screen.getByLabelText("Email"), { target: { value: " ana@example.org " } });
    fireEvent.change(screen.getByLabelText("Password"), { target: { value: "pw-123456" } });
    fireEvent.click(screen.getByRole("button", { name: "Log in with email" }));

    await waitFor(() => expect(sdk.signOut).toHaveBeenCalled());
    expect(sdk.signInWithEmailAndPassword).toHaveBeenCalledWith(
      expect.anything(),
      "ana@example.org",
      "pw-123456",
    );
    expect(postedBody().idToken).toBe("firebase-id-token");
  });

  it("writes nothing to local or session storage", async () => {
    const setItem = vi.spyOn(Storage.prototype, "setItem");
    render(<FirebaseLogin firebaseConfig={CONFIG} returnTo="/app" />);
    fireEvent.click(screen.getByRole("button", { name: "Continue with Google" }));

    await waitFor(() => expect(assign).toHaveBeenCalled());
    expect(setItem).not.toHaveBeenCalled();
    expect(localStorage.length).toBe(0);
    expect(sessionStorage.length).toBe(0);
    expect(document.cookie).not.toContain("firebase-id-token");
  });

  it("signs out and shows that the login did not complete when the server refuses", async () => {
    fetchMock.mockResolvedValue(
      Response.json({ error: { code: "unauthenticated", message: "no" } }, { status: 401 }),
    );
    render(<FirebaseLogin firebaseConfig={CONFIG} returnTo="/app" />);
    fireEvent.click(screen.getByRole("button", { name: "Continue with Google" }));

    expect(await screen.findByText("The login did not complete. Try again.")).toBeInTheDocument();
    expect(sdk.signOut).toHaveBeenCalled();
    expect(assign).not.toHaveBeenCalled();
  });

  it("sends a refused account to the not-allowed page", async () => {
    fetchMock.mockResolvedValue(
      Response.json({ error: { code: "not_allowed", message: "no" } }, { status: 403 }),
    );
    render(<FirebaseLogin firebaseConfig={CONFIG} returnTo="/app" />);
    fireEvent.click(screen.getByRole("button", { name: "Continue with Google" }));

    await waitFor(() => expect(assign).toHaveBeenCalledWith("/auth/not-allowed"));
    expect(sdk.signOut).toHaveBeenCalled();
  });

  it("signs out even when sign-in fails", async () => {
    sdk.signInWithPopup.mockRejectedValue(new Error("auth/popup-closed-by-user"));
    render(<FirebaseLogin firebaseConfig={CONFIG} returnTo="/app" />);
    fireEvent.click(screen.getByRole("button", { name: "Continue with Google" }));

    expect(await screen.findByText("The login did not complete. Try again.")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
    expect(sdk.signOut).toHaveBeenCalled();
  });
});
