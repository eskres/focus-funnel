"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { CommandList } from "@/components/chat/command-list";
import { Composer } from "@/components/chat/composer";
import { useConversations } from "@/components/chat/conversations-context";
import { DeleteDialog } from "@/components/chat/delete-dialog";
import {
  MessageList,
  type AnswerMessage,
  type ChatMessage,
  type ToolIndication,
} from "@/components/chat/message-list";
import { ModelPicker, type ModelOption } from "@/components/chat/model-picker";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { ApiError, UnauthenticatedError, createApiError } from "@/lib/api";
import { isDeleteCommand, streamChat, type ModelChoice } from "@/lib/chat";
import {
  deleteConversation,
  getConversation,
  type ConversationDetail,
  type StoredMessage,
} from "@/lib/conversations";
import { getEfforts, getModelSettings, type ModelSettings } from "@/lib/models";
import { redirectToLogin } from "@/lib/redirect-to-login";

/** Rebuilds the chat items from stored messages: one answer per user message. */
function fromStored(stored: StoredMessage[], nextId: () => number): ChatMessage[] {
  const items: ChatMessage[] = [];
  let answer: AnswerMessage | null = null;
  let prompt = "";
  for (const message of stored) {
    if (message.role === "user") {
      prompt = message.content ?? "";
      items.push({ id: nextId(), role: "user", text: prompt });
      answer = null;
      continue;
    }
    if (message.role !== "assistant") continue;
    if (!answer) {
      answer = { id: nextId(), role: "assistant", prompt, text: "", tools: [], status: "done" };
      items.push(answer);
    }
    for (const call of message.tool_calls ?? []) {
      answer.tools.push({ name: call.function.name, state: "done" });
    }
    answer.text += message.content ?? "";
    if (message.status !== "complete" || message.error_code) {
      answer.status = message.status === "cut" && !message.error_code ? "cut" : "failed";
      answer.error = createApiError(
        message.error_code ?? "internal_error",
        "This answer did not finish. Send the message again to retry.",
        200,
      );
    }
  }
  return items;
}

/** The loadout models, plus the conversation's own model when it has left the loadout. */
function modelOptions(
  settings: ModelSettings | null,
  own: ModelChoice | null,
  ownEfforts: string[],
): ModelOption[] {
  const options: ModelOption[] = (settings?.models ?? []).map((entry) => ({
    providerId: entry.provider_id,
    model: entry.model,
    efforts: entry.efforts,
    loadoutEffort: entry.reasoning_effort,
    inLoadout: true,
  }));
  if (own && !options.some((o) => o.providerId === own.providerId && o.model === own.model)) {
    options.push({
      providerId: own.providerId,
      model: own.model,
      efforts: ownEfforts,
      loadoutEffort: null,
      inLoadout: false,
    });
  }
  return options;
}

function defaultChoice(settings: ModelSettings | null): ModelChoice | null {
  const entry = settings?.models.find((m) => m.is_default);
  return entry
    ? { providerId: entry.provider_id, model: entry.model, reasoningEffort: entry.reasoning_effort }
    : null;
}

function storedChoice(conversation: ConversationDetail): ModelChoice | null {
  return conversation.provider_id && conversation.model
    ? {
        providerId: conversation.provider_id,
        model: conversation.model,
        reasoningEffort: conversation.reasoning_effort,
      }
    : null;
}

