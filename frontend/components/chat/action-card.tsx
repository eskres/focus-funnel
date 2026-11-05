"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { ApiError } from "@/lib/api";
import { decideAction } from "@/lib/conversations";
import type { Action } from "@/lib/sse";
import { cn } from "@/lib/utils";

/** A value as the card shows it: text as it is, anything nested as JSON. */
function shown(value: unknown): { text: string; nested: boolean } {
  if (typeof value === "string") return { text: value, nested: false };
  if (typeof value === "number" || typeof value === "boolean" || value === null) {
    return { text: String(value), nested: false };
  }
  return { text: JSON.stringify(value, null, 2), nested: true };
}

function statusLine(action: Action): string {
  switch (action.status) {
    case "pending":
      return "Waiting for your approval. Nothing has been sent yet.";
    case "running":
      return "Running…";
    case "done":
      return action.errorCode === "tool_error" ? "Ran, and the tool reported an error:" : "Done.";
    case "failed":
      return "Did not run.";
    case "unknown":
      return "Sent, but it is not known whether it ran. Check before trying again.";
    case "declined":
      return "Declined. Nothing was sent.";
    case "expired":
      return "Expired: the conversation moved on, so this did not run.";
  }
}

/**
 * A connector tool call that needs the user's approval: the connector, the
 * tool, and its arguments, with Approve and Decline. Approving calls the
 * server once; declining calls nothing. A failed call can be approved again
 * until the next message expires it; one whose outcome is unknown (it may have
 * run) cannot.
 */
export function ActionCard({
  conversationId,
  action,
  canAct = true,
  onChange,
}: {
  conversationId: string | undefined;
  action: Action;
  /** False while an answer is arriving: the server refuses approvals during a turn. */
  canAct?: boolean;
  onChange: (action: Action) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const open = action.status === "pending" || action.status === "failed";
  const entries = Object.entries(action.arguments);
  const name = action.title ?? action.tool;

  async function decide(decision: "approve" | "decline") {
    if (!conversationId) return;
    const before = action;
    setError(null);
    if (decision === "approve") onChange({ ...action, status: "running" });
    try {
      onChange(await decideAction(conversationId, action.id, decision));
    } catch (err) {
      if (err instanceof ApiError && err.code === "action_expired") {
        onChange({ ...before, status: "expired" });
        return;
      }
      onChange(before);
      setError(err instanceof Error ? err.message : "Could not reach the server.");
    }
  }

  return (
    <div
      role="group"
      aria-label={`Action: ${action.connector}: ${name}`}
      data-status={action.status}
      className={cn(
        "flex w-full max-w-[85%] flex-col gap-2 rounded-lg border p-3 text-sm",
        !open && action.status !== "running" && "bg-muted/40",
      )}
    >
      <p className="text-xs font-medium text-muted-foreground">
        {action.connector}: {name}
        {action.title && action.title !== action.tool && (
          <span className="font-normal"> ({action.tool})</span>
        )}
      </p>
      {entries.length > 0 ? (
        <dl className="grid grid-cols-[max-content_1fr] gap-x-3 gap-y-1 text-xs">
          {entries.map(([key, value]) => {
            const { text, nested } = shown(value);
            return (
              <div key={key} className="contents">
                <dt className="font-medium text-muted-foreground">{key}</dt>
                <dd className="min-w-0 break-words">
                  {nested ? (
                    <pre className="overflow-x-auto rounded bg-muted p-1 font-mono text-[11px] whitespace-pre-wrap">
                      {text}
                    </pre>
                  ) : (
                    <span className="whitespace-pre-wrap">{text}</span>
                  )}
                </dd>
              </div>
            );
          })}
        </dl>
      ) : (
        <p className="text-xs text-muted-foreground">No arguments.</p>
      )}
      <p
        role="status"
        className={cn(
          "text-xs",
          action.status === "failed" || action.status === "unknown"
            ? "text-destructive"
            : "text-muted-foreground",
        )}
      >
        {statusLine(action)}
        {(action.status === "failed" || action.status === "unknown") &&
          action.result &&
          ` ${action.result}`}
      </p>
      {action.status === "done" && action.result && (
        <pre className="max-h-48 overflow-auto rounded bg-muted p-2 font-mono text-[11px] whitespace-pre-wrap">
          {action.result}
        </pre>
      )}
      {open && (
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            disabled={!canAct || !conversationId}
            onClick={() => void decide("approve")}
          >
            {action.status === "failed" ? "Approve again" : "Approve"}
          </Button>
          <Button
            size="sm"
            variant="outline"
            disabled={!canAct || !conversationId}
            onClick={() => void decide("decline")}
          >
            Decline
          </Button>
        </div>
      )}
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
