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
import { deleteMyData, logOut } from "@/lib/account";
import { ApiError } from "@/lib/api";

/**
 * "Delete my data": deletes everything stored for the user, after a
 * confirmation, then logs out. Not shown in demo mode, where "End demo" does
 * the same for the session.
 */
export function DeleteDataSection() {
  const demo = useDemo();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (demo) return null;

  async function confirmDelete() {
    setBusy(true);
    setError(null);
    try {
      await deleteMyData();
      logOut();
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Could not delete your data. Try again.");
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Delete my data</CardTitle>
        <CardDescription>
          Delete everything Focus Funnel stores about you and log out. Logging in again starts
          an empty account.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button variant="destructive" onClick={() => setOpen(true)}>
          Delete my data
        </Button>
      </CardContent>
      <Dialog open={open} onOpenChange={(next) => !next && !busy && setOpen(false)}>
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Delete all your data?</DialogTitle>
            <DialogDescription>
              Your filed thoughts and their search index, your API keys, your models and
              settings, your conversations, and your usage records are deleted for good. This
              cannot be undone.
            </DialogDescription>
          </DialogHeader>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={busy}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={confirmDelete} disabled={busy}>
              Delete everything
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
