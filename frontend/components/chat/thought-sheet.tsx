"use client";

import { useRouter } from "next/navigation";
import { type MouseEvent, useEffect, useRef, useState } from "react";

import { DateFields, type DateText, dateTextOf, sameWhen, whenOfText } from "@/components/chat/date-fields";
import { DeleteDialog } from "@/components/chat/delete-dialog";
import {
  type FieldText,
  hasEmptyField,
  parseTags,
  ThoughtFields,
} from "@/components/chat/thought-fields";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { NotFoundError, UnauthenticatedError } from "@/lib/api";
import { formatWhen } from "@/lib/dates";
import { redirectToLogin } from "@/lib/redirect-to-login";
import {
  closeThought,
  isOpenConversation,
  openOriginHere,
  originHref,
  useOpenThought,
} from "@/lib/thought-link";
import { browserTimeZone } from "@/lib/time-zone";
import {
  deleteThought,
  getThought,
  type Thought,
  type ThoughtAddition,
  type ThoughtChange,
  type ThoughtOrigin,
  undoAddition,
  updateThought,
} from "@/lib/thoughts";

type Loaded =
  | { id: string; state: "ready"; thought: Thought }
  | { id: string; state: "gone" }
  | { id: string; state: "failed"; message: string };

/** A moment the server stamped (filed, changed, proposed), in the browser's zone. */
function stamp(value: string): string {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/**
 * The thought named in the address (`?thought=<id>`), in a sheet over the
 * chat, with Edit and Delete. Closing it, or Back, leaves the chat as it was
 * and drops an unsaved edit.
 */
export function ThoughtSheet() {
  const id = useOpenThought();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  // The open thought for a save or delete that answers later: by then the
  // user may have opened another thought, closed the sheet, or gone Back.
  const openId = useRef(id);

  useEffect(() => {
    openId.current = id;
  }, [id]);

  useEffect(() => {
    if (!id) return;
    let cancelled = false;
    getThought(id)
      .then((thought) => !cancelled && setLoaded({ id, state: "ready", thought }))
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof UnauthenticatedError) {
          redirectToLogin(window.location.pathname + window.location.search);
          return;
        }
        setLoaded(
          error instanceof NotFoundError
            ? { id, state: "gone" }
            : { id, state: "failed", message: "The thought could not be loaded. Try again." },
        );
      });
    return () => {
      cancelled = true;
    };
  }, [id]);

  const current = loaded?.id === id ? loaded : null;
  const thought = current?.state === "ready" ? current.thought : null;

  return (
    // Not modal and with no overlay: the chat stays readable and usable beside it.
    <Sheet open={id !== null} modal={false} onOpenChange={(open) => !open && closeThought()}>
      <SheetContent side="right" showOverlay={false} className="w-full overflow-y-auto sm:max-w-lg">
        <SheetHeader>
          <SheetTitle>{thought?.title ?? "Thought"}</SheetTitle>
          {/* The thought's own date, as written, apart from when it was filed and changed. */}
          {thought?.when && <p className="text-sm">When: {formatWhen(thought.when)}</p>}
          <SheetDescription>
            {thought
              ? `Filed ${stamp(thought.created_at)} · changed ${stamp(thought.updated_at)}`
              : current?.state === "gone"
                ? "This thought no longer exists."
                : current?.state === "failed"
                  ? current.message
                  : "Loading…"}
          </SheetDescription>
        </SheetHeader>
        {thought && (
          // Only while the thought is shown: a close, Back, or another thought
          // unmounts it, so its edit is dropped.
          <ThoughtBody
            key={thought.id}
            thought={thought}
            // Each answer replaces only its own thought's state, so a late
            // answer never takes the place of another thought shown since.
            onSaved={(saved) =>
              setLoaded((now) => (now?.id === saved.id ? { id: saved.id, state: "ready", thought: saved } : now))
            }
            onDeleted={() => {
              // Marked gone, so its old address never shows the deleted copy.
              setLoaded((now) => (now?.id === thought.id ? { id: thought.id, state: "gone" } : now));
              if (openId.current === thought.id) closeThought();
            }}
          />
        )}
      </SheetContent>
    </Sheet>
  );
}

