"use client";

import {
  CircleAlertIcon,
  CircleCheckIcon,
  CircleXIcon,
  InfoIcon,
  TriangleAlertIcon,
  type LucideIcon,
} from "lucide-react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from "react";

import { MODEL_SETTINGS_CHANGED, ModelSettingsSection } from "@/components/model-settings";
import { PROVIDER_KEYS_CHANGED, ProvidersSettings } from "@/components/providers-settings";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button, buttonVariants } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  ApiError,
  NotFoundError,
  SetupIncompleteError,
  SetupTokenInvalidError,
  UnauthenticatedError,
} from "@/lib/api";
import { redirectToLogin } from "@/lib/redirect-to-login";
import {
  finishSetup,
  getSetupStatus,
  type SetupItem,
  type SetupItemState,
  type SetupStatus,
} from "@/lib/setup";

/** Where the setup token is kept: this browser tab only, until setup ends. */
export const SETUP_TOKEN_KEY = "focus-funnel:setup-token";

const SOMETHING_WENT_WRONG = "Something went wrong. Try again.";

type Phase =
  | { kind: "checking" }
  | { kind: "token"; error: string | null }
  | { kind: "closed" }
  | { kind: "open"; status: SetupStatus }
  | { kind: "done" };

// sessionStorage can throw (storage turned off); the wizard then asks for the
// token again after a reload, which is all that is lost.
function readToken(): string | null {
  try {
    return window.sessionStorage.getItem(SETUP_TOKEN_KEY);
  } catch {
    return null;
  }
}

function storeToken(token: string) {
  try {
    window.sessionStorage.setItem(SETUP_TOKEN_KEY, token);
  } catch {
    // Kept in memory only.
  }
}

function forgetToken() {
  try {
    window.sessionStorage.removeItem(SETUP_TOKEN_KEY);
  } catch {
    // Nothing stored.
  }
}

function messageFor(error: unknown): string {
  return error instanceof ApiError ? error.message : SOMETHING_WENT_WRONG;
}

const MODE_LABELS: Record<string, string> = {
  oidc: "OpenID Connect (oidc)",
  firebase: "Firebase (firebase)",
  demo: "Demo (demo)",
};

const ITEM_NAMES: Record<string, string> = {
  database: "Database",
  encryption_key: "Key encryption key",
  login: "Login",
  allow_list: "Allow-list",
  search_key: "Search key",
  chat_model: "Default model",
  custom_provider: "Custom provider",
  connectors: "Connectors",
};

const STATES: Record<SetupItemState, { label: string; Icon: LucideIcon; className: string }> = {
  ok: { label: "OK", Icon: CircleCheckIcon, className: "text-emerald-600 dark:text-emerald-400" },
  missing: { label: "Missing", Icon: CircleAlertIcon, className: "text-amber-600 dark:text-amber-400" },
  failed: { label: "Failed", Icon: CircleXIcon, className: "text-destructive" },
  warning: { label: "Warning", Icon: TriangleAlertIcon, className: "text-amber-600 dark:text-amber-400" },
  info: { label: "Info", Icon: InfoIcon, className: "text-muted-foreground" },
};

/**
 * The first-run setup wizard: the setup token the backend printed, then four
 * steps (login, provider, model, server) built from `GET /api/setup/status`,
 * and Finish. The provider and model steps embed the settings sections
 * unchanged, so what they save is the operator's own key and loadout; the
 * status is read again after each successful save.
 */
