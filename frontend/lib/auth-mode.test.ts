import { readdirSync, readFileSync, statSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { AuthConfigError, DEFAULT_OIDC_SCOPES, readAuthConfig } from "./auth-mode";

const SECRET = "0123456789abcdef0123456789abcdef";

const oidcEnv = {
  AUTH_MODE: "oidc",
  SESSION_SECRET: SECRET,
  APP_BASE_URL: "http://localhost:3000",
  OIDC_ISSUER: "http://localhost:1411",
  OIDC_CLIENT_ID: "client-id",
  OIDC_CLIENT_SECRET: "client-secret",
};
const firebaseEnv = {
  AUTH_MODE: "firebase",
  SESSION_SECRET: SECRET,
  FIREBASE_PROJECT_ID: "focus-funnel",
  FIREBASE_API_KEY: "public-web-api-key",
  FIREBASE_AUTH_DOMAIN: "focus-funnel.firebaseapp.com",
};
const demoEnv = { AUTH_MODE: "demo", SESSION_SECRET: SECRET };

function failure(env: Record<string, string | undefined>): string {
  try {
    readAuthConfig(env);
  } catch (error) {
    expect(error).toBeInstanceOf(AuthConfigError);
    return (error as Error).message;
  }
  throw new Error("expected the configuration to be refused");
}

const without = (env: Record<string, string>, name: string) => ({ ...env, [name]: undefined });

describe("readAuthConfig", () => {
  it("names AUTH_MODE and its three values when it is missing", () => {
    const message = failure({ SESSION_SECRET: SECRET });
    expect(message).toContain("AUTH_MODE");
    for (const mode of ["oidc", "firebase", "demo"]) expect(message).toContain(mode);
  });

  it("names the refused value of an unknown mode", () => {
    expect(failure({ ...demoEnv, AUTH_MODE: "magic-link" })).toContain("AUTH_MODE 'magic-link'");
  });

  it.each([
    ["oidc", oidcEnv],
    ["firebase", firebaseEnv],
    ["demo", demoEnv],
  ])("requires SESSION_SECRET in %s mode", (_mode, env) => {
    expect(failure(without(env, "SESSION_SECRET"))).toContain("SESSION_SECRET");
  });

  it("refuses a short SESSION_SECRET", () => {
    expect(failure({ ...demoEnv, SESSION_SECRET: "short" })).toContain("SESSION_SECRET");
  });

  it.each(["OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "APP_BASE_URL"])(
    "names %s when oidc mode lacks it",
    (name) => {
      expect(failure(without(oidcEnv, name))).toContain(name);
    },
  );

  it.each(["FIREBASE_PROJECT_ID", "FIREBASE_API_KEY", "FIREBASE_AUTH_DOMAIN"])(
    "names %s when firebase mode lacks it",
    (name) => {
      expect(failure(without(firebaseEnv, name))).toContain(name);
    },
  );

  it.each([
    "OIDC_ISSUER",
    "OIDC_CLIENT_ID",
    "OIDC_CLIENT_SECRET",
    "OIDC_SCOPES",
    "OIDC_INTERNAL_URL",
    "FIREBASE_PROJECT_ID",
    "FIREBASE_API_KEY",
    "FIREBASE_AUTH_DOMAIN",
  ])("refuses demo mode with %s set, naming it", (name) => {
    expect(failure({ ...demoEnv, [name]: "http://value" })).toContain(`Remove ${name}`);
  });

  it("refuses demo mode with ALLOW_CUSTOM_PROVIDER=true", () => {
    expect(failure({ ...demoEnv, ALLOW_CUSTOM_PROVIDER: "true" })).toContain(
      "ALLOW_CUSTOM_PROVIDER",
    );
  });

  it.each(["DEMO_RATE_LIMIT", "DEMO_KEY_TTL_MINUTES", "DEMO_KEY_MAX_HOURS"])(
    "names %s when it is not a positive number",
    (name) => {
      expect(failure({ ...demoEnv, [name]: "-1" })).toContain(name);
    },
  );

  it("reads a valid oidc configuration with default scopes", () => {
    const config = readAuthConfig({ ...oidcEnv, OIDC_INTERNAL_URL: "http://pocket-id:1411/" });
    expect(config.mode).toBe("oidc");
    expect(config.oidc).toMatchObject({
      issuer: "http://localhost:1411",
      scopes: DEFAULT_OIDC_SCOPES,
      internalUrl: "http://pocket-id:1411",
    });
    expect(config.demo).toBeNull();
  });

  it("reads demo defaults", () => {
    const config = readAuthConfig({ ...demoEnv, ALLOW_CUSTOM_PROVIDER: "false" });
    expect(config.demo).toEqual({
      keyTtlMinutes: 30,
      keyMaxHours: 4,
      rateLimit: 60,
      newSessionsPerHour: 5,
      trustedProxy: false,
    });
  });

  it("reads the allow-list lowercased", () => {
    const config = readAuthConfig({ ...firebaseEnv, AUTH_ALLOWED_EMAILS: "Ana@X.org, @Team.io" });
    expect(config.allowedEmails).toEqual(["ana@x.org", "@team.io"]);
  });

  it("reads the mode at call time, so a restart with a new value switches mode", () => {
    const env: Record<string, string | undefined> = { ...demoEnv };
    expect(readAuthConfig(env).mode).toBe("demo");
    Object.assign(env, firebaseEnv);
    expect(readAuthConfig(env).mode).toBe("firebase");
  });
});

describe("mode is never public", () => {
  const root = path.resolve(__dirname, "..");
  const skip = new Set(["node_modules", ".next", "coverage"]);

  function sourceFiles(dir: string): string[] {
    return readdirSync(dir).flatMap((name) => {
      if (skip.has(name)) return [];
      const full = path.join(dir, name);
      if (statSync(full).isDirectory()) return sourceFiles(full);
      return /\.(ts|tsx|mjs|js)$/.test(name) && !name.endsWith(".test.ts") ? [full] : [];
    });
  }

  it("uses no NEXT_PUBLIC_ variable, which would bake the mode into the build", () => {
    const offenders = sourceFiles(root).filter((file) =>
      readFileSync(file, "utf8").includes("NEXT_PUBLIC_"),
    );
    expect(offenders).toEqual([]);
  });
});