function textOf(thought: Thought): FieldText {
  return {
    title: thought.title,
    summary: thought.summary,
    tags: thought.tags.join(", "),
    category: thought.category ?? "",
  };
}

function sameTags(a: string[], b: string[]): boolean {
  return a.length === b.length && a.every((tag, index) => tag === b[index]);
}

/**
 * Only the fields the user changed, so an unchanged field is never sent. A
 * changed date goes with the browser's zone; a cleared one as null.
 */
function changesOf(thought: Thought, text: FieldText, date: DateText | null): ThoughtChange {
  const change: ThoughtChange = {};
  const title = text.title.trim();
  const summary = text.summary.trim();
  const tags = parseTags(text.tags);
  const category = text.category || null;
  if (title !== thought.title) change.title = title;
  if (summary !== thought.summary) change.summary = summary;
  if (!sameTags(tags, thought.tags)) change.tags = tags;
  if (category !== thought.category) change.category = category;
  const when = whenOfText(date, browserTimeZone());
  if (!sameWhen(when, thought.when)) change.when = when;
  return change;
}

/** The empty fields a save needs, named, while Save is off. */
function emptyNote(text: FieldText): string | null {
  if (!text.title.trim()) return "Title must not be empty.";
  if (!text.summary.trim()) return "Summary must not be empty.";
  return null;
}

/**
 * The thought's fields in view mode, or as fields in edit mode, with Edit and
 * Delete. The origin and the raw text stay read-only in both.
 */
