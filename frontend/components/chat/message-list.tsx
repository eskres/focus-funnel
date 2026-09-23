"use client";

import { useEffect, useRef } from "react";

import { ChatError } from "@/components/chat/chat-error";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { ApiError } from "@/lib/api";

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
  status: "streaming" | "done" | "failed" | "cut";
  error?: ApiError;
};

export type ChatMessage = { id: number; role: "user"; text: string } | AnswerMessage;

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
  messages,
  canAct,
  onRetry,
}: {
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
          message.role === "user" ? (
            <li key={message.id} className="flex justify-end">
              <p className="max-w-[85%] rounded-2xl bg-primary px-3 py-2 text-sm whitespace-pre-wrap text-primary-foreground">
                {message.text}
              </p>
            </li>
          ) : (
            <Answer key={message.id} answer={message} canAct={canAct} onRetry={onRetry} />
          ),
        )}
      </ol>
      <div ref={endRef} />
    </>
  );
}

function Answer({
  answer,
  canAct,
  onRetry,
}: {
  answer: AnswerMessage;
  canAct: boolean;
  onRetry: (answer: AnswerMessage) => void;
}) {
  // Models often start with a blank line before their text.
  const text = answer.text.trimStart();
  const thinking = answer.status === "streaming" && !text && answer.tools.length === 0;
  return (
    <li className="flex flex-col items-start gap-2">
      {answer.tools.map((tool, index) => (
        <p
          key={index}
          data-testid="tool-indication"
          className="rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground"
        >
          {toolLabel(tool)}
        </p>
      ))}
      {text && <p className="max-w-[85%] text-sm whitespace-pre-wrap">{text}</p>}
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
