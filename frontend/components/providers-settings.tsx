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
import { ApiError, apiFetch, UnauthenticatedError, ValidationError } from "@/lib/api";

export interface ProviderStatus {
  id: string;
  label: string;
  key_url: string;
  notice: string;
  key_required: boolean;
  is_custom: boolean;
  base_url?: string;
  key_saved: boolean;
  key_last4?: string;
  key_saved_at?: string;
}

interface ProvidersResponse {
  providers: ProviderStatus[];
  custom_provider_allowed: boolean;
}

const LIST_ENDPOINT = "/api/providers";

// Shown by the browser's own check before an empty key is sent for a
// provider that needs one.
const EMPTY_KEY_MESSAGE = "Enter an API key.";
const EMPTY_BASE_URL_MESSAGE = "Enter a base URL.";
const NOTICE_NOT_ACCEPTED_MESSAGE = "Read the notice above before saving a key.";

function messageFor(error: unknown): string {
  if (error instanceof ValidationError) return error.message;
  if (error instanceof ApiError) return error.message;
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
  // /auth/login is a route handler, not a page, so it needs a full browser
  // navigation rather than a client-side route change. It sends the user to
  // the login of the server's auth mode.
  window.location.assign(new URL("/auth/login?returnTo=/settings", window.location.origin));
}

