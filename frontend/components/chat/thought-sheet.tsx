"use client";

import { useEffect, useState } from "react";

import { Badge } from "@/components/ui/badge";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { NotFoundError, UnauthenticatedError } from "@/lib/api";
import { redirectToLogin } from "@/lib/redirect-to-login";
import { closeThought, useOpenThought } from "@/lib/thought-link";
import { getThought, type Thought } from "@/lib/thoughts";

type Loaded =
  | { id: string; state: "ready"; thought: Thought }
  | { id: string; state: "gone" }
  | { id: string; state: "failed"; message: string };

function when(value: string): string {
  return new Date(value).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

/**
 * The thought named in the address (`?thought=<id>`), read-only, in a sheet
 * over the chat. Closing it, or Back, leaves the chat as it was.
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
  const rawText = thought?.raw_text?.trim();
  const showRaw = Boolean(rawText) && rawText !== thought?.summary.trim();

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
          <div className="flex flex-col gap-4 px-4 pb-6">
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
            {showRaw && (
              <section aria-label="Raw text">
                <h3 className="mb-1 text-xs font-medium text-muted-foreground">Raw text</h3>
                <p className="whitespace-pre-wrap text-muted-foreground">{rawText}</p>
              </section>
            )}
          </div>
        )}
      </SheetContent>
    </Sheet>
  );
}