function ThoughtBody({
  thought,
  onSaved,
  onDeleted,
}: {
  thought: Thought;
  onSaved: (thought: Thought) => void;
  onDeleted: () => void;
}) {
  const [text, setText] = useState<FieldText | null>(null);
  const [date, setDate] = useState<DateText | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [undoing, setUndoing] = useState(false);
  const additions = thought.additions ?? [];
  // Only the newest addition can be undone, and only once: every undo changes
  // the thought, so an older one could not be undone after it anyway.
  const lastAddition = additions[0] && !additions[0].undone ? additions[0] : null;
  const rawText = thought.raw_text?.trim();
  const showRaw = Boolean(rawText) && rawText !== thought.summary.trim();

  function edit() {
    setText(textOf(thought));
    setDate(dateTextOf(thought.when));
    setError(null);
  }

  function cancel() {
    setText(null);
    setError(null);
  }

  async function save() {
    if (!text || hasEmptyField(text)) return;
    const change = changesOf(thought, text, date);
    if (Object.keys(change).length === 0) {
      cancel();
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const saved = await updateThought(thought.id, change);
      setText(null);
      onSaved(saved);
    } catch (err) {
      // The text stays, so the user can fix the field the server named.
      setError(err instanceof Error ? err.message : "Could not save the thought.");
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    await deleteThought(thought.id);
    setDeleting(false);
    onDeleted();
  }

  /** A refusal (409, the thought changed since) throws, and the dialog shows why. */
  async function undo() {
    if (!lastAddition) return;
    const restored = await undoAddition(thought.id, lastAddition);
    setUndoing(false);
    onSaved(restored);
  }

  const note = text && emptyNote(text);

  return (
    <div className="flex flex-col gap-4 px-4 pb-6">
      {text ? (
        <section aria-label="Edit thought" className="flex flex-col gap-2">
          <ThoughtFields value={text} onChange={setText} keep={thought.category} />
          <DateFields value={date} onChange={setDate} disabled={busy} />
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" onClick={save} disabled={busy || Boolean(note)}>
              Save
            </Button>
            <Button size="sm" variant="outline" onClick={cancel} disabled={busy}>
              Cancel
            </Button>
          </div>
          {note && <p className="text-xs text-muted-foreground">{note}</p>}
          {error && (
            <p role="alert" className="text-xs text-destructive">
              {error}
            </p>
          )}
        </section>
      ) : (
        <>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant="outline" onClick={edit}>
              Edit
            </Button>
            <Button size="sm" variant="outline" onClick={() => setDeleting(true)}>
              Delete
            </Button>
            {lastAddition && (
              <Button size="sm" variant="outline" onClick={() => setUndoing(true)}>
                Undo last addition
              </Button>
            )}
          </div>
          {(thought.category || thought.tags.length > 0) && (
            <div className="flex flex-wrap items-center gap-1" aria-label="Category and tags">
              {thought.category && <Badge>{thought.category}</Badge>}
              {thought.tags.map((tag) => (
                <Badge key={tag} variant="outline">
                  #{tag}
                </Badge>
              ))}
            </div>
          )}
          <section aria-label="Summary">
            <h3 className="mb-1 text-xs font-medium text-muted-foreground">Summary</h3>
            <p className="whitespace-pre-wrap">{thought.summary}</p>
          </section>
        </>
      )}
      {thought.origin && <Origin origin={thought.origin} />}
      {additions.length > 0 && <Additions additions={additions} />}
      {showRaw && (
        <section aria-label="Raw text">
          <h3 className="mb-1 text-xs font-medium text-muted-foreground">Raw text</h3>
          <p className="whitespace-pre-wrap text-muted-foreground">{rawText}</p>
        </section>
      )}
      {/* Inside the sheet, so the sheet takes it as its own and stays open behind it. */}
      <DeleteDialog
        title={thought.title}
        open={deleting}
        onCancel={() => setDeleting(false)}
        onConfirm={remove}
        heading="Delete this thought?"
        description={<>“{thought.title}” is deleted for good. This cannot be undone.</>}
        failure="Could not delete the thought."
      />
      {lastAddition && (
        <DeleteDialog
          title={thought.title}
          open={undoing}
          onCancel={() => setUndoing(false)}
          onConfirm={undo}
          heading="Undo the last addition?"
          description={
            <>
              The summary, tags, and category go back to what they were before the addition from “
              {lastAddition.conversation_title}”.
            </>
          }
          failure="Could not undo the addition."
          action="Undo"
        />
      )}
    </div>
  );
}

/**
 * A link to a conversation at one proposal card. It is a real link, so it can
 * be copied; a plain click in the conversation it names stays on this page.
 */
function CardLink({
  conversationId,
  proposalId,
  children,
}: {
  conversationId: string;
  proposalId: string;
  children: string;
}) {
  const router = useRouter();
  const href = originHref(conversationId, proposalId);

  function open(event: MouseEvent<HTMLAnchorElement>) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    if (isOpenConversation(conversationId)) {
      openOriginHere(conversationId, proposalId);
    } else {
      router.push(href);
    }
  }

  return (
    <a href={href} onClick={open} className="text-primary underline-offset-4 hover:underline">
      {children}
    </a>
  );
}

/** Where the thought was saved from. */
function Origin({ origin }: { origin: ThoughtOrigin }) {
  return (
    <section aria-label="Origin">
      <h3 className="mb-1 text-xs font-medium text-muted-foreground">From</h3>
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
        <CardLink conversationId={origin.conversation_id} proposalId={origin.proposal_id}>
          {origin.conversation_title}
        </CardLink>
        <span className="text-muted-foreground">proposed {stamp(origin.proposed_at)}</span>
        {origin.archived && <Badge variant="outline">Archived</Badge>}
      </p>
    </section>
  );
}

/** Where the thought grew, newest first, each linked to its card. */
function Additions({ additions }: { additions: ThoughtAddition[] }) {
  return (
    <section aria-label="Additions">
      <h3 className="mb-1 text-xs font-medium text-muted-foreground">Added to from</h3>
      <ul className="flex flex-col gap-1">
        {additions.map((addition) => (
          <li key={addition.id} className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
            <CardLink conversationId={addition.conversation_id} proposalId={addition.proposal_id}>
              {addition.conversation_title}
            </CardLink>
            <span className="text-muted-foreground">added {stamp(addition.added_at)}</span>
            {addition.undone && <Badge variant="outline">Undone</Badge>}
          </li>
        ))}
      </ul>
    </section>
  );
}
