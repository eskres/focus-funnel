"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { CompactNotice, UsageWarningNotice } from "@/components/chat/chat-notices";
import { CommandList } from "@/components/chat/command-list";
import { CompactDialog, type CompactState } from "@/components/chat/compact-dialog";
import { Composer } from "@/components/chat/composer";
import { ContextMeter, type Meter } from "@/components/chat/context-meter";
import { useConversations } from "@/components/chat/conversations-context";
import { useDemo } from "@/components/demo/demo-context";
import { DemoNoticeDialog } from "@/components/demo/demo-notice";
import { DeleteDialog } from "@/components/chat/delete-dialog";
import {
  MessageList,
  type AnswerMessage,
  type ChatMessage,
  type ToolIndication,
  toolName,
} from "@/components/chat/message-list";
import { ModelPicker, type ModelOption } from "@/components/chat/model-picker";
import { ConnectorPicker, type PickerConnector } from "@/components/chat/connector-picker";
import { withSources } from "@/components/chat/sources-list";
import { ThoughtSheet } from "@/components/chat/thought-sheet";
import {
  ProposalDialog,
  heldProposalFor,
  type HeldOffer,
} from "@/components/chat/proposal-dialog";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { ApiError, UnauthenticatedError, createApiError } from "@/lib/api";
import { isCompactCommand, isDeleteCommand, streamChat, type ModelChoice } from "@/lib/chat";
import { getConnectors, switchedOnTools, type ConnectorsListing } from "@/lib/connectors";
import {
  acceptCompaction,
  deleteConversation,
  getConversation,
  setConversationConnectors,
  storedActions,
  storedProposals,
  storedSources,
  type ContextMeter as StoredMeter,
  type ConversationDetail,
  type StoredMessage,
} from "@/lib/conversations";
import {
  getEfforts,
  getModelSettings,
  getProviderModels,
  type ModelSettings,
  type ProviderModel,
  type UsageWarning,
} from "@/lib/models";
import { redirectToLogin } from "@/lib/redirect-to-login";
import type { Action, CompactModel, Proposal } from "@/lib/sse";

/**
 * Rebuilds the chat items from stored messages: one answer per user message,
 * with the proposal cards, action cards, and sources it showed.
 */
