"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { confirmProposal, type ConfirmOutcome } from "@/lib/conversations";
import type { Proposal } from "@/lib/sse";

function parseTags(text: string): string[] {
  return text
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}

/**
 * A proposed thought the user can edit and confirm. Nothing is saved until
 * they confirm, and the conversation can carry on without it.
 */
export function ProposalCard({
  conversationId,
  proposal,
}: {
  conversationId: string | undefined;
  proposal: Proposal;
}) {
  const [title, setTitle] = useState(proposal.title);
  const [summary, setSummary] = useState(proposal.summary);
  const [tags, setTags] = useState(proposal.tags.join(", "));
  const [busy, setBusy] = useState(false);
  const [outcome, setOutcome] = useState<ConfirmOutcome | null>(null);
  const [error, setError] = useState<string | null>(null);
  const empty = !title.trim() || !summary.trim();

  async function confirm() {
    if (!conversationId || empty) return;
    setBusy(true);
    setError(null);
    try {
      setOutcome(
        await confirmProposal(conversationId, {
          title: title.trim(),
          summary: summary.trim(),
          tags: parseTags(tags),
        }),
      );
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not confirm the proposal.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section
      aria-label="Proposal to file"
      className="flex w-full max-w-[85%] flex-col gap-2 rounded-lg border p-3"
    >
      <p className="text-xs font-medium text-muted-foreground">A thought to file</p>
      <Label className="flex flex-col items-start gap-1 text-xs">
        Title
        <Input value={title} onChange={(event) => setTitle(event.target.value)} />
      </Label>
      <Label className="flex flex-col items-start gap-1 text-xs">
        Summary
        <Textarea value={summary} onChange={(event) => setSummary(event.target.value)} />
      </Label>
      <Label className="flex flex-col items-start gap-1 text-xs">
        Tags, separated by commas
        <Input value={tags} onChange={(event) => setTags(event.target.value)} />
      </Label>
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={confirm} disabled={busy || empty || !conversationId || outcome?.saved}>
          Confirm
        </Button>
        {outcome && (
          <p role="status" className="text-xs text-muted-foreground">
            {outcome.message}
          </p>
        )}
        {error && <p className="text-xs text-destructive">{error}</p>}
      </div>
    </section>
  );
}
