"use client";

import { useState } from "react";

import { ProposalGroup } from "@/components/chat/proposal-card";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { offerProposal } from "@/lib/conversations";
import type { Proposal } from "@/lib/sse";

export type HeldOffer = {
  conversationId: string;
  proposal: Proposal;
  /** The button that carries on with the action, such as "Archive now". */
  continueLabel: string;
  onContinue: () => void | Promise<void>;
};

/**
 * The proposal to show before an action, or null when there is none. A
 * failed offer does not block the action: nothing is lost, since nothing
 * was saved.
 */
export async function heldProposalFor(conversationId: string): Promise<Proposal | null> {
  try {
    const offered = await offerProposal(conversationId);
    return offered && offered.parts.some((part) => part.thoughtId === null) ? offered : null;
  } catch {
    return null;
  }
}

/** Shows the held proposal before an action, then lets the action continue. */
export function ProposalDialog({ offer, onClose }: { offer: HeldOffer | null; onClose: () => void }) {
  const [busy, setBusy] = useState(false);

  async function carryOn() {
    if (!offer) return;
    setBusy(true);
    try {
      onClose();
      await offer.onContinue();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={offer !== null} onOpenChange={(next) => !next && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Before you go on</DialogTitle>
          <DialogDescription>
            This conversation has a thought you can file. Edit it and confirm, or carry on.
          </DialogDescription>
        </DialogHeader>
        {offer && (
          <ProposalGroup
            key={offer.proposal.id}
            conversationId={offer.conversationId}
            proposal={offer.proposal}
            onlyUnsaved
          />
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button onClick={carryOn} disabled={busy}>
            {offer?.continueLabel ?? "Continue"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
