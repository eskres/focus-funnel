"use client";

import { useEffect, useState } from "react";

import { DateFields, type DateText, dateTextOf, whenOfText } from "@/components/chat/date-fields";
import { ThoughtLink } from "@/components/chat/thought-link";
import { type FieldText, hasEmptyField, parseTags, ThoughtFields } from "@/components/chat/thought-fields";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { NotFoundError, ThoughtChangedError } from "@/lib/api";
import { confirmProposal } from "@/lib/conversations";
import { formatWhen, type When } from "@/lib/dates";
import type { Proposal, ProposalPart, Target } from "@/lib/sse";
import { THOUGHT_CHANGED_EVENT, type ThoughtChanged } from "@/lib/thoughts";
import { browserTimeZone } from "@/lib/time-zone";
import { cn } from "@/lib/utils";
import { afterParts, beforeParts, type DiffPart, wordDiff } from "@/lib/word-diff";

/**
 * A card: the parts it covers, and the text as the user left it. Once saved,
 * `savedTitle` is the thought's current title and `deleted` says it is gone.
 * `whenChoices` are two dates for the user to pick from, in place of `when`.
 * An addition names the thought it adds to (`addTo`), the version the card
 * was made from (`basedOn`), and that thought as it is now (`target`); a new
 * thought may name a strong match (`similar`) the user can add to instead.
 * A status part names the thought it marks done (`mark`), with that thought
 * as it is now in `target`.
 */
type Card = {
  parts: number[];
  title: string;
  summary: string;
  tags: string;
  category: string | null;
  when: When | null;
  whenChoices: When[] | null;
  thoughtId: string | null;
  savedTitle: string | null;
  deleted: boolean;
  addTo: string | null;
  basedOn: string | null;
  target: ProposalPart["target"];
  similar: ProposalPart["similar"];
  added: boolean;
  undone: boolean;
  mark: string | null;
};

function cardOf(part: ProposalPart, index: number): Card {
  return {
    parts: [index],
    title: part.title,
    summary: part.summary,
    tags: part.tags.join(", "),
    category: part.category,
    when: part.when,
    whenChoices: part.whenChoices,
    thoughtId: part.thoughtId,
    savedTitle: part.savedTitle,
    deleted: part.deleted,
    addTo: part.addTo,
    basedOn: part.basedOn,
    target: part.target,
    similar: part.similar,
    added: part.added,
    undone: part.undone,
    mark: part.mark,
  };
}

/**
 * Every part in one card, with no model call: the first part's title,
 * category, and date (or date choices), the summaries as paragraphs in
 * order, and every tag once.
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
    when: parts[0].when,
    whenChoices: parts[0].whenChoices,
    thoughtId: null,
    // Merged parts are saved as one thought, so the first part says how it is now.
    savedTitle: parts[0].savedTitle,
    deleted: parts[0].deleted,
    // An addition or a status part is never merged.
    addTo: null,
    basedOn: null,
    target: null,
    similar: null,
    added: false,
    undone: false,
    mark: null,
  };
}

/** Each tag once, in order: the thought's own, then the card's new ones. */
function joinTags(...lists: string[][]): string {
  const tags: string[] = [];
  for (const tag of lists.flat()) {
    if (!tags.includes(tag)) tags.push(tag);
  }
  return tags.join(", ");
}

function isTarget(target: Card["target"]): target is Target {
  return target !== null && !("deleted" in target);
}

