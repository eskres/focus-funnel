"use client";

import { useEffect, useId, useState, type FormEvent } from "react";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ApiError, NotFoundError, UnauthenticatedError } from "@/lib/api";
import {
  acceptConnectorWarning,
  addConnector,
  changeConnector,
  changeTool,
  deleteConnector,
  getConnectors,
  testConnector,
  type AuthKind,
  type CatalogEntry,
  type Connector,
  type ConnectorFields,
  type ConnectorTool,
  type ConnectorsListing,
  type ToolChange,
} from "@/lib/connectors";
import { redirectToLogin } from "@/lib/redirect-to-login";

/** Shown once, before the first add and before the first tool is switched on. */
export const WARNING_TEXT = [
  "Connectors let the model read from and act on outside services, such as your calendar.",
  "What those services send back can contain instructions aimed at the model, written by anyone who can put text there.",
  "Add only servers you trust, and check each action before you approve it.",
];

const AUTH_LABELS: Record<AuthKind, string> = {
  none: "No auth",
  bearer: "Bearer token",
  header: "Header",
};

function messageFor(caught: unknown, fallback: string): string {
  return caught instanceof ApiError ? caught.message : fallback;
}

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

function formatDate(iso: string): string {
  const date = new Date(iso);
  return Number.isNaN(date.getTime())
    ? "an unknown date"
    : date.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/** How a connector's auth reads: never the value, only its last 4 characters. */
function authText(connector: Connector): string {
  if (connector.auth_kind === "none") return "No auth.";
  const what =
    connector.auth_kind === "bearer" ? "Bearer token" : `Header ${connector.auth_header ?? ""}`;
  if (connector.source === "operator") return `${what}, set by the operator.`;
  if (!connector.auth_set) return `${what}, no value stored.`;
  return connector.auth_kind === "bearer"
    ? `Bearer token ending in ${connector.auth_last4 ?? "????"}.`
    : `${what}, value ending in ${connector.auth_last4 ?? "????"}.`;
}

/**
 * "Connectors": the operator's connectors and the user's own, each with Test
 * and its tool list. Users add their own (from the catalog or by hand) only
 * when the server lets them. The section is not shown at all while
 * connectors are off on the server (`GET /api/connectors` answers 404).
 */
export function ConnectorsSection() {
  const [listing, setListing] = useState<ConnectorsListing | null>(null);
  const [off, setOff] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState<FormStart | null>(null);
  // What to do once the warning is accepted; the warning is open while set.
  const [afterWarning, setAfterWarning] = useState<(() => void) | null>(null);
  const [warningBusy, setWarningBusy] = useState(false);
  const [warningError, setWarningError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    getConnectors()
      .then((loaded) => !cancelled && setListing(loaded))
      .catch((caught: unknown) => {
        if (cancelled) return;
        if (caught instanceof NotFoundError) setOff(true);
        else if (caught instanceof UnauthenticatedError) redirectToLogin("/settings");
        else setLoadError("The connectors could not be loaded.");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Connectors are off on the server; nothing shows until the listing arrives.
  if (off || (listing === null && loadError === null)) return null;

  /** Run `then` now if the warning was accepted, else after the user accepts it. */
  function requireWarning(then: () => void) {
    if (listing?.warning_accepted) {
      then();
      return;
    }
    setWarningError(null);
    setAfterWarning(() => then);
  }

  async function acceptWarning() {
    setWarningBusy(true);
    setWarningError(null);
    try {
      await acceptConnectorWarning();
    } catch (caught) {
      setWarningError(messageFor(caught, "Could not save that. Try again."));
      setWarningBusy(false);
      return;
    }
    setWarningBusy(false);
    setListing((current) => current && { ...current, warning_accepted: true });
    const then = afterWarning;
    setAfterWarning(null);
    then?.();
  }

  function replace(updated: Connector) {
    setListing(
      (current) =>
        current && {
          ...current,
          connectors: current.connectors.map((c) => (c.id === updated.id ? updated : c)),
        },
    );
  }

  function added(connector: Connector) {
    setListing(
      (current) => current && { ...current, connectors: [...current.connectors, connector] },
    );
    setForm(null);
  }

  function removed(id: string) {
    setListing(
      (current) =>
        current && { ...current, connectors: current.connectors.filter((c) => c.id !== id) },
    );
  }

  const allowed = listing?.user_connectors_allowed ?? false;

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2>Connectors</h2>
        </CardTitle>
        <CardDescription>
          Connectors let the chat use tools on outside services through MCP servers. Test a
          connector to list its tools, switch on the ones the model may use, then turn the
          connector on in a conversation. A tool that acts waits for your approval each time.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {loadError && (
          <p role="alert" className="text-sm text-destructive">
            {loadError}
          </p>
        )}
        {listing && listing.connectors.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {allowed ? "No connectors yet." : "The operator has not set up any connectors."}
          </p>
        )}
        {listing && listing.connectors.length > 0 && (
          <ul aria-label="Your connectors" className="flex flex-col gap-4">
            {listing.connectors.map((connector) => (
              <li key={connector.id}>
                <ConnectorItem
                  connector={connector}
                  onUpdated={replace}
                  onRemoved={removed}
                  requireWarning={requireWarning}
                />
              </li>
            ))}
          </ul>
        )}

        {allowed && listing && form === null && (
          <AddChoices
            catalog={listing.catalog}
            onStart={(start) => requireWarning(() => setForm(start))}
          />
        )}
        {allowed && form !== null && (
          <ConnectorForm
            key={form.key}
            start={form}
            onSave={async (fields) => added(await addConnector(fields as ConnectorFields))}
            onCancel={() => setForm(null)}
          />
        )}
      </CardContent>

      <Dialog
        open={afterWarning !== null}
        onOpenChange={(open) => !open && !warningBusy && setAfterWarning(null)}
      >
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Before you use connectors</DialogTitle>
            <DialogDescription render={<div />} className="flex flex-col gap-2">
              {WARNING_TEXT.map((line) => (
                <p key={line}>{line}</p>
              ))}
            </DialogDescription>
          </DialogHeader>
          {warningError && (
            <p role="alert" className="text-sm text-destructive">
              {warningError}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setAfterWarning(null)} disabled={warningBusy}>
              Cancel
            </Button>
            <Button onClick={acceptWarning} disabled={warningBusy}>
              I understand
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

/** How the add or edit form starts: empty, from a catalog entry, or from a connector. */
type FormStart = {
  key: string;
  fields: ConnectorFields;
  guide?: string;
  title?: string;
  editing?: Connector;
};

function AddChoices({
  catalog,
  onStart,
}: {
  catalog: CatalogEntry[];
  onStart: (start: FormStart) => void;
}) {
  return (
    <div className="flex flex-col gap-3">
      {catalog.length > 0 && (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-medium">Known servers</h3>
          <ul aria-label="Connector catalog" className="flex flex-col gap-2">
            {catalog.map((entry) => (
              <li key={entry.name} className="flex items-start justify-between gap-3">
                <div className="flex flex-col">
                  <span className="text-sm font-medium">{entry.title}</span>
                  <span className="text-xs text-muted-foreground">{entry.description}</span>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  aria-label={`Use ${entry.title}`}
                  onClick={() =>
                    onStart({
                      key: `catalog:${entry.name}`,
                      fields: {
                        name: entry.name,
                        url: entry.url,
                        auth_kind: entry.auth_kind,
                        auth_header: entry.auth_header,
                      },
                      guide: entry.guide,
                      title: entry.title,
                    })
                  }
                >
                  Use
                </Button>
              </li>
            ))}
          </ul>
        </div>
      )}
      <Button
        variant="outline"
        className="w-fit"
        onClick={() =>
          onStart({ key: "new", fields: { name: "", url: "", auth_kind: "none", auth_header: null } })
        }
      >
        Add connector
      </Button>
    </div>
  );
}

/** The add and edit form. Editing sends only what changed; an empty value keeps the stored one. */
function ConnectorForm({
  start,
  onSave,
  onCancel,
}: {
  start: FormStart;
  onSave: (fields: Partial<ConnectorFields>) => Promise<void>;
  onCancel: () => void;
}) {
  const id = useId();
  const editing = start.editing;
  const [name, setName] = useState(start.fields.name);
  const [url, setUrl] = useState(start.fields.url);
  const [kind, setKind] = useState<AuthKind>(start.fields.auth_kind);
  const [header, setHeader] = useState(start.fields.auth_header ?? "");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const keepsValue = Boolean(editing?.auth_set) && kind === editing?.auth_kind;

  function fields(): Partial<ConnectorFields> {
    const all: ConnectorFields = {
      name: name.trim(),
      url: url.trim(),
      auth_kind: kind,
      ...(kind === "header" ? { auth_header: header.trim() } : {}),
      ...(kind !== "none" && value ? { auth_value: value } : {}),
    };
    if (!editing) return all;
    const changed: Partial<ConnectorFields> = {};
    if (all.name !== editing.name) changed.name = all.name;
    if (all.url !== (editing.url ?? "")) changed.url = all.url;
    if (kind !== editing.auth_kind) changed.auth_kind = kind;
    if (kind === "header" && all.auth_header !== (editing.auth_header ?? "")) {
      changed.auth_header = all.auth_header;
    }
    if (all.auth_value) changed.auth_value = all.auth_value;
    return changed;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSave(fields());
    } catch (caught) {
      setError(messageFor(caught, "Could not save the connector. Try again."));
      setBusy(false);
    }
  }

  const valueLabel = kind === "bearer" ? "Token" : "Header value";

  return (
    <form
      onSubmit={submit}
      aria-label={editing ? `Edit ${editing.name}` : "Add a connector"}
      className="flex flex-col gap-3 rounded-lg border p-3"
    >
      <h3 className="text-sm font-medium">
        {editing ? `Edit ${editing.name}` : start.title ? `Add ${start.title}` : "Add a connector"}
      </h3>
      {start.guide && (
        <p className="text-xs text-muted-foreground">
          This server runs on its own.{" "}
          <a href={start.guide} target="_blank" rel="noreferrer" className="underline underline-offset-2">
            Read how to set it up
          </a>
          , then check the URL below.
        </p>
      )}
      <div className="flex flex-col gap-1">
        <Label htmlFor={`${id}-name`}>Name</Label>
        <Input
          id={`${id}-name`}
          value={name}
          maxLength={24}
          autoComplete="off"
          onChange={(event) => setName(event.target.value)}
          disabled={busy}
        />
        <p className="text-xs text-muted-foreground">
          Lowercase letters, digits, and underscores. It starts each of the connector&apos;s tool
          names.
        </p>
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor={`${id}-url`}>Server URL</Label>
        <Input
          id={`${id}-url`}
          value={url}
          placeholder="https://example.com/mcp"
          autoComplete="off"
          onChange={(event) => setUrl(event.target.value)}
          disabled={busy}
        />
      </div>
      <div className="flex flex-col gap-1">
        <Label htmlFor={`${id}-auth`}>Auth</Label>
        <select
          id={`${id}-auth`}
          value={kind}
          onChange={(event) => setKind(event.target.value as AuthKind)}
          disabled={busy}
          className="h-8 w-fit rounded-lg border bg-background px-2 text-sm"
        >
          {(Object.keys(AUTH_LABELS) as AuthKind[]).map((option) => (
            <option key={option} value={option}>
              {AUTH_LABELS[option]}
            </option>
          ))}
        </select>
      </div>
      {kind === "header" && (
        <div className="flex flex-col gap-1">
          <Label htmlFor={`${id}-header`}>Header name</Label>
          <Input
            id={`${id}-header`}
            value={header}
            placeholder="X-Api-Key"
            autoComplete="off"
            onChange={(event) => setHeader(event.target.value)}
            disabled={busy}
          />
        </div>
      )}
      {kind !== "none" && (
        <div className="flex flex-col gap-1">
          <Label htmlFor={`${id}-value`}>{valueLabel}</Label>
          <Input
            id={`${id}-value`}
            type="password"
            value={value}
            autoComplete="off"
            placeholder={
              keepsValue ? `Leave empty to keep the one ending in ${editing?.auth_last4 ?? "????"}` : ""
            }
            onChange={(event) => setValue(event.target.value)}
            disabled={busy}
          />
          <p className="text-xs text-muted-foreground">
            Stored encrypted. Only its last 4 characters are shown again.
          </p>
        </div>
      )}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}
      <div className="flex gap-2">
        <Button type="submit" disabled={busy}>
          {busy ? "Saving…" : "Save"}
        </Button>
        <Button type="button" variant="ghost" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
      </div>
    </form>
  );
}

function ConnectorItem({
  connector,
  onUpdated,
  onRemoved,
  requireWarning,
}: {
  connector: Connector;
  onUpdated: (connector: Connector) => void;
  onRemoved: (id: string) => void;
  requireWarning: (then: () => void) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [editing, setEditing] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const operator = connector.source === "operator";

  async function run(action: () => Promise<void>, fallback: string) {
    setBusy(true);
    setError(null);
    setNote(null);
    try {
      await action();
    } catch (caught) {
      if (caught instanceof UnauthenticatedError) redirectToLogin("/settings");
      else setError(messageFor(caught, fallback));
    } finally {
      setBusy(false);
    }
  }

  function test() {
    void run(async () => {
      const tested = await testConnector(connector.id);
      onUpdated(tested);
      setNote(`The server answered with ${plural(tested.tools.length, "tool")}.`);
    }, "Could not test the connector. Try again.");
  }

  function remove() {
    void run(async () => {
      await deleteConnector(connector.id);
      onRemoved(connector.id);
    }, "Could not delete the connector. Try again.");
  }

  const labelId = useId();

  return (
    <section aria-labelledby={labelId} className="flex flex-col gap-2 rounded-lg border p-3">
      <div className="flex flex-wrap items-center gap-2">
        <h3 id={labelId} className="font-mono text-sm font-medium">
          {connector.name}
        </h3>
        {operator && <Badge variant="secondary">Set up by the operator</Badge>}
      </div>
      {connector.url && <p className="font-mono text-xs break-all">{connector.url}</p>}
      <p className="text-sm">{authText(connector)}</p>
      <p className="text-xs text-muted-foreground">
        {connector.tools_listed_at
          ? `Tools listed ${formatDate(connector.tools_listed_at)}.`
          : "Not tested yet. Test it to list its tools."}
      </p>

      {!editing && (
        <div className="flex flex-wrap gap-2">
          <Button variant="outline" size="sm" onClick={test} disabled={busy}>
            {busy ? "Working…" : "Test"}
          </Button>
          {!operator && (
            <>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  setError(null);
                  setNote(null);
                  setEditing(true);
                }}
                disabled={busy}
              >
                Edit
              </Button>
              {confirmingDelete ? (
                <>
                  <Button variant="destructive" size="sm" onClick={remove} disabled={busy}>
                    Delete {connector.name}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => setConfirmingDelete(false)}
                    disabled={busy}
                  >
                    Keep it
                  </Button>
                </>
              ) : (
                <Button
                  variant="destructive"
                  size="sm"
                  onClick={() => setConfirmingDelete(true)}
                  disabled={busy}
                >
                  Delete
                </Button>
              )}
            </>
          )}
        </div>
      )}
      {confirmingDelete && !editing && (
        <p className="text-xs text-muted-foreground">
          Deleting it also turns it off in every conversation.
        </p>
      )}
      {note && <p className="text-sm text-muted-foreground">{note}</p>}
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}

      {editing && (
        <ConnectorForm
          start={{
            key: connector.id,
            fields: {
              name: connector.name,
              url: connector.url ?? "",
              auth_kind: connector.auth_kind,
              auth_header: connector.auth_header,
            },
            editing: connector,
          }}
          onSave={async (fields) => {
            onUpdated(await changeConnector(connector.id, fields));
            setEditing(false);
          }}
          onCancel={() => setEditing(false)}
        />
      )}

      {connector.tools.length > 0 && (
        <ToolList connector={connector} onUpdated={onUpdated} requireWarning={requireWarning} />
      )}
    </section>
  );
}