export function SetupWizard() {
  const [phase, setPhase] = useState<Phase>({ kind: "checking" });
  const [tokenInput, setTokenInput] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const [finishing, setFinishing] = useState(false);
  const [finishError, setFinishError] = useState<string | null>(null);
  const token = useRef<string | null>(null);
  // Only the newest status request may change the page.
  const latest = useRef(0);

  /** Handles a refusal from a setup route; returns true when it was one. */
  const handleRefusal = useCallback((error: unknown, sentToken: boolean): boolean => {
    if (error instanceof UnauthenticatedError) {
      redirectToLogin("/setup");
      return true;
    }
    if (error instanceof NotFoundError) {
      token.current = null;
      forgetToken();
      setPhase({ kind: "closed" });
      return true;
    }
    if (error instanceof SetupTokenInvalidError) {
      token.current = null;
      forgetToken();
      setPhase({ kind: "token", error: sentToken ? error.message : null });
      return true;
    }
    return false;
  }, []);

  /**
   * Reads the status with the given token (null asks whether setup is open at
   * all). A refresh keeps the steps on screen when the call fails for another
   * reason, such as an unreachable backend.
   */
  const load = useCallback(
    (value: string | null, refresh = false): Promise<void> => {
      const request = ++latest.current;
      return getSetupStatus(value).then(
        (status) => {
          if (request !== latest.current) return;
          setRefreshError(null);
          if (value === null) {
            // The server always wants a token; ask for it.
            setPhase({ kind: "token", error: null });
            return;
          }
          token.current = value;
          storeToken(value);
          setPhase({ kind: "open", status });
        },
        (error: unknown) => {
          if (request !== latest.current) return;
          if (handleRefusal(error, value !== null)) return;
          if (refresh) setRefreshError(messageFor(error));
          else setPhase({ kind: "token", error: messageFor(error) });
        },
      );
    },
    [handleRefusal],
  );

  // On the first render: the token kept in this tab, or a check without one
  // that tells "setup is closed" (404) from "a token is needed" (403).
  useEffect(() => {
    void load(readToken());
  }, [load]);

  // A saved key or model changes the status.
  const open = phase.kind === "open";
  useEffect(() => {
    if (!open) return;
    const refresh = () => {
      if (token.current !== null) void load(token.current, true);
    };
    window.addEventListener(PROVIDER_KEYS_CHANGED, refresh);
    window.addEventListener(MODEL_SETTINGS_CHANGED, refresh);
    return () => {
      window.removeEventListener(PROVIDER_KEYS_CHANGED, refresh);
      window.removeEventListener(MODEL_SETTINGS_CHANGED, refresh);
    };
  }, [open, load]);

  async function submitToken(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const value = tokenInput.trim();
    if (value === "") {
      setPhase({ kind: "token", error: "Enter the setup token from the backend's log." });
      return;
    }
    setSubmitting(true);
    try {
      await load(value);
      setTokenInput("");
    } finally {
      setSubmitting(false);
    }
  }

  async function finish() {
    const value = token.current;
    if (value === null) return;
    setFinishing(true);
    setFinishError(null);
    try {
      await finishSetup(value);
      token.current = null;
      forgetToken();
      setPhase({ kind: "done" });
    } catch (error) {
      if (error instanceof SetupIncompleteError) {
        setFinishError(error.message);
        void load(value, true);
      } else if (!handleRefusal(error, true)) {
        setFinishError(messageFor(error));
      }
    } finally {
      setFinishing(false);
    }
  }

  switch (phase.kind) {
    case "checking":
      return <p className="text-sm text-muted-foreground">Checking setup…</p>;

    case "closed":
      return (
        <div className="flex flex-col gap-3">
          <p>Setup is not open on this server.</p>
          <p className="text-sm text-muted-foreground">
            It has been finished, or the server does not offer it. Change your keys and models in{" "}
            <Link href="/settings" className="underline">
              Settings
            </Link>
            , or{" "}
            <Link href="/app" className="underline">
              go to the app
            </Link>
            .
          </p>
        </div>
      );

    case "done":
      return (
        <div className="flex flex-col gap-3">
          <p>Setup is complete.</p>
          <p className="text-sm text-muted-foreground">
            The setup page is closed now. Other users set their own keys and models in Settings.
          </p>
          <div>
            <Link href="/app" className={buttonVariants()}>
              Go to the app
            </Link>
          </div>
        </div>
      );

    case "token":
      return (
        <form className="flex flex-col gap-3" onSubmit={submitToken} noValidate>
          <label className="flex flex-col gap-1 text-sm">
            <span className="font-medium">Setup token</span>
            <Input
              aria-label="Setup token"
              autoComplete="off"
              spellCheck={false}
              value={tokenInput}
              onChange={(event) => setTokenInput(event.target.value)}
              disabled={submitting}
            />
          </label>
          <p className="text-sm text-muted-foreground">
            The backend prints the setup token in its log each time it starts (for example{" "}
            <code>docker compose logs backend</code>). Restart the backend to get a new one.
          </p>
          {phase.error && (
            <Alert variant="destructive">
              <AlertDescription>{phase.error}</AlertDescription>
            </Alert>
          )}
          <div>
            <Button type="submit" disabled={submitting}>
              {submitting ? "Checking…" : "Continue"}
            </Button>
          </div>
        </form>
      );

    case "open":
      return (
        <OpenSetup
          status={phase.status}
          refreshError={refreshError}
          finishing={finishing}
          finishError={finishError}
          onFinish={finish}
        />
      );
  }
}

