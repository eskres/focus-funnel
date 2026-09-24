"use client";

import { useState } from "react";

import { formatTokens } from "@/components/chat/context-meter";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";
import type { CompactModel } from "@/lib/sse";

/** Where /compact is: writing the draft, showing it, asking for a larger model, or failed. */
export type CompactState =
  | { step: "writing" }
  | { step: "draft"; summary: string; throughPosition: number; model: string }
  | { step: "choose"; models: CompactModel[]; contextLength: number | null }
  | { step: "failed"; message: string };

/**
 * The /compact dialog. The draft is editable, and nothing changes until the
 * user accepts it. When the conversation is too long for its own model, the
 * user picks a larger loadout model for this one summary; nothing is picked
 * for them.
 */
export function CompactDialog({
  state,
  onCancel,
  onAccept,
  onChoose,
}: {
  state: CompactState | null;
  onCancel: () => void;
  /** Stores the summary as edited. Throws to keep the dialog open with the error. */
  onAccept: (summary: string, throughPosition: number) => Promise<void>;
  onChoose: (model: CompactModel) => void;
}) {
  return (
    <Dialog open={state !== null} onOpenChange={(next) => !next && onCancel()}>
      <DialogContent className="sm:max-w-xl">
        {state?.step === "draft" ? (
          <DraftStep
            key={`${state.throughPosition}:${state.summary}`}
            draft={state}
            onCancel={onCancel}
            onAccept={onAccept}
          />
        ) : state?.step === "choose" ? (
          <ChooseStep state={state} onCancel={onCancel} onChoose={onChoose} />
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>Compact the conversation</DialogTitle>
              <DialogDescription>
                A summary replaces the older messages for the model. You can edit it first.
              </DialogDescription>
            </DialogHeader>
            {state?.step === "failed" ? (
              <Alert variant="destructive">
                <AlertDescription>{state.message} Nothing in the conversation changed.</AlertDescription>
              </Alert>
            ) : (
              <p role="status" className="text-sm text-muted-foreground">
                Writing a summary…
              </p>
            )}
            <DialogFooter>
              <Button variant="outline" onClick={onCancel}>
                {state?.step === "failed" ? "Close" : "Cancel"}
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function DraftStep({
  draft,
  onCancel,
  onAccept,
}: {
  draft: Extract<CompactState, { step: "draft" }>;
  onCancel: () => void;
  onAccept: (summary: string, throughPosition: number) => Promise<void>;
}) {
  const [text, setText] = useState(draft.summary);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function accept() {
    setBusy(true);
    setError(null);
    try {
      await onAccept(text.trim(), draft.throughPosition);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "The summary could not be saved.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <DialogHeader>
        <DialogTitle>Compact the conversation</DialogTitle>
        <DialogDescription>
          This summary replaces the older messages for the model. The most recent messages stay as
          they are, and every message stays visible. Edit the summary, then accept it.
        </DialogDescription>
      </DialogHeader>
      <Textarea
        aria-label="Summary"
        className="max-h-80 min-h-40"
        value={text}
        disabled={busy}
        onChange={(event) => setText(event.target.value)}
      />
      <p className="text-xs text-muted-foreground">Written by {draft.model}.</p>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
      <DialogFooter>
        <Button variant="outline" onClick={onCancel} disabled={busy}>
          Cancel
        </Button>
        <Button onClick={accept} disabled={busy || text.trim() === ""}>
          Accept summary
        </Button>
      </DialogFooter>
    </>
  );
}

function ChooseStep({
  state,
  onCancel,
  onChoose,
}: {
  state: Extract<CompactState, { step: "choose" }>;
  onCancel: () => void;
  onChoose: (model: CompactModel) => void;
}) {
  const [picked, setPicked] = useState<CompactModel | null>(null);
  const limit = state.contextLength ? ` (${formatTokens(state.contextLength)} tokens)` : "";
  return (
    <>
      <DialogHeader>
        <DialogTitle>Choose a model for the summary</DialogTitle>
        <DialogDescription>
          This conversation is too long for its model{limit} to summarise. Choose a model from your
          loadout with a larger context to write this one summary. The conversation keeps its own
          model.
        </DialogDescription>
      </DialogHeader>
      {state.models.length === 0 ? (
        <Alert>
          <AlertDescription>
            No model in your loadout has a large enough context. Add one in the model settings, or
            switch this conversation back to a larger model.
          </AlertDescription>
        </Alert>
      ) : (
        <fieldset className="flex flex-col gap-2 text-sm">
          <legend className="sr-only">Models large enough</legend>
          {state.models.map((model) => (
            <label key={`${model.providerId}:${model.model}`} className="flex items-center gap-2">
              <input
                type="radio"
                name="compact-model"
                checked={picked === model}
                onChange={() => setPicked(model)}
              />
              <span>{model.model}</span>
              <span className="text-muted-foreground">
                {formatTokens(model.contextLength)} tokens
              </span>
            </label>
          ))}
        </fieldset>
      )}
      <DialogFooter>
        <Button variant="outline" onClick={onCancel}>
          Cancel
        </Button>
        {state.models.length > 0 && (
          <Button disabled={!picked} onClick={() => picked && onChoose(picked)}>
            Write the summary
          </Button>
        )}
      </DialogFooter>
    </>
  );
}