export function ProvidersSettings() {
  const [providers, setProviders] = useState<ProviderStatus[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    apiFetch<ProvidersResponse>(LIST_ENDPOINT)
      .then((result) => {
        if (!cancelled) setProviders(result.providers);
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

  function updateProvider(updated: ProviderStatus) {
    setProviders((current) =>
      (current ?? []).map((p) => (p.id === updated.id ? updated : p)),
    );
  }

  return (
    <div className="flex flex-col gap-4">
      {providers === null && !loadError && (
        <p className="text-sm text-muted-foreground">Loading…</p>
      )}
      {loadError && (
        <Alert variant="destructive">
          <AlertDescription>{loadError}</AlertDescription>
        </Alert>
      )}
      {providers?.map((provider) => (
        <ProviderCard key={provider.id} provider={provider} onUpdated={updateProvider} />
      ))}
    </div>
  );
}

function ProviderCard({
  provider,
  onUpdated,
}: {
  provider: ProviderStatus;
  onUpdated: (updated: ProviderStatus) => void;
}) {
  const [editing, setEditing] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [baseUrl, setBaseUrl] = useState(provider.base_url ?? "");
  const [noticeAccepted, setNoticeAccepted] = useState(false);
  const [noticeOpen, setNoticeOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState<string | null>(null);

  const endpoint = `/api/providers/${provider.id}/key`;
  // A keyless provider is ready to test and edit once its base URL (custom)
  // or its fixed config (a keyless preset) is in place, even with no key saved.
  // "Ready" is also what the notice gate keys off: a keyless provider's
  // key_saved never turns true, so gating on it would block every edit
  // forever instead of just the first one.
  const configured =
    provider.key_saved || (provider.is_custom ? Boolean(provider.base_url) : !provider.key_required);
  const needsNoticeGate = provider.notice.trim() !== "" && !configured;
  const showForm = !configured || editing;

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setTestResult(null);
    if (provider.key_required && apiKey.trim() === "") {
      setError(EMPTY_KEY_MESSAGE);
      return;
    }
    if (provider.is_custom && baseUrl.trim() === "") {
      setError(EMPTY_BASE_URL_MESSAGE);
      return;
    }
    if (needsNoticeGate && !noticeAccepted) {
      setError(NOTICE_NOT_ACCEPTED_MESSAGE);
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const body: { key: string; base_url?: string } = { key: apiKey };
      if (provider.is_custom) body.base_url = baseUrl.trim();
      const result = await apiFetch<ProviderStatus>(endpoint, {
        method: "PUT",
        body: JSON.stringify(body),
      });
      onUpdated(result);
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
    setTestResult(null);
    try {
      await apiFetch<void>(endpoint, { method: "DELETE" });
      onUpdated({
        ...provider,
        key_saved: false,
        key_last4: undefined,
        key_saved_at: undefined,
        base_url: provider.is_custom ? undefined : provider.base_url,
      });
      setBaseUrl("");
      setEditing(false);
    } catch (e) {
      if (e instanceof UnauthenticatedError) redirectToLogin();
      else setError(messageFor(e));
    } finally {
      setBusy(false);
    }
  }

  async function test() {
    setBusy(true);
    setError(null);
    setTestResult(null);
    try {
      const result = await apiFetch<{ models: unknown[] }>(
        `/api/providers/${provider.id}/models`,
      );
      const count = result.models.length;
      setTestResult(count === 1 ? "1 model available." : `${count} models available.`);
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
    setTestResult(null);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>{provider.label}</CardTitle>
        <CardDescription className="flex flex-col gap-1">
          {provider.key_url && (
            <a
              href={provider.key_url}
              target="_blank"
              rel="noreferrer"
              className="underline underline-offset-2"
            >
              Get a key
            </a>
          )}
          {provider.notice.trim() !== "" && (
            <button
              type="button"
              className="w-fit text-left underline underline-offset-2"
              onClick={() => setNoticeOpen((open) => !open)}
            >
              {noticeOpen ? "Hide data-handling notice" : "Read data-handling notice"}
            </button>
          )}
          {noticeOpen && <p className="text-sm">{provider.notice}</p>}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {provider.is_custom && !editing && (
          <p className="text-sm">
            {provider.base_url ? (
              <>
                Endpoint: <span className="font-mono">{provider.base_url}</span>
              </>
            ) : (
              "No endpoint set."
            )}
          </p>
        )}

        {!provider.key_saved && (
          <p className="text-sm">
            {provider.key_required ? "No API key saved." : "No API key needed for this provider."}
          </p>
        )}
        {provider.key_saved && (
          <p className="text-sm">
            Key ending in <span className="font-mono font-medium">{provider.key_last4}</span>,
            saved on {formatDate(provider.key_saved_at)}.
          </p>
        )}
        {configured && !editing && (
          <div className="flex gap-2">
            <Button variant="outline" onClick={test} disabled={busy}>
              Test
            </Button>
            <Button variant="outline" onClick={() => setEditing(true)} disabled={busy}>
              {provider.key_saved ? "Replace" : "Edit"}
            </Button>
            <Button variant="destructive" onClick={remove} disabled={busy}>
              Delete
            </Button>
          </div>
        )}

        {testResult && <p className="text-sm text-muted-foreground">{testResult}</p>}

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        {showForm && (
          <form onSubmit={save} className="flex flex-col gap-2">
            {provider.is_custom && (
              <>
                <Input
                  type="text"
                  name="base_url"
                  aria-label="Base URL"
                  placeholder="http://localhost:11434/v1"
                  autoComplete="off"
                  value={baseUrl}
                  onChange={(event) => setBaseUrl(event.target.value)}
                  disabled={busy}
                />
                <p className="text-xs text-muted-foreground">
                  Include the /v1 path and your server&apos;s port. If Focus Funnel runs in
                  Docker, use host.docker.internal instead of localhost.
                </p>
              </>
            )}
            {needsNoticeGate && (
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={noticeAccepted}
                  onChange={(event) => setNoticeAccepted(event.target.checked)}
                  disabled={busy}
                />
                I&apos;ve read the data-handling notice above.
              </label>
            )}
            <div className="flex flex-col gap-2 sm:flex-row">
              <Input
                type="password"
                name="api_key"
                aria-label={provider.key_saved ? `New ${provider.label} API key` : `${provider.label} API key`}
                placeholder={`Paste your ${provider.label} API key`}
                autoComplete="off"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                disabled={busy}
              />
              <div className="flex gap-2">
                <Button type="submit" disabled={busy}>
                  {busy ? "Checking…" : "Save"}
                </Button>
                {provider.key_saved && (
                  <Button type="button" variant="ghost" onClick={cancelReplace} disabled={busy}>
                    Cancel
                  </Button>
                )}
              </div>
            </div>
          </form>
        )}
      </CardContent>
    </Card>
  );
}