function OpenSetup({
  status,
  refreshError,
  finishing,
  finishError,
  onFinish,
}: {
  status: SetupStatus;
  refreshError: string | null;
  finishing: boolean;
  finishError: string | null;
  onFinish: () => void;
}) {
  const byId = new Map(status.items.map((item) => [item.id, item]));
  const pick = (...ids: string[]) =>
    ids.map((id) => byId.get(id)).filter((item): item is SetupItem => item !== undefined);
  const loginItems = pick("login", "allow_list");
  const loginSettings = [...new Set(loginItems.flatMap((item) => item.settings))];

  return (
    <div className="flex flex-col gap-8">
      {refreshError && (
        <Alert variant="destructive">
          <AlertDescription>{refreshError}</AlertDescription>
        </Alert>
      )}

      <Step id="setup-login" title="1. Login">
        <p className="text-sm">
          Mode: <span className="font-medium">{MODE_LABELS[status.auth_mode] ?? status.auth_mode}</span>
        </p>
        <ItemList items={loginItems} />
        <p className="text-sm text-muted-foreground">
          These come from the environment and cannot be changed here. Change them in{" "}
          <code>.env</code> and restart both servers: {joinCodes(loginSettings)}. See{" "}
          <code>docs/login.md</code>.
        </p>
      </Step>

      <Step id="setup-provider" title="2. Provider">
        <ItemList items={pick("search_key")} />
        <ProvidersSettings />
      </Step>

      <Step id="setup-model" title="3. Model">
        <ItemList items={pick("chat_model")} />
        <ModelSettingsSection />
      </Step>

      <Step id="setup-server" title="4. Server">
        <ItemList items={pick("database", "encryption_key", "custom_provider", "connectors")} />
      </Step>

      <div className="flex flex-col gap-2 border-t pt-4">
        {finishError && (
          <Alert variant="destructive">
            <AlertDescription>{finishError}</AlertDescription>
          </Alert>
        )}
        {!status.ready && (
          <p className="text-sm text-muted-foreground">
            Finish is enabled once every required item is OK.
          </p>
        )}
        <div>
          <Button type="button" onClick={onFinish} disabled={!status.ready || finishing}>
            {finishing ? "Finishing…" : "Finish"}
          </Button>
        </div>
      </div>
    </div>
  );
}

function Step({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="flex flex-col gap-3">
      <h2 id={id} className="text-lg font-semibold tracking-tight">
        {title}
      </h2>
      {children}
    </section>
  );
}

function ItemList({ items }: { items: SetupItem[] }) {
  if (items.length === 0) return null;
  return (
    <ul className="flex flex-col gap-2">
      {items.map((item) => {
        const name = ITEM_NAMES[item.id] ?? item.id;
        const { label, Icon, className } = STATES[item.state] ?? STATES.info;
        return (
          <li key={item.id} aria-label={name} className="flex gap-2 rounded-lg border p-3 text-sm">
            <Icon aria-hidden className={`mt-0.5 size-4 shrink-0 ${className}`} />
            <div className="flex flex-col gap-1">
              <p>
                <span className="font-medium">{name}</span>{" "}
                <span className={className}>
                  {label}
                  {item.required ? "" : " (optional)"}
                </span>
              </p>
              <p>{item.message}</p>
              {item.settings.length > 0 && (
                <p className="text-xs text-muted-foreground">Set by {joinCodes(item.settings)}</p>
              )}
            </div>
          </li>
        );
      })}
    </ul>
  );
}

function joinCodes(names: string[]): ReactNode {
  return names.map((name, index) => (
    <span key={name}>
      {index > 0 && ", "}
      <code>{name}</code>
    </span>
  ));
}
