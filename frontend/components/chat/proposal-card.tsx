"use client";

import { useEffect, useState } from "react";

import { ThoughtLink } from "@/components/chat/thought-link";
import { type FieldText, hasEmptyField, parseTags, ThoughtFields } from "@/components/chat/thought-fields";
import { Button } from "@/components/ui/button";
import { confirmProposal } from "@/lib/conversations";
import type { Proposal, ProposalPart } from "@/lib/sse";
import { THOUGHT_CHANGED_EVENT, type ThoughtChanged } from "@/lib/thoughts";
import { cn } from "@/lib/utils";

/**
 * A card: the parts it covers, and the text as the user left it. Once saved,
 * `savedTitle` is the thought's current title and `deleted` says it is gone.
 */
type Card = {
  parts: number[];
  title: string;
  summary: string;
  tags: string;
  category: string | null;
  thoughtId: string | null;
  savedTitle: string | null;
  deleted: boolean;
};

function cardOf(part: ProposalPart, index: number): Card {
  return {
    parts: [index],
    title: part.title,
    summary: part.summary,
    tags: part.tags.join(", "),
    category: part.category,
    thoughtId: part.thoughtId,
    savedTitle: part.savedTitle,
    deleted: part.deleted,
  };
}

/**
 * Every part in one card, with no model call: the first part's title and
 * category, the summaries as paragraphs in order, and every tag once.
 */
export function mergeParts(parts: ProposalPart[]): Card {
  const tags: string[] = [];
  for (const tag of parts.flatMap((part) => part.tags)) {
    if (!tags.includes(tag)) tags.push(tag);
  }
  return {
    parts: parts.map((_, index) => index),
    title: parts[0].title,
    summary: parts.map((part) => part.summary).join("\n\n"),
    tags: tags.join(", "),
    category: parts[0].category,
    thoughtId: null,
    // Merged parts are saved as one thought, so the first part says how it is now.
    savedTitle: parts[0].savedTitle,
    deleted: parts[0].deleted,
  };
}

/**
 * The cards of one proposal: one per part, confirmed one by one, or merged
 * into one card before any is saved. Nothing is saved until the user
 * confirms, and the conversation can carry on without it.
 */
export function ProposalGroup({
  conversationId,
  proposal,
  onlyUnsaved = false,
  anchor = false,
  marked = false,
}: {
  conversationId: string | undefined;
  proposal: Proposal;
  /** Leave out the parts already saved, as when a held proposal is offered again. */
  onlyUnsaved?: boolean;
  /** In the message list, so a thought's origin can scroll to it. The held-proposal dialog's copy is not. */
  anchor?: boolean;
  /** Ringed for a moment after an origin opened it. */
  marked?: boolean;
}) {
  const [saved, setSaved] = useState<(string | null)[]>(() =>
    proposal.parts.map((part) => part.thoughtId),
  );
  // Parts saved as one thought were merged.
  const [merged, setMerged] = useState(
    () => saved.length >= 2 && saved[0] !== null && saved.every((id) => id === saved[0]),
  );
  const cards = merged
    ? [{ ...mergeParts(proposal.parts), thoughtId: saved[0] }]
    : proposal.parts
        .map((part, index) => ({ ...cardOf(part, index), thoughtId: saved[index] }))
        .filter((card) => !onlyUnsaved || !card.thoughtId);
  // A replaced proposal keeps its unsaved cards folded away until the user asks.
  const [unfolded, setUnfolded] = useState(false);
  const folded = Boolean(proposal.replacedBy) && !unfolded;
  const waiting = cards.filter((card) => !card.thoughtId).length;
  const shown = folded ? cards.filter((card) => card.thoughtId) : cards;
  const canMerge =
    !folded && !merged && proposal.parts.length >= 2 && saved.every((id) => id === null);

  function onSaved(parts: number[], thoughtId: string) {
    setSaved((current) => current.map((id, index) => (parts.includes(index) ? thoughtId : id)));
  }

  return (
    <section
      aria-label={cards.length > 1 ? "Proposals to file" : "Proposal to file"}
      data-proposal-id={anchor ? proposal.id : undefined}
      data-marked={marked || undefined}
      className={cn(
        "flex w-full max-w-[85%] flex-col gap-2 rounded-xl transition-shadow duration-500",
        marked && "ring-2 ring-primary ring-offset-4 ring-offset-background",
      )}
    >
      {shown.map((card) => (
        <ProposalCard
          key={`${merged ? "merged" : "part"}-${card.parts.join(",")}`}
          conversationId={conversationId}
          proposalId={proposal.id}
          card={card}
          onSaved={onSaved}
        />
      ))}
      {folded && waiting > 0 && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed p-2 text-xs text-muted-foreground">
          <span>
            {waiting === 1 ? "A thought to file was" : `${waiting} thoughts to file were`} replaced by a
            newer proposal.
          </span>
          <Button variant="ghost" size="xs" onClick={() => setUnfolded(true)}>
            Show
          </Button>
        </div>
      )}
      {canMerge && (
        <Button variant="outline" size="sm" className="self-start" onClick={() => setMerged(true)}>
          Merge into one
        </Button>
      )}
    </section>
  );
}

