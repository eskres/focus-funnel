// The auth mode and its settings for the frontend server. Read from the
// server's environment at run time, never from a build-time public variable, so
// one build serves every mode. The backend runs the same checks.

export const AUTH_MODES = ["oidc", "firebase", "demo"] as const;
export type AuthMode = (typeof AUTH_MODES)[number];

export const DEFAULT_OIDC_SCOPES = "openid email profile offline_access";
// SESSION_SECRET is stretched into a 256-bit key, so it needs as much entropy.
const MIN_SESSION_SECRET_LENGTH = 32;
const LOGIN_SETTING_PREFIXES = ["OIDC_", "FIREBASE_"];

export interface OidcConfig {
  issuer: string;
  clientId: string;
  clientSecret: string;
  scopes: string;
  /** Replaces the issuer's origin for server-to-server calls. */
  internalUrl: string | null;
}

export interface FirebaseConfig {
  projectId: string;
  apiKey: string;
  authDomain: string;
}

export interface DemoConfig {
  keyTtlMinutes: number;
  keyMaxHours: number;
  rateLimit: number;
  newSessionsPerHour: number;
  trustedProxy: boolean;
}

export interface AuthConfig {
  mode: AuthMode;
  sessionSecret: string;
  appBaseUrl: string | null;
  /** Lowercased addresses and @domain entries, or null when no list is set. */
  allowedEmails: string[] | null;
  oidc: OidcConfig | null;
  firebase: FirebaseConfig | null;
  demo: DemoConfig | null;
}

export class AuthConfigError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "AuthConfigError";
  }
}

type Env = Record<string, string | undefined>;

function value(env: Env, name: string): string | null {
  const raw = env[name]?.trim();
  return raw ? raw : null;
}

function required(env: Env, name: string, mode: AuthMode): string {
  const found = value(env, name);
  if (found === null) throw new AuthConfigError(`${name} is required when AUTH_MODE is ${mode}`);
  return found;
}

function positiveNumber(env: Env, name: string, fallback: number): number {
  const raw = value(env, name);
  if (raw === null) return fallback;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new AuthConfigError(`${name} must be a positive number, got '${raw}'`);
  }
  return parsed;
}

function flag(env: Env, name: string): boolean | null {
  const raw = value(env, name);
  if (raw === null) return null;
  const lowered = raw.toLowerCase();
  if (["true", "1", "yes", "on"].includes(lowered)) return true;
  if (["false", "0", "no", "off"].includes(lowered)) return false;
  throw new AuthConfigError(`${name} must be true or false, got '${raw}'`);
}

function url(env: Env, name: string, raw: string): string {
  try {
    return new URL(raw).toString().replace(/\/$/, "");
  } catch {
    throw new AuthConfigError(`${name} must be a URL, got '${raw}'`);
  }
}

/** Parses AUTH_ALLOWED_EMAILS into lowercased entries, or null when unset. */
export function parseAllowedEmails(raw: string | null | undefined): string[] | null {
  if (!raw?.trim()) return null;
  return raw
    .split(",")
    .map((entry) => entry.trim().toLowerCase())
    .filter(Boolean);
}

/** Reads and checks the auth settings. Throws AuthConfigError naming the setting. */
export function readAuthConfig(env: Env = process.env): AuthConfig {
  const rawMode = value(env, "AUTH_MODE");
  if (rawMode === null) {
    throw new AuthConfigError("AUTH_MODE is required: set it to oidc, firebase, or demo");
  }
  const mode = rawMode.toLowerCase() as AuthMode;
  if (!AUTH_MODES.includes(mode)) {
    throw new AuthConfigError(
      `AUTH_MODE '${rawMode}' is not valid: set it to oidc, firebase, or demo`,
    );
  }

  const sessionSecret = required(env, "SESSION_SECRET", mode);
  if (sessionSecret.length < MIN_SESSION_SECRET_LENGTH) {
    throw new AuthConfigError(
      `SESSION_SECRET must be at least ${MIN_SESSION_SECRET_LENGTH} characters: openssl rand -hex 32`,
    );
  }
  const rawBaseUrl = value(env, "APP_BASE_URL");
  const appBaseUrl = rawBaseUrl === null ? null : url(env, "APP_BASE_URL", rawBaseUrl);

  const config: AuthConfig = {
    mode,
    sessionSecret,
    appBaseUrl,
    allowedEmails: parseAllowedEmails(value(env, "AUTH_ALLOWED_EMAILS")),
    oidc: null,
    firebase: null,
    demo: null,
  };

  if (mode === "oidc") {
    if (appBaseUrl === null) {
      throw new AuthConfigError("APP_BASE_URL is required when AUTH_MODE is oidc");
    }
    const internalUrl = value(env, "OIDC_INTERNAL_URL");
    config.oidc = {
      issuer: required(env, "OIDC_ISSUER", mode),
      clientId: required(env, "OIDC_CLIENT_ID", mode),
      clientSecret: required(env, "OIDC_CLIENT_SECRET", mode),
      scopes: value(env, "OIDC_SCOPES") ?? DEFAULT_OIDC_SCOPES,
      internalUrl: internalUrl === null ? null : url(env, "OIDC_INTERNAL_URL", internalUrl),
    };
    url(env, "OIDC_ISSUER", config.oidc.issuer);
  } else if (mode === "firebase") {
    config.firebase = {
      projectId: required(env, "FIREBASE_PROJECT_ID", mode),
      apiKey: required(env, "FIREBASE_API_KEY", mode),
      authDomain: required(env, "FIREBASE_AUTH_DOMAIN", mode),
    };
  } else {
    const loginSetting = Object.keys(env)
      .sort()
      .find(
        (name) =>
          LOGIN_SETTING_PREFIXES.some((prefix) => name.toUpperCase().startsWith(prefix)) &&
          value(env, name) !== null,
      );
    if (loginSetting) {
      throw new AuthConfigError(`Remove ${loginSetting}: demo mode does not use login settings`);
    }
    if (flag(env, "ALLOW_CUSTOM_PROVIDER") === true) {
      throw new AuthConfigError(
        "Remove ALLOW_CUSTOM_PROVIDER=true: demo mode turns the custom provider off",
      );
    }
    config.demo = {
      keyTtlMinutes: positiveNumber(env, "DEMO_KEY_TTL_MINUTES", 30),
      keyMaxHours: positiveNumber(env, "DEMO_KEY_MAX_HOURS", 4),
      rateLimit: positiveNumber(env, "DEMO_RATE_LIMIT", 60),
      newSessionsPerHour: positiveNumber(env, "DEMO_NEW_SESSIONS_PER_HOUR", 5),
      trustedProxy: flag(env, "TRUSTED_PROXY") ?? false,
    };
  }
  return config;
}

/** The auth settings of this server process, read from its environment. */
export function getAuthConfig(): AuthConfig {
  return readAuthConfig(process.env);
}
