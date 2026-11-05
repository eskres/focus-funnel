// Sends a chat message to `POST /api/chat` and streams the answer back.
// The browser uses `fetch` and a stream reader rather than `EventSource`,
// because `EventSource` cannot send a request body.
import { BackendUnreachableError, toApiError } from "@/lib/api";
import { parseSse, type SseEvent } from "@/lib/sse";

// `/delete` is left out on purpose: nothing in the product suggests it.
export const COMMANDS = [
  { id: "push", command: "/push", description: "Propose a thought to file" },
  { id: "pull", command: "/pull", description: "Search your filed thoughts" },
  { id: "explore", command: "/explore", description: "Discuss and refine a thought" },
  { id: "compact", command: "/compact", description: "Summarise older messages to free up room" },
] as const;

/** True for a message that is only `/delete`, in any letter case. */
export function isDeleteCommand(text: string): boolean {
  return /^\s*\/delete\s*$/i.test(text);
}

export function isCompactCommand(text: string): boolean {
  return /^\s*\/compact\s*$/i.test(text);
}

export type ModelChoice = {
  providerId: string;
  model: string;
  reasoningEffort: string | null;
};

export type ChatRequest = {
  message: string;
  conversationId?: string;
  /** The model and effort chosen in the composer, applied from this message on. */
  choice?: ModelChoice;
  /** For /compact only: the loadout model the user chose to write the summary. */
  compactModel?: { providerId: string; model: string };
};

/**
 * Sends a message and yields the answer's events as they arrive.
 *
 * Throws an `ApiError` subclass when the request is refused before the stream
 * starts. If the message was stored anyway, `onStored` gets the conversation
 * id first. Once the stream has started, an `error` event is yielded instead.
 * A failure while reading the stream is thrown as it is, so the caller can
 * tell a cut-off answer from a refused request.
 */
export async function* streamChat(
  request: ChatRequest,
  signal?: AbortSignal,
  onStored?: (conversationId: string) => void,
): AsyncGenerator<SseEvent, void, undefined> {
  const body: Record<string, unknown> = { message: request.message };
  if (request.conversationId) body.conversation_id = request.conversationId;
  if (request.choice) {
    body.provider_id = request.choice.providerId;
    body.model = request.choice.model;
    body.reasoning_effort = request.choice.reasoningEffort;
  }
  if (request.compactModel) {
    body.compact_model = {
      provider_id: request.compactModel.providerId,
      model: request.compactModel.model,
    };
  }
  let response: Response;
  try {
    response = await fetch("/api/chat", {
      method: "POST",
      headers: { Accept: "text/event-stream", "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new BackendUnreachableError(
      "backend_unreachable",
      "The server could not be reached. Try again.",
      0,
    );
  }
  if (!response.ok) {
    const stored = response.headers.get("X-Conversation-Id");
    if (stored) onStored?.(stored);
    throw await toApiError(response);
  }
  if (!response.body) return;
  yield* parseSse(response.body);
}

/**
 * Follows the answer running in a conversation (`GET /api/chat/{id}/stream`):
 * yields every event it has sent so far, then the rest as they arrive, and
 * ends after `done` or `error`. Yields nothing when no answer is running
 * (204): the stored conversation then holds the last answer.
 *
 * Throws an `ApiError` subclass when the request is refused, for example
 * `NotFoundError` for a conversation that is not the user's. Aborting `signal`
 * stops following; the answer itself keeps running on the server.
 */
export async function* followTurn(
  conversationId: string,
  signal?: AbortSignal,
): AsyncGenerator<SseEvent, void, undefined> {
  let response: Response;
  try {
    response = await fetch(`/api/chat/${encodeURIComponent(conversationId)}/stream`, {
      headers: { Accept: "text/event-stream" },
      signal,
    });
  } catch (error) {
    if (signal?.aborted) throw error;
    throw new BackendUnreachableError(
      "backend_unreachable",
      "The server could not be reached. Try again.",
      0,
    );
  }
  if (response.status === 204) return;
  if (!response.ok) throw await toApiError(response);
  if (!response.body) return;
  yield* parseSse(response.body);
}
