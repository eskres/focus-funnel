"use client";

import { useEffect, useRef } from "react";

import { ChatError } from "@/components/chat/chat-error";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { ApiError } from "@/lib/api";

export type ChatMessage =
  | { id: number; role: "user"; text: string }
  | {
      id: number;
      role: "assistant";
      /** The user message this answers, so a cut-off answer can be asked again. */
      prompt: string;
      text: string;
      status: "streaming" | "done" | "failed" | "cut";
      error?: ApiError;
    };

export type AnswerMessage = Extract<ChatMessage, { role: "assistant" }>;

export function MessageList({
  messages,
  canAct,
  onRetry,
}: {
  messages: ChatMessage[];
  /** False while an answer is arriving, so no second answer can start. */
  canAct: boolean;
  onRetry: (text: string) => void;
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
          <li key={message.id} className="flex flex-col items-start gap-2">
            {message.text && (
              <p className="max-w-[85%] text-sm whitespace-pre-wrap">{message.text}</p>
            )}
            {message.status === "streaming" && (
              <p role="status" className="text-xs text-muted-foreground">
                Writing…
              </p>
            )}
            {message.status === "failed" && message.error && (
              <div className="w-full [&_[data-slot=alert-description]]:text-pretty!">
                <ChatError error={message.error} />
              </div>
            )}
            {message.status === "cut" && (
              <Alert>
                <AlertDescription className="flex flex-wrap items-center gap-2 text-pretty!">
                  <span>This answer was cut short. The text above is all that arrived.</span>
                  <Button
                    variant="outline"
                    size="xs"
                    disabled={!canAct}
                    onClick={() => onRetry(message.prompt)}
                  >
                    Send again
                  </Button>
                </AlertDescription>
              </Alert>
            )}
          </li>
        ),
      )}
      </ol>
      <div ref={endRef} />
    </>
  );
}