function ProposalCard({
  conversationId,
  proposalId,
  card,
  onSaved,
}: {
  conversationId: string | undefined;
  proposalId: string;
  card: Card;
  onSaved: (parts: number[], thoughtId: string) => void;
}) {
  const [text, setText] = useState<FieldText>(() => ({
    title: card.title,
    summary: card.summary,
    tags: card.tags,
    category: card.category ?? "",
  }));
  // The saved thought as it is now: its title once it changed, and whether it is gone.
  const [now, setNow] = useState({ title: card.savedTitle, deleted: card.deleted });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const thoughtId = card.thoughtId;
  const empty = hasEmptyField(text);

  // An edit or a delete in the thought sheet shows here at once.
  useEffect(() => {
    if (!thoughtId) return;
    function follow(event: Event) {
      const change = (event as CustomEvent<ThoughtChanged>).detail;
      if (change?.id !== thoughtId) return;
      setNow((current) =>
        "deleted" in change ? { ...current, deleted: true } : { title: change.title, deleted: false },
      );
    }
    window.addEventListener(THOUGHT_CHANGED_EVENT, follow);
    return () => window.removeEventListener(THOUGHT_CHANGED_EVENT, follow);
  }, [thoughtId]);

  async function confirm() {
    if (!conversationId || empty) return;
    setBusy(true);
    setError(null);
    try {
      const outcome = await confirmProposal(conversationId, proposalId, {
        parts: card.parts,
        title: text.title.trim(),
        summary: text.summary.trim(),
        tags: parseTags(text.tags),
        category: text.category || null,
      });
      onSaved(card.parts, outcome.thought_id);
    } catch (err) {
      // The text stays, so the user can fix the field the server named.
      setError(err instanceof Error ? err.message : "Could not save the thought.");
    } finally {
      setBusy(false);
    }
  }

  const shownTitle = now.title ?? text.title;

  if (thoughtId && now.deleted) {
    return (
      <div
        role="group"
        aria-label={`Deleted: ${shownTitle}`}
        className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed p-3 text-sm"
      >
        <span role="status" className="text-muted-foreground">
          Deleted:
        </span>
        <span className="text-muted-foreground">{shownTitle}</span>
      </div>
    );
  }

  if (thoughtId) {
    return (
      <div
        role="group"
        aria-label={`Saved: ${shownTitle}`}
        className="flex flex-wrap items-center gap-2 rounded-lg border p-3 text-sm"
      >
        <span role="status" className="text-muted-foreground">
          Saved:
        </span>
        <span className="font-medium">{shownTitle}</span>
        <ThoughtLink id={thoughtId} className="text-xs">
          Open
        </ThoughtLink>
      </div>
    );
  }

  return (
    <div
      role="group"
      aria-label={`Thought to file: ${card.title}`}
      className="flex flex-col gap-2 rounded-lg border p-3"
    >
      <p className="text-xs font-medium text-muted-foreground">A thought to file</p>
      <ThoughtFields value={text} onChange={setText} />
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={confirm} disabled={busy || empty || !conversationId}>
          Confirm
        </Button>
        {error && (
          <p role="alert" className="text-xs text-destructive">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}
