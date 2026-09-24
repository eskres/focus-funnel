import { describe, expect, it } from "vitest";

import { RateLimiter, SHARED_CLIENT, clientAddress } from "./rate-limit";

describe("RateLimiter", () => {
  it("allows the capacity, then refuses with the wait until the next token", () => {
    const limiter = new RateLimiter(60, 60_000);
    for (let i = 0; i < 60; i++) expect(limiter.take("a", 0).allowed).toBe(true);
    expect(limiter.take("a", 0)).toEqual({ allowed: false, retryAfterSeconds: 1 });
    expect(limiter.take("b", 0).allowed).toBe(true);
  });

  it("refills evenly over the window", () => {
    const limiter = new RateLimiter(5, 3_600_000);
    for (let i = 0; i < 5; i++) limiter.take("a", 0);
    const refused = limiter.take("a", 0);
    expect(refused).toEqual({ allowed: false, retryAfterSeconds: 720 });
    expect(limiter.take("a", 720_000).allowed).toBe(true);
    expect(limiter.take("a", 720_000).allowed).toBe(false);
  });
});

describe("clientAddress", () => {
  const withHeader = (value?: string) =>
    new Request("http://localhost/", value ? { headers: { "x-forwarded-for": value } } : {});

  it("shares one bucket without a trusted proxy", () => {
    expect(clientAddress(withHeader("1.2.3.4"), false)).toBe(SHARED_CLIENT);
  });

  it("uses the last hop with a trusted proxy", () => {
    expect(clientAddress(withHeader("9.9.9.9, 1.2.3.4 "), true)).toBe("1.2.3.4");
    expect(clientAddress(withHeader(), true)).toBe(SHARED_CLIENT);
  });
});
