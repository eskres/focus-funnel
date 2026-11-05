"use client";

import { useRouter } from "next/navigation";
import { type MouseEvent, useEffect, useState } from "react";

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
import { redirectToLogin } from "@/lib/redirect-to-login";
import {
  closeThought,
  isOpenConversation,
  openOriginHere,
  originHref,
  useOpenThought,
} from "@/lib/thought-link";
import {
  deleteThought,
  getThought,
  type Thought,
  type ThoughtChange,
  type ThoughtOrigin,
  updateThought,
} from "@/lib/thoughts";

type Loaded =
  | { id: string; state: "ready"; thought: Thought }
  | { id: string; state: "gone" }
  | { id: string; state: "failed"; message: string };

function when(value: string): string {
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
          <SheetDescription>
            {thought
              ? `Filed ${when(thought.created_at)} · changed ${when(thought.updated_at)}`
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
            onSaved={(saved) => setLoaded({ id: saved.id, state: "ready", thought: saved })}
            onDeleted={() => {
              setLoaded({ id: thought.id, state: "gone" });
              closeThought();
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

/** Only the fields the user changed, so an unchanged field is never sent. */
function changesOf(thought: Thought, text: FieldText): ThoughtChange {
  const change: ThoughtChange = {};
  const title = text.title.trim();
  const summary = text.summary.trim();
  const tags = parseTags(text.tags);
  const category = text.category || null;
  if (title !== thought.title) change.title = title;
  if (summary !== thought.summary) change.summary = summary;
  if (!sameTags(tags, thought.tags)) change.tags = tags;
  if (category !== thought.category) change.category = category;
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const rawText = thought.raw_text?.trim();
  const showRaw = Boolean(rawText) && rawText !== thought.summary.trim();

  function edit() {
    setText(textOf(thought));
    setError(null);
  }

  function cancel() {
    setText(null);
    setError(null);
  }

  async function save() {
    if (!text || hasEmptyField(text)) return;
    const change = changesOf(thought, text);
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

  const note = text && emptyNote(text);

  return (
    <div className="flex flex-col gap-4 px-4 pb-6">
      {text ? (
        <section aria-label="Edit thought" className="flex flex-col gap-2">
          <ThoughtFields value={text} onChange={setText} keep={thought.category} />
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
    </div>
  );
}

/**
 * Where the thought was saved from. The link is a real link, so it can be
 * copied; a plain click in the conversation it names stays on this page.
 */
function Origin({ origin }: { origin: ThoughtOrigin }) {
  const router = useRouter();
  const href = originHref(origin.conversation_id, origin.proposal_id);

  function open(event: MouseEvent<HTMLAnchorElement>) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    if (isOpenConversation(origin.conversation_id)) {
      openOriginHere(origin.conversation_id, origin.proposal_id);
    } else {
      router.push(href);
    }
  }

  return (
    <section aria-label="Origin">
      <h3 className="mb-1 text-xs font-medium text-muted-foreground">From</h3>
      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
        <a href={href} onClick={open} className="text-primary underline-offset-4 hover:underline">
          {origin.conversation_title}
        </a>
        <span className="text-muted-foreground">proposed {when(origin.proposed_at)}</span>
        {origin.archived && <Badge variant="outline">Archived</Badge>}
      </p>
    </section>
  );
}
