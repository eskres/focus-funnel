"use client";

import { useEffect, useRef } from "react";

import { ChatError } from "@/components/chat/chat-error";
import { ProposalGroup } from "@/components/chat/proposal-card";
import { SourcesList } from "@/components/chat/sources-list";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { ApiError } from "@/lib/api";
import type { Proposal, Source } from "@/lib/sse";
import { cn } from "@/lib/utils";

export type ToolIndication = {
  name: string;
  state: "running" | "done";
  summary?: string;
};

export type AnswerMessage = {
  id: number;
  role: "assistant";
  /** The user message this answers, so it can be asked again. */
  prompt: string;
  text: string;
  tools: ToolIndication[];
  /** The proposals the model made in this answer, with their saved state. */
  proposals?: Proposal[];
  /** The thoughts this answer's searches returned, each once. */
  sources?: Source[];
  status: "streaming" | "done" | "failed" | "cut";
  error?: ApiError;
  /** Replaced for the model by a /compact summary, and still shown. */
  compacted?: boolean;
};

export type ChatMessage =
  | { id: number; role: "user"; text: string; compacted?: boolean }
  | AnswerMessage
  | { id: number; role: "summary"; text: string; compacted?: boolean };

const runningLabels: Record<string, string> = {
  search_thoughts: "Searching your thoughts…",
  propose_thought: "Proposing a thought to file…",
};

const doneLabels: Record<string, string> = {
  search_thoughts: "Searched your thoughts",
  propose_thought: "Proposed a thought to file",
};

function toolLabel(tool: ToolIndication): string {
  if (tool.state === "running") return runningLabels[tool.name] ?? `Using ${tool.name}…`;
  return tool.summary || doneLabels[tool.name] || `Used ${tool.name}`;
}

export function MessageList({
  conversationId,
  messages,
  canAct,
  onRetry,
}: {
  conversationId: string | undefined;
  messages: ChatMessage[];
  /** False while an answer is arriving, so no second answer can start. */
  canAct: boolean;
  onRetry: (answer: AnswerMessage) => void;
}) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ block: "end" });
  }, [messages]);

  return (
    <>
      <ol className="mx-auto flex w-full max-w-3xl flex-col gap-4" aria-label="Conversation">
        {messages.map((message) =>
          message.role === "summary" ? (
            <li key={message.id} className={message.compacted ? "opacity-60" : undefined}>
              <section
                aria-label="Summary of earlier messages"
                className="rounded-lg border bg-muted/40 p-3 text-sm"
              >
                <p className="mb-1 text-xs font-medium text-muted-foreground">
                  Summary of earlier messages{message.compacted ? " (replaced by a later summary)" : ""}
                </p>
                <p className="whitespace-pre-wrap">{message.text}</p>
              </section>
            </li>
          ) : message.role === "user" ? (
            <li
              key={message.id}
              className={cn("flex flex-col items-end gap-1", message.compacted && "opacity-60")}
            >
              {message.compacted && <CompactedLabel />}
              <p className="max-w-[85%] rounded-2xl bg-primary px-3 py-2 text-sm whitespace-pre-wrap text-primary-foreground">
                {message.text}
              </p>
            </li>
          ) : (
            <Answer
              key={message.id}
              conversationId={conversationId}
              answer={message}
              canAct={canAct}
              onRetry={onRetry}
            />
          ),
        )}
      </ol>
      <div ref={endRef} />
    </>
  );
}

function Answer({
  conversationId,
  answer,
  canAct,
  onRetry,
}: {
  conversationId: string | undefined;
  answer: AnswerMessage;
  canAct: boolean;
  onRetry: (answer: AnswerMessage) => void;
}) {
  // Models often start with a blank line before their text.
  const text = answer.text.trimStart();
  const thinking = answer.status === "streaming" && !text && answer.tools.length === 0;
  return (
    <li className={cn("flex flex-col items-start gap-2", answer.compacted && "opacity-60")}>
      {answer.compacted && <CompactedLabel />}
      {answer.tools.map((tool, index) => (
        <p
          key={index}
          data-testid="tool-indication"
          className="rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground"
        >
          {toolLabel(tool)}
        </p>
      ))}
      {answer.proposals?.map((proposal) => (
        <ProposalGroup key={proposal.id} conversationId={conversationId} proposal={proposal} />
      ))}
      {text && <p className="max-w-[85%] text-sm whitespace-pre-wrap">{text}</p>}
      {answer.sources && <SourcesList sources={answer.sources} />}
      {thinking && (
        <p role="status" className="text-xs text-muted-foreground">
          Thinking…
        </p>
      )}
      {answer.status === "streaming" && !thinking && (
        <p role="status" className="text-xs text-muted-foreground">
          Writing…
        </p>
      )}
      {answer.status === "failed" && answer.error && (
        <div className="w-full [&_[data-slot=alert-description]]:text-pretty!">
          <ChatError error={answer.error} canRetry={canAct} onRetry={() => onRetry(answer)} />
        </div>
      )}
      {answer.status === "cut" && (
        <Alert>
          <AlertDescription className="flex flex-wrap items-center gap-2 text-pretty!">
            <span>This answer was cut short. The text above is all that arrived.</span>
            <Button variant="outline" size="xs" disabled={!canAct} onClick={() => onRetry(answer)}>
              Send again
            </Button>
          </AlertDescription>
        </Alert>
      )}
    </li>
  );
}

function CompactedLabel() {
  return (
    <span
      className="text-[10px] font-medium tracking-wide text-muted-foreground uppercase"
      title="Summarised by /compact: the model gets the summary instead of this message."
    >
      Compacted
    </span>
  );
}
