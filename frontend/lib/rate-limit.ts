// In-memory token buckets for demo mode. They live in this one server
// process, which is why demo mode runs a single frontend instance.

export type Take = { allowed: true } | { allowed: false; retryAfterSeconds: number };

interface Bucket {
  tokens: number;
  updatedAt: number;
}

export class RateLimiter {
  private readonly buckets = new Map<string, Bucket>();
  private takes = 0;

  /** Allows `capacity` requests per `windowMs` per key, refilled evenly. */
  constructor(
    readonly capacity: number,
    readonly windowMs: number,
  ) {}

  take(key: string, now = Date.now()): Take {
    const perMs = this.capacity / this.windowMs;
    const bucket = this.buckets.get(key) ?? { tokens: this.capacity, updatedAt: now };
    bucket.tokens = Math.min(this.capacity, bucket.tokens + (now - bucket.updatedAt) * perMs);
    bucket.updatedAt = now;
    this.buckets.set(key, bucket);
    if (++this.takes % 1000 === 0) this.sweep(now);
    if (bucket.tokens >= 1) {
      bucket.tokens -= 1;
      return { allowed: true };
    }
    return { allowed: false, retryAfterSeconds: Math.max(1, Math.ceil((1 - bucket.tokens) / perMs / 1000)) };
  }

  /** Drops buckets that have refilled completely; they hold nothing. */
  private sweep(now: number) {
    for (const [key, bucket] of this.buckets) {
      if (now - bucket.updatedAt >= this.windowMs) this.buckets.delete(key);
    }
  }
}

// Every request without a trusted proxy shares this key.
export const SHARED_CLIENT = "shared";

/**
 * The client address for the limits. Behind a reverse proxy
 * (TRUSTED_PROXY=true) it is the last X-Forwarded-For hop, the one the proxy
 * added. Otherwise the server cannot see a trustworthy address (a client can
 * send any X-Forwarded-For), so all requests share one bucket.
 */
export function clientAddress(request: Request, trustedProxy: boolean): string {
  if (!trustedProxy) return SHARED_CLIENT;
  const hops = (request.headers.get("x-forwarded-for") ?? "")
    .split(",")
    .map((hop) => hop.trim())
    .filter(Boolean);
  return hops.at(-1) ?? SHARED_CLIENT;
}
