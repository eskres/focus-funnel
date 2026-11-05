"use client";

import { type ReactNode, useState } from "react";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/**
 * Asks before something is deleted for good. Opened only by the user. By
 * default it asks about a conversation; `heading`, `description`, and
 * `failure` word it for something else, such as a thought, and `action`
 * names its button for another change that asks first, such as an undo.
 */
export function DeleteDialog({
  title,
  open,
  onCancel,
  onConfirm,
  heading = "Delete this conversation?",
  description,
  failure = "Could not delete the conversation.",
  action = "Delete",
}: {
  /** The name of what is deleted. */
  title: string;
  open: boolean;
  onCancel: () => void;
  onConfirm: () => Promise<void>;
  heading?: string;
  description?: ReactNode;
  /** Shown when the delete fails with no message of its own. */
  failure?: string;
  /** The confirm button's label. */
  action?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [wasOpen, setWasOpen] = useState(open);

  // Each opening starts clean: a failure from an earlier try is not shown again.
  if (open !== wasOpen) {
    setWasOpen(open);
    if (open) setError(null);
  }

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await onConfirm();
    } catch (err) {
      setError(err instanceof Error ? err.message : failure);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onCancel()}>
      <DialogContent showCloseButton={false}>
        <DialogHeader>
          <DialogTitle>{heading}</DialogTitle>
          <DialogDescription>
            {description ?? (
              <>“{title}” and all of its messages are deleted for good. This cannot be undone.</>
            )}
          </DialogDescription>
        </DialogHeader>
        {error && (
          <p role="alert" className="text-sm text-destructive">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={confirm} disabled={busy}>
            {action}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
