"use client";

import { useEffect, useState } from "react";

import { useDemo } from "@/components/demo/demo-context";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { apiFetch } from "@/lib/api";
import { formatWhen } from "@/lib/demo";

type ProviderNotice = { id: string; label: string; notice: string };

/**
 * What the demo stores, for how long, and who can read it, with the chosen
 * provider's own data-handling notice. With onAccept it asks the visitor to
 * accept before their first message; without, it is for reading again.
 */
export function DemoNoticeDialog({
  open,
  providerId,
  onClose,
  onAccept,
}: {
  open: boolean;
  /** The provider of the chosen model; null shows every provider's notice. */
  providerId: string | null;
  onClose: () => void;
  onAccept?: () => Promise<void>;
}) {
  const demo = useDemo();
  const [providers, setProviders] = useState<ProviderNotice[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || providers) return;
    let cancelled = false;
    apiFetch<{ providers: ProviderNotice[] }>("/api/providers")
      .then((result) => !cancelled && setProviders(result.providers))
      .catch(() => !cancelled && setProviders([]));
    return () => {
      cancelled = true;
    };
  }, [open, providers]);

  if (!demo) return null;
  const shown = (providers ?? []).filter(
    (p) => p.notice.trim() !== "" && (providerId === null || p.id === providerId),
  );

  async function accept() {
    if (!onAccept) return;
    setBusy(true);
    setError(null);
    try {
      await onAccept();
    } catch {
      setError("Could not save that you accepted the notice. Try again.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Before you use this demo</DialogTitle>
          <DialogDescription>Read what happens to what you write here.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3 text-sm">
          <p>
            This demo stores your conversations, their messages, your model settings, and your
            usage on this server, under an anonymous session in this browser. It deletes all of
            them at <strong>{formatWhen(demo.expiresAt)}</strong>, or at once when you select
            &ldquo;End demo&rdquo;.
          </p>
          <p>
            Whoever runs this server can technically read the conversations stored here. Do not
            write anything you would not share.
          </p>
          <p>
            Your API key is not stored on the server. This browser holds it in an encrypted cookie
            that page scripts cannot read, and forgets it after {demo.keyTtlMinutes} minutes
            without use or {demo.keyMaxHours} hours after you saved it, whichever comes first.
          </p>
          <p>Each message goes to the provider of the model you choose, which handles it as follows:</p>
          {providers === null ? (
            <p className="text-muted-foreground">Loading the provider&apos;s notice…</p>
          ) : shown.length === 0 ? (
            <p className="text-muted-foreground">This provider has no notice of its own.</p>
          ) : (
            <ul className="flex flex-col gap-2">
              {shown.map((provider) => (
                <li key={provider.id}>
                  <strong>{provider.label}:</strong> {provider.notice}
                </li>
              ))}
            </ul>
          )}
          {error && <p className="text-destructive">{error}</p>}
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            {onAccept ? "Not now" : "Close"}
          </Button>
          {onAccept && (
            <Button onClick={accept} disabled={busy}>
              I accept
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
