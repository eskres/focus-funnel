// @vitest-environment jsdom
import { render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

const { FirebaseLogin } = vi.hoisted(() => ({
  FirebaseLogin: vi.fn<(props: { returnTo: string }) => null>(() => null),
}));

vi.mock("@/components/firebase-login", () => ({ FirebaseLogin }));
vi.mock("@/lib/auth-mode", () => ({
  getAuthConfig: () => ({
    mode: "firebase",
    firebase: { apiKey: "web-key", authDomain: "p.firebaseapp.com", projectId: "p" },
  }),
}));
vi.mock("next/navigation", () => ({
  redirect: vi.fn(() => {
    throw new Error("redirect is not expected in firebase mode");
  }),
}));

import LoginPage from "./page";

afterEach(() => {
  vi.clearAllMocks();
});

async function renderWith(returnTo: string) {
  render(await LoginPage({ searchParams: Promise.resolve({ returnTo }) }));
  expect(FirebaseLogin).toHaveBeenCalled();
  return FirebaseLogin.mock.calls[0][0].returnTo;
}

describe("the Firebase login page (thought-export task 4.3)", () => {
  it.each(["/api/me/export?format=json", "/settings/../api/me/export?format=json"])(
    "passes /app as the destination for returnTo=%s",
    async (returnTo) => {
      expect(await renderWith(returnTo)).toBe("/app");
    },
  );

  it("passes a page to return to through", async () => {
    expect(await renderWith("/settings?tab=x")).toBe("/settings?tab=x");
  });
});
