"use client";

import { useEffect, useRef, useState } from "react";

import { CommandList } from "@/components/chat/command-list";
import { Composer } from "@/components/chat/composer";
import { MessageList, type AnswerMessage, type ChatMessage } from "@/components/chat/message-list";
import { ApiError, UnauthenticatedError, createApiError } from "@/lib/api";
import { streamChat } from "@/lib/chat";
import { redirectToLogin } from "@/lib/redirect-to-login";

// The conversation lives in this component's state only. Reloading the page
// starts an empty one, and nothing is stored on the server.
export function Chat() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [answering, setAnswering] = useState(false);
  const nextId = useRef(1);
  const abortRef = useRef<AbortController | null>(null);

  // Stop reading an answer when the user leaves the chat.
  useEffect(() => () => abortRef.current?.abort(), []);

  function updateAnswer(id: number, update: (answer: AnswerMessage) => AnswerMessage) {
    setMessages((current) =>
      current.map((m) => (m.role === "assistant" && m.id === id ? update(m) : m)),
    );
  }

  async function send(text: string) {
    if (answering || text.trim() === "") return;

    const answerId = nextId.current++;
    setMessages((current) => [
      ...current,
      { id: nextId.current++, role: "user", text },
      { id: answerId, role: "assistant", prompt: text, text: "", status: "streaming" },
    ]);
    await runAnswer(answerId, text);
  }

  async function runAnswer(answerId: number, message: string) {
    setAnswering(true);

    const controller = new AbortController();
    abortRef.current = controller;
    // Set when the stream ends with `done` or `error`. A stream that closes
    // without either was cut short.
    let finished = false;

    try {
      for await (const event of streamChat(message, controller.signal)) {
        switch (event.type) {
          case "delta":
            updateAnswer(answerId, (a) => ({ ...a, text: a.text + event.text }));
            break;
          case "error":
            finished = true;
            updateAnswer(answerId, (a) => ({
              ...a,
              status: "failed",
              error: createApiError(event.code, event.message, 200),
            }));
            break;
          case "done":
            finished = true;
            updateAnswer(answerId, (a) => ({ ...a, status: "done" }));
            break;
        }
      }
      // The stream closed with neither `done` nor `error`.
      if (!finished) updateAnswer(answerId, (a) => ({ ...a, status: "cut" }));
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error instanceof UnauthenticatedError) {
        redirectToLogin("/app");
        return;
      }
      if (error instanceof ApiError) {
        updateAnswer(answerId, (a) => ({ ...a, status: "failed", error }));
      } else {
        // Reading the stream failed part way through.
        updateAnswer(answerId, (a) => ({ ...a, status: "cut" }));
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      if (!controller.signal.aborted) setAnswering(false);
    }
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex-1 overflow-y-auto p-6">
        {messages.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <CommandList />
          </div>
        ) : (
          <MessageList
            messages={messages}
            canAct={!answering}
            onRetry={send}
          />
        )}
      </div>
      <div className="border-t p-4">
        <div className="mx-auto w-full max-w-3xl">
          <Composer disabled={answering} onSend={send} />
        </div>
      </div>
    </div>
  );
}