function fromStored(
  stored: StoredMessage[],
  proposals: Proposal[],
  nextId: () => number,
  actions: Action[] = [],
): ChatMessage[] {
  const items: ChatMessage[] = [];
  const byId = new Map(proposals.map((proposal) => [proposal.id, proposal]));
  const actionsById = new Map(actions.map((action) => [action.id, action]));
  // The answer each stored position belongs to, for proposals no tool message names.
  const answerAt: { position: number; answer: AnswerMessage }[] = [];
  // Each tool call's indication, so its stored result can relabel it.
  const toolsByCall = new Map<string, ToolIndication>();
  let answer: AnswerMessage | null = null;
  let prompt = "";
  for (const message of stored) {
    const compacted = message.compacted;
    if (message.role === "tool") {
      if (!answer) continue;
      const sources = message.details?.sources !== undefined ? storedSources(message) : null;
      if (sources) answer.sources = withSources(answer.sources ?? [], sources);
      const proposal = byId.get(message.details?.proposal_id ?? "");
      if (proposal) {
        answer.proposals = [...(answer.proposals ?? []), proposal];
        byId.delete(proposal.id);
      }
      const called = toolsByCall.get(message.tool_call_id ?? "");
      if (called && message.details?.failed) {
        called.failed = true;
        if (message.details.summary) called.summary = message.details.summary;
      }
      const action = actionsById.get(message.details?.action_id ?? "");
      if (action) {
        answer.actions = [...(answer.actions ?? []), action];
        // It asked for approval; the card says what happened, so "Used" would mislead.
        if (called) called.summary = `Asked to use ${toolName(called.name)}`;
      }
      answerAt.push({ position: message.position, answer });
      continue;
    }
    if (message.role === "user") {
      prompt = message.content ?? "";
      items.push({ id: nextId(), role: "user", text: prompt, compacted });
      answer = null;
      continue;
    }
    if (message.role === "summary") {
      items.push({ id: nextId(), role: "summary", text: message.content ?? "", compacted });
      answer = null;
      continue;
    }
    if (message.role !== "assistant") continue;
    if (!answer) {
      answer = {
        id: nextId(),
        role: "assistant",
        prompt,
        text: "",
        tools: [],
        status: "done",
        compacted,
      };
      items.push(answer);
    }
    for (const call of message.tool_calls ?? []) {
      const tool: ToolIndication = { name: call.function.name, state: "done" };
      answer.tools.push(tool);
      toolsByCall.set(call.id, tool);
    }
    answer.text += message.content ?? "";
    answerAt.push({ position: message.position, answer });
    if (message.status !== "complete" || message.error_code) {
      answer.status = message.status === "cut" && !message.error_code ? "cut" : "failed";
      answer.error = createApiError(
        message.error_code ?? "internal_error",
        "This answer did not finish. Send the message again to retry.",
        200,
      );
    }
  }
  // A proposal offered before archive or /compact has no tool message: it
  // goes with the answer it followed.
  for (const proposal of byId.values()) {
    const owner = answerAt.findLast((entry) => entry.position <= proposal.position)?.answer;
    if (owner) owner.proposals = [...(owner.proposals ?? []), proposal];
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

function toMeter(context: StoredMeter | undefined): Meter | null {
  return context
    ? {
        tokens: context.tokens,
        estimated: context.estimated,
        contextLength: context.context_length,
        toolTokens: context.tool_tokens,
      }
    : null;
}

/** The connectors the picker lists, or null while connectors are off. */
function pickerConnectors(listing: ConnectorsListing | null): PickerConnector[] | null {
  return listing
    ? listing.connectors.map((c) => ({ id: c.id, name: c.name, tools: switchedOnTools(c) }))
    : null;
}

function readWarning(data: Record<string, unknown>): UsageWarning | null {
  return (data.unit === "usd" || data.unit === "tokens") && typeof data.amount === "number"
    ? { unit: data.unit, amount: data.amount }
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
  const demo = useDemo();
  const { refresh, startNewChat } = useConversations();
  // Demo mode: a message held until the visitor accepts the demo notice.
  const [heldForNotice, setHeldForNotice] = useState<string | null>(null);
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
  const [offer, setOffer] = useState<HeldOffer | null>(null);
  const [meter, setMeter] = useState<Meter | null>(null);
  // Null while connectors are off on the server, or could not be listed.
  const [connectorListing, setConnectorListing] = useState<ConnectorsListing | null>(null);
  const [connectorsOn, setConnectorsOn] = useState<string[]>([]);
  const [compactSuggested, setCompactSuggested] = useState(false);
  const [usageWarning, setUsageWarning] = useState<UsageWarning | null>(null);
  const [compactState, setCompactState] = useState<CompactState | null>(null);
  const providerModels = useRef(new Map<string, Promise<ProviderModel[]>>());
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
        // A conversation with no stored model yet gets the default, like a new one.
        setChoice((current) => current ?? defaultChoice(loaded));
      })
      .catch((error: unknown) => {
        if (error instanceof UnauthenticatedError) redirectToLogin("/app");
      });
    return () => {
      cancelled = true;
    };
  }, [initialId]);

  // Connectors are optional: any failure (404 while they are off) hides the picker.
  useEffect(() => {
    let cancelled = false;
    getConnectors()
      .then((listing) => !cancelled && setConnectorListing(listing))
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!initialId) return;
    let cancelled = false;
    getConversation(initialId)
      .then((conversation) => {
        if (cancelled) return;
        setTitle(conversation.title);
        setMessages(
          fromStored(
            conversation.messages,
            storedProposals(conversation),
            () => nextId.current++,
            storedActions(conversation),
          ),
        );
        setMeter(toMeter(conversation.context));
        setConnectorsOn((conversation.connectors ?? []).map((c) => c.id));
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

  /** Replace an action card's state, wherever its answer is. */
  function changeAction(action: Action) {
    setMessages((current) =>
      current.map((m) =>
        m.role === "assistant" && m.actions?.some((a) => a.id === action.id)
          ? { ...m, actions: m.actions.map((a) => (a.id === action.id ? action : a)) }
          : m,
      ),
    );
  }

  /** A turn started: the server expired every card still waiting. */
  function expireOpenActions() {
    setMessages((current) =>
      current.map((m) =>
        m.role === "assistant" && m.actions?.some((a) => a.status === "pending" || a.status === "failed")
          ? {
              ...m,
              actions: m.actions.map((a) =>
                a.status === "pending" || a.status === "failed" ? { ...a, status: "expired" } : a,
              ),
            }
          : m,
      ),
    );
  }

  function adopt(id: string) {
    setConversationId(id);
    // Keep the address in step without leaving the page, so the answer keeps streaming.
    window.history.replaceState(null, "", `/app/${id}`);
  }

  async function send(text: string, offered = false, noticeAccepted = false) {
    if (answering || text.trim() === "") return;
    if (demo && !demo.noticeAccepted && !noticeAccepted) {
      setHeldForNotice(text);
      return;
    }
    if (isDeleteCommand(text)) {
      if (conversationId) setDeleteOpen(true);
      return;
    }
    if (isCompactCommand(text)) {
      if (conversationId && !offered) {
        // The held proposal is offered before compacting.
        setAnswering(true);
        const proposal = await heldProposalFor(conversationId);
        setAnswering(false);
        if (proposal) {
          setOffer({
            conversationId,
            proposal,
            continueLabel: "Compact now",
            onContinue: () => send(text, true),
          });
          return;
        }
      }
      await runCompact();
      return;
    }
    // Sending the same text after an unanswered message resends it, as the
    // server does, rather than showing it twice.
    const last = messages.at(-1);
    const unfinished = last?.role === "assistant" && (last.status === "failed" || last.status === "cut");
    if (unfinished && last.prompt === text) {
      await retry(last);
      return;
    }
    if (last?.role === "user" && last.text === text) {
      const answerId = nextId.current++;
      setMessages((current) => [
        ...current,
        { id: answerId, role: "assistant", prompt: text, text: "", tools: [], status: "streaming" },
      ]);
      await runAnswer(answerId, text);
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
      proposals: undefined,
      actions: undefined,
      sources: undefined,
      error: undefined,
      status: "streaming",
    }));
    await runAnswer(answer.id, answer.prompt);
  }

  /** Asks for a /compact draft. Nothing changes until the user accepts it. */
  async function runCompact(compactModel?: CompactModel) {
    setCompactState({ step: "writing" });
    setAnswering(true);
    const controller = new AbortController();
    abortRef.current = controller;
    const sentChoice = choiceChanged ? (choice ?? undefined) : undefined;
    let outcome: CompactState | null = null;
    try {
      const events = streamChat(
        {
          message: "/compact",
          conversationId,
          choice: sentChoice,
          compactModel: compactModel && {
            providerId: compactModel.providerId,
            model: compactModel.model,
          },
        },
        controller.signal,
      );
      for await (const event of events) {
        if (event.type === "compact_draft") {
          const { summary, throughPosition, model } = event;
          outcome = { step: "draft", summary, throughPosition, model };
        } else if (event.type === "compact_models") {
          outcome = { step: "choose", models: event.models, contextLength: event.contextLength };
        } else if (event.type === "error") {
          outcome = { step: "failed", message: event.message };
        }
      }
      if (sentChoice) {
        setOwn(sentChoice);
        setChoiceChanged(false);
      }
    } catch (error) {
      if (controller.signal.aborted) return;
      if (error instanceof UnauthenticatedError) {
        redirectToLogin(conversationId ? `/app/${conversationId}` : "/app");
        return;
      }
      outcome = {
        step: "failed",
        message: error instanceof ApiError ? error.message : "The summary could not be written.",
      };
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
      if (!controller.signal.aborted) setAnswering(false);
    }
    setCompactState(
      outcome ?? { step: "failed", message: "The summary was cut short. Try /compact again." },
    );
  }

  async function acceptDraft(summary: string, throughPosition: number) {
    if (!conversationId) return;
    const detail = await acceptCompaction(conversationId, summary, throughPosition);
    setMessages(
      fromStored(
        detail.messages,
        storedProposals(detail),
        () => nextId.current++,
        storedActions(detail),
      ),
    );
    setMeter(toMeter(detail.context));
    setCompactSuggested(false);
    setCompactState(null);
  }

  /** The context length of a model, from its provider's list, fetched once per page. */
  function contextLengthOf(providerId: string, model: string): Promise<number | null> {
    let list = providerModels.current.get(providerId);
    if (!list) {
      list = getProviderModels(providerId);
      providerModels.current.set(providerId, list);
    }
    return list.then(
      (models) => models.find((m) => m.id === model)?.context_length ?? null,
      () => null,
    );
  }

  function chooseModel(next: ModelChoice) {
    setChoice(next);
    setChoiceChanged(true);
    if (!meter) return;
    // Models count tokens differently: the figure is an estimate until the next answer.
    setMeter((current) => current && { ...current, estimated: true });
    void contextLengthOf(next.providerId, next.model).then((contextLength) =>
      setMeter((current) => current && { ...current, contextLength }),
    );
  }

  /** Turn connectors on or off; the change applies from the next turn. */
  async function changeConnectors(connectorIds: string[]) {
    if (!conversationId) return;
    let detail: ConversationDetail;
    try {
      detail = await setConversationConnectors(conversationId, connectorIds);
    } catch (error) {
      if (error instanceof UnauthenticatedError) {
        redirectToLogin(`/app/${conversationId}`);
        return;
      }
      throw error;
    }
    setConnectorsOn((detail.connectors ?? []).map((c) => c.id));
    // A change of the offered tools makes the figure an estimate until the
    // next answer (the server says so). A model chosen but not yet sent keeps
    // its context length and its estimate mark.
    const next = toMeter(detail.context);
    setMeter((current) =>
      next && choiceChanged && current
        ? { ...next, estimated: true, contextLength: current.contextLength }
        : next,
    );
  }

  async function runAnswer(answerId: number, message: string) {
    setAnswering(true);
    const controller = new AbortController();
    abortRef.current = controller;
    const sentChoice = choiceChanged || !conversationId ? (choice ?? undefined) : undefined;
    // Set when the stream ends with `done` or `error`. A stream that closes
    // without either was cut short.
    let finished = false;
    let started = false;

    try {
      const events = streamChat(
        { message, conversationId, choice: sentChoice },
        controller.signal,
        (id) => {
          // The message was stored and refused (too_many_tools, context_full…):
          // its turn started on the server, which expired the waiting cards.
          adopt(id);
          expireOpenActions();
        },
      );
      for await (const event of events) {
        if (!started) {
          // The turn started, so cards from earlier answers can no longer be approved.
          started = true;
          expireOpenActions();
        }
        switch (event.type) {
          case "conversation":
            adopt(event.id);
            setTitle(event.title);
            void refresh();
            break;
          case "tool": {
            const found = event.sources;
            updateAnswer(answerId, (a) => ({
              ...a,
              tools: withTool(a.tools, event),
              ...(found ? { sources: withSources(a.sources ?? [], found) } : {}),
            }));
            break;
          }
          case "proposal": {
            const { id, position, parts, replacedBy, replaces } = event;
            setMessages((current) =>
              current.map((m) => {
                if (m.role !== "assistant") return m;
                // The replaced proposal's cards collapse, wherever they are.
                const proposals = m.proposals?.map((p) =>
                  p.id === replaces ? { ...p, replacedBy: id } : p,
                );
                return m.id === answerId
                  ? { ...m, proposals: [...(proposals ?? []), { id, position, parts, replacedBy }] }
                  : { ...m, proposals };
              }),
            );
            break;
          }
          case "action":
            updateAnswer(answerId, (a) => ({ ...a, actions: [...(a.actions ?? []), event.action] }));
            break;
          case "delta":
            updateAnswer(answerId, (a) => ({ ...a, text: a.text + event.text }));
            break;
          case "usage":
            setMeter((current) => ({
              tokens: event.promptTokens,
              estimated: false,
              contextLength: event.contextLength ?? current?.contextLength ?? null,
              toolTokens: current?.toolTokens,
            }));
            break;
          case "notice":
            if (event.kind === "compact_suggested") setCompactSuggested(true);
            if (event.kind === "usage_warning") setUsageWarning(readWarning(event.data));
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
    startNewChat();
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
            messages={messages}
            canAct={!answering}
            onRetry={retry}
            onActionChange={changeAction}
          />
        )}
      </div>
      <div className="border-t p-4">
        <div className="mx-auto w-full max-w-3xl">
          {(compactSuggested || usageWarning) && (
            <div className="mb-3 flex flex-col gap-2">
              {compactSuggested && (
                <CompactNotice
                  share={meter?.contextLength ? meter.tokens / meter.contextLength : null}
                  canAct={!answering}
                  onCompact={() => {
                    setCompactSuggested(false);
                    void send("/compact");
                  }}
                  onDismiss={() => setCompactSuggested(false)}
                />
              )}
              {usageWarning && (
                <UsageWarningNotice warning={usageWarning} onDismiss={() => setUsageWarning(null)} />
              )}
            </div>
          )}
          <Composer disabled={answering || loading || Boolean(loadError)} onSend={send}>
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <ModelPicker
                  options={options}
                  choice={choice}
                  disabled={answering}
                  onChange={chooseModel}
                />
                <ConnectorPicker
                  connectors={pickerConnectors(connectorListing)}
                  on={connectorsOn}
                  maxTools={connectorListing?.max_tools ?? 0}
                  canChange={Boolean(conversationId)}
                  disabled={answering || loading}
                  onChange={changeConnectors}
                />
              </div>
              <ContextMeter meter={meter} />
            </div>
          </Composer>
        </div>
      </div>
      <ProposalDialog offer={offer} onClose={() => setOffer(null)} />
      <ThoughtSheet />
      <DemoNoticeDialog
        open={heldForNotice !== null}
        providerId={choice?.providerId ?? null}
        onClose={() => setHeldForNotice(null)}
        onAccept={async () => {
          await demo?.acceptNotice();
          const text = heldForNotice;
          setHeldForNotice(null);
          if (text !== null) void send(text, false, true);
        }}
      />
      <CompactDialog
        state={compactState}
        onCancel={() => {
          if (compactState?.step === "writing") {
            // Stop reading the draft; nothing was stored.
            abortRef.current?.abort();
            setAnswering(false);
          }
          setCompactState(null);
        }}
        onAccept={acceptDraft}
        onChoose={(model) => void runCompact(model)}
      />
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
  event: { name: string; phase: "start" | "end"; summary?: string; failed?: boolean },
): ToolIndication[] {
  if (event.phase === "start") return [...tools, { name: event.name, state: "running" }];
  const index = tools.findLastIndex((t) => t.name === event.name && t.state === "running");
  const done: ToolIndication = {
    name: event.name,
    state: "done",
    summary: event.summary,
    ...(event.failed ? { failed: true } : {}),
  };
  if (index === -1) return [...tools, done];
  return tools.map((tool, i) => (i === index ? done : tool));
}