export function Chat({ conversationId: initialId }: { conversationId?: string }) {
  const router = useRouter();
  const { refresh } = useConversations();
  const [conversationId, setConversationId] = useState<string | undefined>(initialId);
  const [title, setTitle] = useState("");
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(Boolean(initialId));
  const [loadError, setLoadError] = useState<string | null>(null);
  const [answering, setAnswering] = useState(false);
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  // The model the conversation stores, and the one shown in the picker.
  const [own, setOwn] = useState<ModelChoice | null>(null);
  const [ownEfforts, setOwnEfforts] = useState<string[]>([]);
  const [choice, setChoice] = useState<ModelChoice | null>(null);
  const [choiceChanged, setChoiceChanged] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const nextId = useRef(1);
  const abortRef = useRef<AbortController | null>(null);

  // Stop reading an answer when the user leaves the chat.
  useEffect(() => () => abortRef.current?.abort(), []);

  useEffect(() => {
    let cancelled = false;
    getModelSettings()
      .then((loaded) => {
        if (cancelled) return;
        setSettings(loaded);
        if (!initialId) setChoice(defaultChoice(loaded));
      })
      .catch((error: unknown) => {
        if (error instanceof UnauthenticatedError) redirectToLogin("/app");
      });
    return () => {
      cancelled = true;
    };
  }, [initialId]);

  useEffect(() => {
    if (!initialId) return;
    let cancelled = false;
    getConversation(initialId)
      .then((conversation) => {
        if (cancelled) return;
        setTitle(conversation.title);
        setMessages(fromStored(conversation.messages, () => nextId.current++));
        const stored = storedChoice(conversation);
        setOwn(stored);
        setChoice((current) => stored ?? current);
        setLoading(false);
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof UnauthenticatedError) {
          redirectToLogin(`/app/${initialId}`);
          return;
        }
        setLoadError(error instanceof ApiError ? error.message : "Could not load the conversation.");
        setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [initialId]);

  // A model outside the loadout needs its effort choices from the server.
  useEffect(() => {
    if (!own || settings?.models.some((m) => m.provider_id === own.providerId && m.model === own.model)) {
      return;
    }
    let cancelled = false;
    getEfforts(own.model)
      .then((efforts) => !cancelled && setOwnEfforts(efforts))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [own, settings]);

  function updateAnswer(id: number, update: (answer: AnswerMessage) => AnswerMessage) {
    setMessages((current) =>
      current.map((m) => (m.role === "assistant" && m.id === id ? update(m) : m)),
    );
  }

  function adopt(id: string) {
    setConversationId(id);
    // Keep the address in step without leaving the page, so the answer keeps streaming.
    window.history.replaceState(null, "", `/app/${id}`);
  }

  async function send(text: string) {
    if (answering || text.trim() === "") return;
    if (isDeleteCommand(text)) {
      if (conversationId) setDeleteOpen(true);
      return;
    }
    const answerId = nextId.current++;
    setMessages((current) => [
      ...current,
      { id: nextId.current++, role: "user", text },
      { id: answerId, role: "assistant", prompt: text, text: "", tools: [], status: "streaming" },
    ]);
    await runAnswer(answerId, text);
  }

  async function retry(answer: AnswerMessage) {
    if (answering) return;
    updateAnswer(answer.id, (a) => ({
      ...a,
      text: "",
      tools: [],
      proposal: undefined,
      error: undefined,
      status: "streaming",
    }));
    await runAnswer(answer.id, answer.prompt);
  }

  async function runAnswer(answerId: number, message: string) {
    setAnswering(true);
    const controller = new AbortController();
    abortRef.current = controller;
    const sentChoice = choiceChanged || !conversationId ? (choice ?? undefined) : undefined;
    // Set when the stream ends with `done` or `error`. A stream that closes
    // without either was cut short.
    let finished = false;

    try {
      const events = streamChat(
        { message, conversationId, choice: sentChoice },
        controller.signal,
        adopt,
      );
      for await (const event of events) {
        switch (event.type) {
          case "conversation":
            adopt(event.id);
            setTitle(event.title);
            void refresh();
            break;
          case "tool":
            updateAnswer(answerId, (a) => ({ ...a, tools: withTool(a.tools, event) }));
            break;
          case "proposal": {
            const { title, summary, tags } = event;
            updateAnswer(answerId, (a) => ({ ...a, proposal: { title, summary, tags } }));
            break;
          }
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
      if (sentChoice) {
        setOwn(sentChoice);
        setChoiceChanged(false);
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
      if (!controller.signal.aborted) {
        setAnswering(false);
        void refresh();
      }
    }
  }

  async function confirmDelete() {
    if (!conversationId) return;
    await deleteConversation(conversationId);
    setDeleteOpen(false);
    await refresh();
    router.push("/app");
  }

  const options = modelOptions(settings, own, ownEfforts);

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="flex-1 overflow-y-auto p-6">
        {loadError ? (
          <Alert variant="destructive" className="mx-auto max-w-3xl">
            <AlertDescription>{loadError}</AlertDescription>
          </Alert>
        ) : loading ? (
          <p role="status" className="text-center text-sm text-muted-foreground">
            Loading the conversation…
          </p>
        ) : messages.length === 0 ? (
          <div className="flex h-full items-center justify-center">
            <CommandList />
          </div>
        ) : (
          <MessageList
            conversationId={conversationId}
            messages={messages} canAct={!answering} onRetry={retry} />
        )}
      </div>
      <div className="border-t p-4">
        <div className="mx-auto w-full max-w-3xl">
          <Composer disabled={answering || loading || Boolean(loadError)} onSend={send}>
            <ModelPicker
              options={options}
              choice={choice}
              disabled={answering}
              onChange={(next) => {
                setChoice(next);
                setChoiceChanged(true);
              }}
            />
          </Composer>
        </div>
      </div>
      <DeleteDialog
        open={deleteOpen}
        title={title}
        onCancel={() => setDeleteOpen(false)}
        onConfirm={confirmDelete}
      />
    </div>
  );
}

function withTool(
  tools: ToolIndication[],
  event: { name: string; phase: "start" | "end"; summary?: string },
): ToolIndication[] {
  if (event.phase === "start") return [...tools, { name: event.name, state: "running" }];
  const index = tools.findLastIndex((t) => t.name === event.name && t.state === "running");
  const done: ToolIndication = { name: event.name, state: "done", summary: event.summary };
  if (index === -1) return [...tools, done];
  return tools.map((tool, i) => (i === index ? done : tool));
}