function filedOn(value: string): string {
  return new Date(value).toLocaleDateString(undefined, { dateStyle: "medium" });
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
  // Parts saved as one thought were merged. A proposal with an addition or a
  // status part is never merged, though an addition and a mark on the same
  // thought both end with its id.
  const [merged, setMerged] = useState(
    () =>
      saved.length >= 2 &&
      saved[0] !== null &&
      saved.every((id) => id === saved[0]) &&
      proposal.parts.every((part) => !part.mark && !part.addTo),
  );
  // A status part is never offered again, so the held proposal's copy leaves it out.
  const cards = merged
    ? [{ ...mergeParts(proposal.parts), thoughtId: saved[0] }]
    : proposal.parts
        .map((part, index) => ({ ...cardOf(part, index), thoughtId: saved[index] }))
        .filter((card) => !onlyUnsaved || (!card.thoughtId && !card.mark));
  // A replaced proposal keeps its unsaved cards folded away until the user
  // asks. A status card is not replaced: it stays shown and can be confirmed.
  const [unfolded, setUnfolded] = useState(false);
  const folded = Boolean(proposal.replacedBy) && !unfolded;
  const waiting = cards.filter((card) => !card.thoughtId && !card.mark).length;
  const shown = folded ? cards.filter((card) => card.thoughtId || card.mark) : cards;
  // The cards the user turned into additions with the "Similar" hint.
  const [adding, setAdding] = useState<number[]>([]);
  // An addition adds one card to one thought, so a proposal with one is not merged.
  const canMerge =
    !folded &&
    !merged &&
    proposal.parts.length >= 2 &&
    saved.every((id) => id === null) &&
    proposal.parts.every((part) => !part.addTo && !part.mark) &&
    adding.length === 0;
  const statusOnly = proposal.parts.every((part) => part.mark);

  function onSaved(parts: number[], thoughtId: string) {
    setSaved((current) => current.map((id, index) => (parts.includes(index) ? thoughtId : id)));
  }

  function onAdding(parts: number[], add: boolean) {
    setAdding((current) =>
      add ? [...current, ...parts] : current.filter((index) => !parts.includes(index)),
    );
  }

  return (
    <section
      aria-label={
        statusOnly
          ? "Proposed status change"
          : cards.length > 1
            ? "Proposals to file"
            : "Proposal to file"
      }
      data-proposal-id={anchor ? proposal.id : undefined}
      data-marked={marked || undefined}
      className={cn(
        "flex w-full max-w-[85%] flex-col gap-2 rounded-xl transition-shadow duration-500",
        marked && "ring-2 ring-primary ring-offset-4 ring-offset-background",
      )}
    >
      {shown.map((card) =>
        card.mark ? (
          <StatusCard
            key={`mark-${card.parts.join(",")}`}
            conversationId={conversationId}
            proposalId={proposal.id}
            card={card}
            onSaved={onSaved}
          />
        ) : (
          <ProposalCard
            key={`${merged ? "merged" : "part"}-${card.parts.join(",")}`}
            conversationId={conversationId}
            proposalId={proposal.id}
            card={card}
            onSaved={onSaved}
            onAdding={onAdding}
          />
        ),
      )}
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


/**
 * The saved thought as it is now: its title once it changed, whether it is
 * gone, and, for an addition, whether it was added and undone since. An edit,
 * delete, or undo in the thought sheet shows here at once.
 */
function useSavedThought(card: Card, proposalId: string) {
  const state = useState({
    title: card.savedTitle,
    deleted: card.deleted,
    added: card.added,
    undone: card.undone,
  });
  const setNow = state[1];
  const thoughtId = card.thoughtId;

  useEffect(() => {
    if (!thoughtId) return;
    function follow(event: Event) {
      const change = (event as CustomEvent<ThoughtChanged>).detail;
      if (change?.id !== thoughtId) return;
      setNow((current) =>
        "deleted" in change
          ? { ...current, deleted: true }
          : {
              ...current,
              title: change.title,
              deleted: false,
              undone: current.undone || change.undone === proposalId,
            },
      );
    }
    window.addEventListener(THOUGHT_CHANGED_EVENT, follow);
    return () => window.removeEventListener(THOUGHT_CHANGED_EVENT, follow);
  }, [thoughtId, proposalId, setNow]);

  return state;
}

/** The confirm's 404 message for a status part whose thought is gone (design decision 7). */
const THOUGHT_GONE = "This thought no longer exists.";

/**
 * A card that marks a filed thought done: no fields, one button. It names the
 * thought as it is now, or by the title stored in the part once it is gone.
 * Only the confirm's "no longer exists" 404 says the thought is gone; any
 * other failure keeps the button, since the thought may well exist.
 */
function StatusCard({
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
  const [now, setNow] = useSavedThought(card, proposalId);
  const [gone, setGone] = useState(() => card.target !== null && "deleted" in card.target);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const thoughtId = card.thoughtId;
  const target = isTarget(card.target) ? card.target : null;
  const title = target?.title || card.title;
  const category = target ? target.category : card.category;

  async function confirm() {
    if (!conversationId) return;
    setBusy(true);
    setError(null);
    try {
      const outcome = await confirmProposal(conversationId, proposalId, { parts: card.parts });
      setNow((current) => ({ ...current, title: current.title || title, deleted: false }));
      onSaved(card.parts, outcome.thought_id);
    } catch (err) {
      // Only the confirm's own answer for a missing thought: a missing
      // conversation or proposal is a 404 too, and says nothing about the thought.
      if (err instanceof NotFoundError && err.message === THOUGHT_GONE) setGone(true);
      else setError(err instanceof Error ? err.message : "Could not mark the thought done.");
    } finally {
      setBusy(false);
    }
  }

  // The deleted state checks `deleted` before the title, which the server
  // sends as null for a gone thought.
  const shownTitle = now.title || title;

  if (thoughtId && now.deleted) {
    // The title stored in the part, never a later rename the open chat heard
    // about: the same title a reload shows (design decision 10).
    return (
      <div
        role="group"
        aria-label={`Deleted: ${card.title}`}
        className="flex flex-wrap items-center gap-2 rounded-lg border border-dashed p-3 text-sm"
      >
        <span role="status" className="text-muted-foreground">
          Deleted:
        </span>
        <span className="text-muted-foreground">{card.title}</span>
      </div>
    );
  }

  if (thoughtId) {
    return (
      <div
        role="group"
        aria-label={`Marked done: ${shownTitle}`}
        className="flex flex-wrap items-center gap-2 rounded-lg border p-3 text-sm"
      >
        <span role="status" className="text-muted-foreground">
          Marked done:
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
      aria-label={`Mark done: ${title}`}
      className="flex flex-col gap-2 rounded-lg border p-3 text-sm"
    >
      {gone ? (
        <p role="status" className="text-muted-foreground">
          This thought no longer exists.
        </p>
      ) : (
        <>
          <p className="flex flex-wrap items-center gap-2">
            <span className="text-xs font-medium text-muted-foreground">Mark done:</span>
            <span className="font-medium">{title}</span>
            {category && <Badge>{category}</Badge>}
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={confirm} disabled={busy || !conversationId}>
              Mark done
            </Button>
            {error && (
              <p role="alert" className="text-xs text-destructive">
                {error}
              </p>
            )}
          </div>
        </>
      )}
    </div>
  );
}

/** The fields as the card first shows them: an addition starts from the thought it adds to. */
function startText(card: Card): FieldText {
  const target = isTarget(card.target) ? card.target : null;
  return {
    title: card.title,
    summary: card.summary,
    tags: target ? joinTags(target.tags, parseTags(card.tags)) : card.tags,
    category: card.category ?? target?.category ?? "",
  };
}

/**
 * One card: a thought to file, or an addition to a filed thought. An
 * addition shows the thought's summary now beside the proposed one, with
 * removed and added words marked as the user edits, and never its title.
 */
function ProposalCard({
  conversationId,
  proposalId,
  card,
  onSaved,
  onAdding,
}: {
  conversationId: string | undefined;
  proposalId: string;
  card: Card;
  onSaved: (parts: number[], thoughtId: string) => void;
  onAdding: (parts: number[], add: boolean) => void;
}) {
  const [text, setText] = useState<FieldText>(() => startText(card));
  // What the card adds to: the model's target, or the match the user picked
  // from the hint; null while it files a new thought.
  const [addition, setAddition] = useState<{
    id: string;
    basedOn: string | null;
    target: Card["target"];
  } | null>(() => (card.addTo ? { id: card.addTo, basedOn: card.basedOn, target: card.target } : null));
  // The date as fields: the proposed one, or none ("Add date"). With two
  // choices, nothing until the user picks one or "No date".
  const [date, setDate] = useState<DateText | null>(() => (card.whenChoices ? null : dateTextOf(card.when)));
  // The choice picked: its index, "none" for "No date", or null before a pick.
  const [pick, setPick] = useState<number | "none" | null>(null);
  // An addition keeps its thought's date, so it has no date to pick.
  const mustPick = !addition && Boolean(card.whenChoices) && pick === null;
  const [now, setNow] = useSavedThought(card, proposalId);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const thoughtId = card.thoughtId;
  const target = addition && isTarget(addition.target) ? addition.target : null;
  const empty = addition ? !text.summary.trim() : hasEmptyField(text);

  function choose(choice: number | "none") {
    setPick(choice);
    setDate(choice === "none" ? null : dateTextOf(card.whenChoices?.[choice]));
  }

  async function confirm() {
    if (!conversationId || empty || mustPick) return;
    setBusy(true);
    setError(null);
    try {
      const outcome = await confirmProposal(conversationId, proposalId, {
        parts: card.parts,
        title: target ? target.title : text.title.trim(),
        summary: text.summary.trim(),
        tags: parseTags(text.tags),
        category: text.category || null,
        ...(addition
          ? {
              mode: "add" as const,
              add_to: addition.id,
              // The version the Now column shows, as the server sent it.
              ...(addition.basedOn ? { based_on: addition.basedOn } : {}),
            }
          : {
              // Always sent for a new thought, with the browser's zone: null
              // is "no date". An addition keeps its thought's date.
              when: whenOfText(date, browserTimeZone()),
            }),
      });
      if (addition) setNow((current) => ({ ...current, title: target?.title ?? null, added: true }));
      onSaved(card.parts, outcome.thought_id);
    } catch (err) {
      if (addition && err instanceof NotFoundError) {
        // The thought is gone: the card says so and can still be filed as new.
        setAddition({ ...addition, target: { deleted: true } });
        return;
      }
      if (addition && err instanceof ThoughtChangedError) {
        // Someone changed the thought: show it as it is now, and confirm against that.
        const changed = err.details.thought as
          | { title: string; summary: string; tags: string[]; category: string | null; updated_at: string }
          | undefined;
        if (changed) {
          setAddition({
            ...addition,
            basedOn: changed.updated_at,
            target: {
              title: changed.title,
              summary: changed.summary,
              tags: changed.tags,
              category: changed.category,
              createdAt: target?.createdAt ?? changed.updated_at,
              updatedAt: changed.updated_at,
            },
          });
        }
      }
      // The text stays, so the user can fix the field the server named.
      setError(err instanceof Error ? err.message : "Could not save the thought.");
    } finally {
      setBusy(false);
    }
  }

  /** The "Similar" hint: add this card to the match, after its current summary. */
  function addToMatch() {
    const match = card.similar;
    if (!match) return;
    setAddition({ id: match.thoughtId, basedOn: match.updatedAt, target: match });
    setText({
      title: match.title,
      summary: `${match.summary}\n\n${text.summary}`.trim(),
      tags: joinTags(match.tags, parseTags(text.tags)),
      category: text.category || match.category || "",
    });
    setError(null);
    onAdding(card.parts, true);
  }

  /** A normal card for a new thought: the model's addition keeps the user's edits. */
  function fileAsNew() {
    setAddition(null);
    setError(null);
    if (card.addTo) {
      setText((current) => ({ ...current, title: card.title }));
    } else {
      // Back from the hint: the card as the model proposed it.
      setText(startText(card));
      onAdding(card.parts, false);
    }
  }

  const shownTitle = now.title ?? (target ? target.title : text.title);

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
    const label = now.undone ? "Addition undone:" : now.added ? "Added to:" : "Saved:";
    return (
      <div
        role="group"
        aria-label={`${label} ${shownTitle}`}
        className="flex flex-wrap items-center gap-2 rounded-lg border p-3 text-sm"
      >
        <span role="status" className="text-muted-foreground">
          {label}
        </span>
        <span className="font-medium">{shownTitle}</span>
        <ThoughtLink id={thoughtId} className="text-xs">
          Open
        </ThoughtLink>
      </div>
    );
  }

  if (addition) {
    return (
      <div
        role="group"
        aria-label={`Addition: ${target?.title ?? card.title}`}
        className="flex flex-col gap-2 rounded-lg border p-3"
      >
        {target ? (
          <>
            <p className="text-sm">
              <span className="text-xs font-medium text-muted-foreground">Add to: </span>
              <span className="font-medium">{target.title}</span>
            </p>
            <AdditionSummary
              now={target.summary}
              after={text.summary}
              onChange={(summary) => setText({ ...text, summary })}
            />
            <ThoughtFields
              value={text}
              onChange={setText}
              keep={target.category}
              fields={["tags", "category"]}
            />
          </>
        ) : (
          <p className="text-sm text-muted-foreground">
            The thought this adds to no longer exists. File it as a new thought instead.
          </p>
        )}
        <div className="flex flex-wrap items-center gap-2">
          {target && (
            <Button size="sm" onClick={confirm} disabled={busy || empty || !conversationId}>
              Add
            </Button>
          )}
          <Button size="sm" variant="outline" onClick={fileAsNew} disabled={busy}>
            File as new
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

  return (
    <div
      role="group"
      aria-label={`Thought to file: ${card.title}`}
      className="flex flex-col gap-2 rounded-lg border p-3"
    >
      <p className="text-xs font-medium text-muted-foreground">A thought to file</p>
      {card.similar && (
        <div
          role="note"
          aria-label="Similar thought"
          className="flex flex-wrap items-center gap-2 rounded-md bg-muted px-2 py-1.5 text-xs"
        >
          <span>
            Similar: <span className="font-medium">{card.similar.title}</span>, filed{" "}
            {filedOn(card.similar.createdAt)}
          </span>
          <Button size="xs" variant="outline" onClick={addToMatch}>
            Add to it instead
          </Button>
        </div>
      )}
      <ThoughtFields value={text} onChange={setText} />
      {card.whenChoices && (
        <div role="group" aria-label="Which date?" className="flex flex-col gap-1">
          <p className="text-xs font-medium">Which date did you mean?</p>
          <div className="flex flex-wrap gap-2">
            {card.whenChoices.map((choice, index) => (
              <Button
                key={index}
                type="button"
                size="sm"
                variant={pick === index ? "default" : "outline"}
                aria-pressed={pick === index}
                disabled={busy}
                onClick={() => choose(index)}
              >
                {formatWhen(choice, { year: false })}
              </Button>
            ))}
            <Button
              type="button"
              size="sm"
              variant={pick === "none" ? "default" : "outline"}
              aria-pressed={pick === "none"}
              disabled={busy}
              onClick={() => choose("none")}
            >
              No date
            </Button>
          </div>
        </div>
      )}
      {/* With two choices, the fields come once the user picked, to adjust the date. */}
      {!mustPick && <DateFields value={date} onChange={setDate} disabled={busy} />}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" onClick={confirm} disabled={busy || empty || mustPick || !conversationId}>
          Confirm
        </Button>
        {mustPick && <p className="text-xs text-muted-foreground">Pick a date, or No date.</p>}
        {error && (
          <p role="alert" className="text-xs text-destructive">
            {error}
          </p>
        )}
      </div>
    </div>
  );
}

function Marked({ parts }: { parts: DiffPart[] }) {
  return (
    <>
      {parts.map((part, index) =>
        part.kind === "removed" ? (
          <del key={index} className="bg-destructive/15 text-destructive">
            {part.text}
          </del>
        ) : part.kind === "added" ? (
          <ins key={index} className="bg-primary/15 no-underline">
            {part.text}
          </ins>
        ) : (
          <span key={index}>{part.text}</span>
        ),
      )}
    </>
  );
}

/**
 * Now and After side by side on wide screens, stacked on narrow ones: the
 * summary now, with the words the addition removes marked, and the proposed
 * summary to edit, with the words it adds marked below it.
 */
function AdditionSummary({
  now,
  after,
  onChange,
}: {
  now: string;
  after: string;
  onChange: (summary: string) => void;
}) {
  const parts = wordDiff(now, after);
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      <section aria-label="Now" className="flex flex-col gap-1 text-xs">
        <h4 className="font-medium text-muted-foreground">Now</h4>
        <p className="whitespace-pre-wrap rounded-md border bg-muted/40 p-2 text-sm">
          <Marked parts={beforeParts(parts)} />
        </p>
      </section>
      <div className="flex flex-col gap-1 text-xs">
        <Label className="flex flex-col items-start gap-1 text-xs">
          After
          <Textarea value={after} onChange={(event) => onChange(event.target.value)} />
        </Label>
        <p aria-label="Changes" className="whitespace-pre-wrap rounded-md border p-2 text-sm">
          <Marked parts={afterParts(parts)} />
        </p>
      </div>
    </div>
  );
}
