"use client";

import { useEffect, useState, type FormEvent } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiError, apiFetch, UnauthenticatedError } from "@/lib/api";

export interface ApiKeyStatus {
  saved: boolean;
  last4?: string;
  saved_at?: string;
}

const ENDPOINT = "/api/settings/api-key";

// Messages from the nebius-api-key spec, keyed by backend error code.
const errorMessages: Record<string, string> = {
  nebius_key_invalid: "Nebius rejected this API key. Check the key and try again.",
  nebius_unreachable:
    "The key could not be checked because Nebius did not respond. Try again.",
  validation_error: "Enter an API key.",
};

function messageFor(error: unknown): string {
  if (error instanceof ApiError && errorMessages[error.code]) {
    return errorMessages[error.code];
  }
  return "Something went wrong. Try again.";
}

function formatDate(iso: string | undefined): string {
  if (!iso) return "an unknown date";
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? "an unknown date"
    : date.toLocaleDateString(undefined, { dateStyle: "medium" });
}

function redirectToLogin() {
  // /auth/login is an Auth0 SDK route served by proxy.ts, not a Next.js page,
  // so it needs a full browser navigation rather than a client-side route change.
  // eslint-disable-next-line @next/next/no-location-assign-relative-destination
  window.location.assign("/auth/login?returnTo=/settings");
}

export function ApiKeySettings() {
  const [status, setStatus] = useState<ApiKeyStatus | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    apiFetch<ApiKeyStatus>(ENDPOINT)
      .then((result) => {
        if (!cancelled) setStatus(result);
      })
      .catch((e: unknown) => {
        if (cancelled) return;
        if (e instanceof UnauthenticatedError) redirectToLogin();
        else setLoadError(messageFor(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (apiKey.trim() === "") {
      setError(errorMessages.validation_error);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const result = await apiFetch<ApiKeyStatus>(ENDPOINT, {
        method: "PUT",
        body: JSON.stringify({ api_key: apiKey }),
      });
      setStatus(result);
      setApiKey("");
      setEditing(false);
    } catch (e) {
      // On failure the backend keeps any previously saved key, so the shown
      // status stays as it was.
      if (e instanceof UnauthenticatedError) redirectToLogin();
      else setError(messageFor(e));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    setBusy(true);
    setError(null);
    try {
      await apiFetch<void>(ENDPOINT, { method: "DELETE" });
      setStatus({ saved: false });
      setEditing(false);
    } catch (e) {
      if (e instanceof UnauthenticatedError) redirectToLogin();
      else setError(messageFor(e));
    } finally {
      setBusy(false);
    }
  }

  function cancelReplace() {
    setEditing(false);
    setApiKey("");
    setError(null);
  }

  const showForm = status !== null && (!status.saved || editing);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Nebius API key</CardTitle>
        <CardDescription>
          Focus Funnel uses your own Nebius key. It is checked with Nebius
          before it is saved, stored encrypted, and never shown in full again.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {status === null && !loadError && (
          <p className="text-sm text-muted-foreground">Loading…</p>
        )}
        {loadError && (
          <Alert variant="destructive">
            <AlertDescription>{loadError}</AlertDescription>
          </Alert>
        )}

        {status && !status.saved && (
          <p className="text-sm">No API key saved.</p>
        )}
        {status?.saved && (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <p className="text-sm">
              Key ending in{" "}
              <span className="font-mono font-medium">{status.last4}</span>, saved
              on {formatDate(status.saved_at)}.
            </p>
            {!editing && (
              <div className="flex gap-2">
                <Button variant="outline" onClick={() => setEditing(true)} disabled={busy}>
                  Replace
                </Button>
                <Button variant="destructive" onClick={remove} disabled={busy}>
                  Delete
                </Button>
              </div>
            )}
          </div>
        )}

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {showForm && (
          <form onSubmit={save} className="flex flex-col gap-2 sm:flex-row">
            <Input
              type="password"
              name="api_key"
              aria-label={status?.saved ? "New Nebius API key" : "Nebius API key"}
              placeholder="Paste your Nebius API key"
              autoComplete="off"
              value={apiKey}
              onChange={(event) => setApiKey(event.target.value)}
              disabled={busy}
            />
            <div className="flex gap-2">
              <Button type="submit" disabled={busy}>
                {busy ? "Checking…" : "Save"}
              </Button>
              {status?.saved && (
                <Button type="button" variant="ghost" onClick={cancelReplace} disabled={busy}>
                  Cancel
                </Button>
              )}
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
