"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { useDemo } from "@/components/demo/demo-context";
import { DemoNoticeDialog } from "@/components/demo/demo-notice";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { endDemo, formatWhen } from "@/lib/demo";

/** The header controls in demo mode: the expiry, the notice, and "End demo". */
export function DemoBar() {
  const demo = useDemo();
  const router = useRouter();
  const [noticeOpen, setNoticeOpen] = useState(false);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!demo) return null;

  async function confirmEnd() {
    setBusy(true);
    setError(null);
    try {
      await endDemo();
      router.replace("/demo/ended");
    } catch {
      setError("Could not end the demo. Try again.");
      setBusy(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-muted-foreground">
        Demo: your data is deleted at {formatWhen(demo.expiresAt)}
      </span>
      <Button variant="ghost" size="sm" onClick={() => setNoticeOpen(true)}>
        Demo notice
      </Button>
      <Button variant="outline" onClick={() => setConfirmOpen(true)}>
        End demo
      </Button>
      <DemoNoticeDialog open={noticeOpen} providerId={null} onClose={() => setNoticeOpen(false)} />
      <Dialog open={confirmOpen} onOpenChange={(next) => !next && !busy && setConfirmOpen(false)}>
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>End the demo now?</DialogTitle>
            <DialogDescription>
              Your conversations, settings, and usage are deleted for good, and this browser
              forgets your API key. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          {error && <p className="text-sm text-destructive">{error}</p>}
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)} disabled={busy}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={confirmEnd} disabled={busy}>
              End demo and delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
