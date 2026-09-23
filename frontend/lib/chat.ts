// Sends a chat message to `POST /api/chat` and streams the answer back.
// The browser uses `fetch` and a stream reader rather than `EventSource`,
// because `EventSource` cannot send a request body.
import { BackendUnreachableError, toApiError } from "@/lib/api";
import { parseSse, type SseEvent } from "@/lib/sse";

export const COMMANDS = [
  { id: "push", command: "/push", description: "Propose a thought to file" },
  { id: "pull", command: "/pull", description: "Search your filed thoughts" },
  { id: "explore", command: "/explore", description: "Discuss and refine a thought" },
] as const;

/**
 * Sends a message and yields the answer's events as they arrive.
 *
 * Throws an `ApiError` subclass when the request is refused before the stream
 * starts. Once the stream has started, an `error` event is yielded instead. A
 * failure while reading the stream is thrown as it is, so the caller can tell
 * a cut-off answer from a refused request.
 */
export async function* streamChat(
  message: string,
  signal?: AbortSignal,
): AsyncGenerator<SseEvent, void, undefined> {
  let response: Response;
  try {
    response = await fetch("/api/chat", {
      method: "POST",
      headers: { Accept: "text/event-stream", "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
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
  if (!response.ok) throw await toApiError(response);
  if (!response.body) return;
  yield* parseSse(response.body);
}
