import { describe, expect, it, vi } from "vitest";

import {
  MAX_COOKIE_VALUE_BYTES,
  SESSION_COOKIE,
  clearSessionCookies,
  readSession,
  seal,
  serializeCookie,
  sessionCookies,
  unseal,
  type Session,
} from "./session";

const SECRET = "0123456789abcdef0123456789abcdef";
const OTHER_SECRET = "fedcba9876543210fedcba9876543210";

const session = (idToken = "header.payload.signature"): Session => ({
  mode: "oidc",
  idToken,
  refreshToken: "refresh-token",
  expiresAt: Math.floor(Date.now() / 1000) + 3600,
});

/** A request that carries the cookies from Set-Cookie headers, as a browser would send them. */
function requestWith(setCookies: string[]): Request {
  const cookie = setCookies
    .map((header) => header.split(";")[0])
    .filter((pair) => !pair.endsWith("="))
    .join("; ");
  return new Request("http://localhost:3000/app", { headers: { cookie } });
}

const empty = () => new Request("http://localhost:3000/app");

describe("seal and unseal", () => {
  it("round-trips a value", async () => {
    const sealed = await seal({ a: 1, b: "two" }, SECRET, "session", 60);
    expect(await unseal(sealed, SECRET, "session")).toEqual({ a: 1, b: "two" });
  });

  it("does not show the value in the sealed text", async () => {
    const sealed = await seal({ token: "very-secret-token" }, SECRET, "session", 60);
    expect(sealed).not.toContain("very-secret-token");
    expect(Buffer.from(sealed.split(".")[3] ?? "", "base64url").toString()).not.toContain(
      "very-secret-token",
    );
  });

  it("refuses a tampered value", async () => {
    const sealed = await seal({ a: 1 }, SECRET, "session", 60);
    const parts = sealed.split(".");
    const ciphertext = Buffer.from(parts[3], "base64url");
    ciphertext[0] ^= 1;
    parts[3] = ciphertext.toString("base64url");
    expect(await unseal(parts.join("."), SECRET, "session")).toBeNull();
    expect(await unseal("not-a-jwe", SECRET, "session")).toBeNull();
  });

  it("refuses another secret or another purpose", async () => {
    const sealed = await seal({ a: 1 }, SECRET, "session", 60);
    expect(await unseal(sealed, OTHER_SECRET, "session")).toBeNull();
    expect(await unseal(sealed, SECRET, "login")).toBeNull();
  });

  it("refuses an expired value", async () => {
    vi.useFakeTimers();
    try {
      const sealed = await seal({ a: 1 }, SECRET, "login", 60);
      vi.advanceTimersByTime(61_000);
      expect(await unseal(sealed, SECRET, "login")).toBeNull();
    } finally {
      vi.useRealTimers();
    }
  });
});

describe("the session cookie", () => {
  it("round-trips through the Set-Cookie and Cookie headers", async () => {
    const headers = await sessionCookies(empty(), session(), SECRET);

    expect(headers).toHaveLength(1);
    expect(headers[0].startsWith(`${SESSION_COOKIE}=`)).toBe(true);
    expect(await readSession(requestWith(headers), SECRET)).toEqual(session());
  });

  it("is HttpOnly, Secure, and SameSite=Lax", async () => {
    const [header] = await sessionCookies(empty(), session(), SECRET);
    const attributes = header.split("; ").slice(1);
    expect(attributes).toEqual(expect.arrayContaining(["HttpOnly", "Secure", "SameSite=Lax", "Path=/"]));
    expect(serializeCookie("x", "y")).toContain("HttpOnly; Secure; SameSite=Lax");
  });

  it("refuses a tampered cookie", async () => {
    const [header] = await sessionCookies(empty(), session(), SECRET);
    const value = header.split(";")[0].split("=")[1];
    // Change one character of the ciphertext (the fourth part).
    const parts = value.split(".");
    const flipped = parts[3][0] === "A" ? "B" : "A";
    parts[3] = flipped + parts[3].slice(1);
    const tampered = parts.join(".");
    expect(tampered).not.toBe(value);
    const request = new Request("http://localhost:3000/", {
      headers: { cookie: `${SESSION_COOKIE}=${tampered}` },
    });
    expect(await readSession(request, SECRET)).toBeNull();
  });

  it("chunks a large token and restores it", async () => {
    const bigToken = "x".repeat(9000);
    const headers = await sessionCookies(empty(), session(bigToken), SECRET);

    expect(headers.length).toBeGreaterThan(2);
    expect(headers.map((h) => h.split("=")[0])).toEqual(
      headers.map((_, index) => `${SESSION_COOKIE}.${index}`),
    );
    for (const header of headers) {
      expect(header.split(";")[0].length).toBeLessThan(MAX_COOKIE_VALUE_BYTES + 100);
      expect(header).toContain("HttpOnly; Secure; SameSite=Lax");
    }
    expect((await readSession(requestWith(headers), SECRET))?.idToken).toBe(bigToken);
  });

  it("clears leftover chunks when a smaller session replaces a chunked one", async () => {
    const chunked = await sessionCookies(empty(), session("x".repeat(9000)), SECRET);
    const replaced = await sessionCookies(requestWith(chunked), session(), SECRET);

    expect(replaced[0].startsWith(`${SESSION_COOKIE}=`)).toBe(true);
    const cleared = replaced.slice(1);
    expect(cleared.length).toBe(chunked.length);
    for (const header of cleared) expect(header).toContain("Max-Age=0");
  });

  it("clears every part on logout", async () => {
    const chunked = await sessionCookies(empty(), session("x".repeat(9000)), SECRET);
    const cleared = clearSessionCookies(requestWith(chunked));
    expect(cleared.map((h) => h.split("=")[0]).sort()).toEqual(
      [SESSION_COOKIE, ...chunked.map((h) => h.split("=")[0])].sort(),
    );
    for (const header of cleared) expect(header).toContain("Max-Age=0");
  });
});