/**
 * The tools from the last Test: a switch, the reads or acts select (reads is
 * offered only for a tool that may read: the server marks it read-only, or
 * the operator lists it so), and "always allow" for acts tools, which asks first.
 */
function ToolList({
  connector,
  onUpdated,
  requireWarning,
}: {
  connector: Connector;
  onUpdated: (connector: Connector) => void;
  requireWarning: (then: () => void) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<ConnectorTool | null>(null);

  async function change(tool: ConnectorTool, body: ToolChange) {
    setBusy(true);
    setError(null);
    try {
      onUpdated(await changeTool(connector.id, tool.name, body));
    } catch (caught) {
      if (caught instanceof UnauthenticatedError) redirectToLogin("/settings");
      else setError(messageFor(caught, "Could not change the tool. Try again."));
    } finally {
      setBusy(false);
    }
  }

  function switchTool(tool: ConnectorTool, enabled: boolean) {
    // An unavailable tool's name is not a valid tool name: it never goes on.
    if (enabled && !tool.available) return;
    // Switching a tool on is what lets a conversation turn the connector on.
    if (enabled) requireWarning(() => void change(tool, { enabled: true }));
    else void change(tool, { enabled: false });
  }

  return (
    <div className="flex flex-col gap-2">
      <h4 className="text-sm font-medium">Tools</h4>
      <ul aria-label={`${connector.name} tools`} className="flex flex-col gap-3">
        {connector.tools.map((tool) => {
          const shown = `${connector.name}: ${tool.name}`;
          return (
            <li key={tool.name} className="flex flex-col gap-1">
              <div className="flex flex-wrap items-center gap-2">
                <label className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    role="switch"
                    aria-label={`Use ${shown}`}
                    checked={tool.enabled}
                    disabled={busy || !tool.available}
                    onChange={(event) => switchTool(tool, event.target.checked)}
                  />
                  <span className="font-mono">{tool.name}</span>
                </label>
                <select
                  aria-label={`What ${shown} does`}
                  value={tool.acts ? "acts" : "reads"}
                  // A tool the server does not mark read-only stays acts.
                  disabled={busy || !tool.reads_allowed}
                  onChange={(event) => void change(tool, { acts: event.target.value === "acts" })}
                  className="h-7 rounded-md border bg-background px-1.5 text-xs"
                >
                  {tool.reads_allowed && <option value="reads">Reads</option>}
                  <option value="acts">Acts</option>
                </select>
                {tool.acts && (
                  <label className="flex items-center gap-1.5 text-xs">
                    <input
                      type="checkbox"
                      aria-label={`Always allow ${shown}`}
                      checked={tool.always_allow}
                      disabled={busy}
                      onChange={(event) =>
                        event.target.checked
                          ? setConfirming(tool)
                          : void change(tool, { always_allow: false })
                      }
                    />
                    Always allow
                  </label>
                )}
              </div>
              {(tool.title || tool.description) && (
                <p className="text-xs text-muted-foreground">
                  {tool.title && tool.title !== tool.name ? `${tool.title}. ` : ""}
                  {tool.description}
                </p>
              )}
              {!tool.available && (
                <p className="text-xs text-muted-foreground">
                  Unavailable: <span className="font-mono">{`${connector.name}__${tool.name}`}</span>{" "}
                  is not a valid tool name (too long or with other characters). Use a shorter
                  connector name to switch it on.
                </p>
              )}
            </li>
          );
        })}
      </ul>
      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}

      <Dialog open={confirming !== null} onOpenChange={(open) => !open && setConfirming(null)}>
        <DialogContent showCloseButton={false}>
          {confirming && (
            <>
              <DialogHeader>
                <DialogTitle>
                  Always allow {connector.name}: {confirming.name}?
                </DialogTitle>
                <DialogDescription>
                  The model will run this tool without asking you first, so it can change things
                  in the outside service on its own. Once a turn has read anything from a
                  connector, this tool still asks you first in that turn.
                </DialogDescription>
              </DialogHeader>
              <DialogFooter>
                <Button variant="outline" onClick={() => setConfirming(null)}>
                  Cancel
                </Button>
                <Button
                  onClick={() => {
                    const tool = confirming;
                    setConfirming(null);
                    void change(tool, { always_allow: true });
                  }}
                >
                  Always allow
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
}
