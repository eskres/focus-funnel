"use client";

import { useState } from "react";

import { useDemo } from "@/components/demo/demo-context";
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
import {
  USAGE_DELETED,
  deleteMyAccount,
  deleteMyContent,
  deleteMyUsage,
  logOut,
} from "@/lib/account";
import { ApiError } from "@/lib/api";

type Action = {
  id: "content" | "usage" | "account";
  label: string;
  description: string;
  question: string;
  deleted: string;
  confirm: string;
  run: () => Promise<void>;
  after: () => void;
};

const ACTIONS: Action[] = [
  {
    id: "content",
    label: "Delete content",
    description: "Your filed thoughts and their search index, and your conversations.",
    question: "Delete your content?",
    deleted:
      "Your filed thoughts and their search index, and your conversations and their messages, are deleted for good. Your account, API keys, models, and usage history stay.",
    confirm: "Delete content",
    run: deleteMyContent,
    after: () => {},
  },
  {
    id: "usage",
    label: "Delete usage history",
    description: "The record of your model calls and their estimated cost.",
    question: "Delete your usage history?",
    deleted:
      "The record of every model call and its estimated cost is deleted for good. Your content, account, API keys, and models stay.",
    confirm: "Delete usage history",
    run: deleteMyUsage,
    after: () => window.dispatchEvent(new Event(USAGE_DELETED)),
  },
  {
    id: "account",
    label: "Delete account",
    description: "Everything above, plus your API keys, models, and settings, then log out.",
    question: "Delete your account?",
    deleted:
      "Your filed thoughts and their search index, your conversations, your usage history, your API keys, and your models and settings are deleted for good, and you are logged out. Logging in again starts an empty account.",
    confirm: "Delete account",
    run: deleteMyAccount,
    after: logOut,
  },
];

/**
 * "Your data": delete the content, the usage history, or the whole account,
 * each after a confirmation. Deleting the account logs out. Not shown in demo
 * mode, where "End demo" deletes the session and everything in it.
 */
export function DeleteDataSection() {
  const demo = useDemo();
  const [action, setAction] = useState<Action | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<string | null>(null);

  if (demo) return null;

  function open(chosen: Action) {
    setError(null);
    setDone(null);
    setAction(chosen);
  }

  async function confirmDelete() {
    if (!action) return;
    setBusy(true);
    setError(null);
    try {
      await action.run();
      action.after();
      if (action.id !== "account") {
        setDone(`${action.label}: done.`);
        setAction(null);
        setBusy(false);
      }
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not delete. Try again.");
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Your data</CardTitle>
        <CardDescription>Each of these deletes for good and cannot be undone.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {ACTIONS.map((item) => (
          <div key={item.id} className="flex items-center gap-4">
            {/* One width for all three; the longest label wraps onto two lines. */}
            <Button
              variant="destructive"
              className="h-auto min-h-8 w-32 py-1.5 whitespace-normal"
              onClick={() => open(item)}
            >
              {item.label}
            </Button>
            <p className="text-sm text-muted-foreground">{item.description}</p>
          </div>
        ))}
        {done && (
          <p role="status" className="text-sm text-muted-foreground">
            {done}
          </p>
        )}
      </CardContent>
      <Dialog open={action !== null} onOpenChange={(next) => !next && !busy && setAction(null)}>
        <DialogContent showCloseButton={false}>
          {action && (
            <>
              <DialogHeader>
                <DialogTitle>{action.question}</DialogTitle>
                <DialogDescription>{action.deleted} This cannot be undone.</DialogDescription>
              </DialogHeader>
              {error && <p className="text-sm text-destructive">{error}</p>}
              <DialogFooter>
                <Button variant="outline" onClick={() => setAction(null)} disabled={busy}>
                  Cancel
                </Button>
                <Button variant="destructive" onClick={confirmDelete} disabled={busy}>
                  {action.confirm}
                </Button>
              </DialogFooter>
            </>
          )}
        </DialogContent>
      </Dialog>
    </Card>
  );
}
