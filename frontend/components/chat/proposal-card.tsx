"use client";

import { useState } from "react";

import { useCategories } from "@/components/chat/categories-context";
import { ThoughtLink } from "@/components/chat/thought-link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { confirmProposal } from "@/lib/conversations";
import type { Proposal, ProposalPart } from "@/lib/sse";
import { cn } from "@/lib/utils";

function parseTags(text: string): string[] {
  return text
    .split(",")
    .map((tag) => tag.trim())
    .filter(Boolean);
}

/** A card: the parts it covers, and the text as the user left it. */
type Card = {
  parts: number[];
  title: string;
  summary: string;
  tags: string;
  category: string | null;
  thoughtId: string | null;
};

function cardOf(part: ProposalPart, index: number): Card {
  return {
    parts: [index],
    title: part.title,
    summary: part.summary,
    tags: part.tags.join(", "),
    category: part.category,
    thoughtId: part.thoughtId,
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
  const categories = useCategories();
  const [title, setTitle] = useState(card.title);
  const [summary, setSummary] = useState(card.summary);
  const [tags, setTags] = useState(card.tags);
  const [category, setCategory] = useState(card.category ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const thoughtId = card.thoughtId;
  const empty = !title.trim() || !summary.trim();
  // A category the user has since removed stays visible, so the card shows what it holds.
  const choices = category && !categories.includes(category) ? [...categories, category] : categories;

  async function confirm() {
    if (!conversationId || empty) return;
    setBusy(true);
    setError(null);
    try {
      const outcome = await confirmProposal(conversationId, proposalId, {
        parts: card.parts,
        title: title.trim(),
        summary: summary.trim(),
        tags: parseTags(tags),
        category: category || null,
      });
      onSaved(card.parts, outcome.thought_id);
    } catch (err) {
      // The text stays, so the user can fix the field the server named.
      setError(err instanceof Error ? err.message : "Could not save the thought.");
    } finally {
      setBusy(false);
    }
  }

  if (thoughtId) {
    return (
      <div
        role="group"
        aria-label={`Saved: ${title}`}
        className="flex flex-wrap items-center gap-2 rounded-lg border p-3 text-sm"
      >
        <span role="status" className="text-muted-foreground">
          Saved:
        </span>
        <span className="font-medium">{title}</span>
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
      <Label className="flex flex-col items-start gap-1 text-xs">
        Category
        <select
          className="rounded-md border bg-background px-2 py-1 text-sm"
          value={category}
          onChange={(event) => setCategory(event.target.value)}
        >
          <option value="">None</option>
          {choices.map((name) => (
            <option key={name} value={name}>
              {name}
            </option>
          ))}
        </select>
      </Label>
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
