// Typed client for the frontend's own `/api/...` proxy routes.
// Backend errors use `{ "error": { "code", "message" } }`; each known code maps
// to its own error class so callers can branch with `instanceof`.

export type ApiErrorCode =
  | "unauthenticated"
  | "validation_error"
  | "not_found"
  | "provider_key_missing"
  | "provider_key_invalid"
  | "provider_key_rejected"
  | "provider_unreachable"
  | "provider_rate_limited"
  | "provider_request_refused"
  | "model_not_set"
  | "model_unknown"
  | "model_unsupported"
  | "model_unavailable"
  | "context_full"
  | "conversation_busy"
  | "output_limit_reached"
  | "tool_loop_limit"
  | "answer_interrupted"
  | "backend_unreachable"
  | "internal_error"
  | "not_allowed"
  | "demo_session_expired"
  | "demo_full"
  | "rate_limited"
  | "thought_changed"
  | "action_expired"
  | "action_running";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  /** Any other keys of the error object, such as the thought a `thought_changed` names. */
  readonly details: Record<string, unknown>;

  constructor(code: string, message: string, status: number, details: Record<string, unknown> = {}) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
    this.details = details;
  }
}

export class UnauthenticatedError extends ApiError {}
export class ValidationError extends ApiError {}
export class NotFoundError extends ApiError {}
export class ProviderKeyMissingError extends ApiError {}
export class ProviderKeyInvalidError extends ApiError {}
export class ProviderKeyRejectedError extends ApiError {}
export class ProviderUnreachableError extends ApiError {}
export class ProviderRateLimitedError extends ApiError {}
export class ProviderRequestRefusedError extends ApiError {}
export class ModelNotSetError extends ApiError {}
export class ModelUnknownError extends ApiError {}
export class ModelUnsupportedError extends ApiError {}
export class ModelUnavailableError extends ApiError {}
export class ContextFullError extends ApiError {}
export class ConversationBusyError extends ApiError {}
export class OutputLimitReachedError extends ApiError {}
export class ToolLoopLimitError extends ApiError {}
/** A running answer stopped because the server stopped or restarted. */
export class AnswerInterruptedError extends ApiError {}
export class BackendUnreachableError extends ApiError {}
export class InternalError extends ApiError {}
export class NotAllowedError extends ApiError {}
export class DemoSessionExpiredError extends ApiError {}
export class DemoFullError extends ApiError {}
export class RateLimitedError extends ApiError {}
/** The thought changed since the card or sheet read it; `details.thought` is how it is now. */
export class ThoughtChangedError extends ApiError {}
export class ActionExpiredError extends ApiError {}
export class ActionRunningError extends ApiError {}

/** Sent on window when a call finds that the demo session has ended. */
export const DEMO_EXPIRED_EVENT = "ff:demo-session-expired";

const errorClasses: Record<ApiErrorCode, typeof ApiError> = {
  unauthenticated: UnauthenticatedError,
  validation_error: ValidationError,
  not_found: NotFoundError,
  provider_key_missing: ProviderKeyMissingError,
  provider_key_invalid: ProviderKeyInvalidError,
  provider_key_rejected: ProviderKeyRejectedError,
  provider_unreachable: ProviderUnreachableError,
  provider_rate_limited: ProviderRateLimitedError,
  provider_request_refused: ProviderRequestRefusedError,
  model_not_set: ModelNotSetError,
  model_unknown: ModelUnknownError,
  model_unsupported: ModelUnsupportedError,
  model_unavailable: ModelUnavailableError,
  context_full: ContextFullError,
  conversation_busy: ConversationBusyError,
  output_limit_reached: OutputLimitReachedError,
  tool_loop_limit: ToolLoopLimitError,
  answer_interrupted: AnswerInterruptedError,
  backend_unreachable: BackendUnreachableError,
  internal_error: InternalError,
  not_allowed: NotAllowedError,
  demo_session_expired: DemoSessionExpiredError,
  demo_full: DemoFullError,
  rate_limited: RateLimitedError,
  thought_changed: ThoughtChangedError,
  action_expired: ActionExpiredError,
  action_running: ActionRunningError,
};

function isKnownCode(code: string): code is ApiErrorCode {
  return Object.hasOwn(errorClasses, code);
}

function readErrorBody(body: unknown): {
  code?: string;
  message?: string;
  details?: Record<string, unknown>;
} {
  if (typeof body !== "object" || body === null || !("error" in body)) return {};
  const { error } = body;
  if (typeof error !== "object" || error === null) return {};
  const { code, message, ...details } = error as Record<string, unknown>;
  return {
    code: typeof code === "string" ? code : undefined,
    message: typeof message === "string" ? message : undefined,
    details,
  };
}

/** Builds the error class for a code, for example from an `error` event in a stream. */
export function createApiError(
  code: string,
  message: string,
  status: number,
  details: Record<string, unknown> = {},
): ApiError {
  const ErrorClass = isKnownCode(code) ? errorClasses[code] : ApiError;
  if (code === "demo_session_expired" && typeof window !== "undefined") {
    // Whichever call finds it first, the page shows that the session ended.
    window.dispatchEvent(new Event(DEMO_EXPIRED_EVENT));
  }
  return new ErrorClass(code, message, status, details);
}

/** Reads the shared error format from a failed response. */
export async function toApiError(response: Response): Promise<ApiError> {
  // A body that is not JSON is not the shared error format: use a generic error.
  const body: unknown = await response.json().catch(() => null);
  const {
    code = "unknown_error",
    message = `Request failed with status ${response.status}.`,
    details,
  } = readErrorBody(body);
  return createApiError(code, message, response.status, details);
}

/**
 * Calls a frontend API route (for example `/api/providers`) and returns
 * the parsed JSON body, or `undefined` for an empty response. Throws an
 * `ApiError` subclass when the response is not OK.
 */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  if (!path.startsWith("/api/")) {
    throw new Error(`apiFetch only calls /api/ routes, got "${path}".`);
  }
  const headers = new Headers(init?.headers);
  if (!headers.has("Accept")) headers.set("Accept", "application/json");
  if (init?.body !== undefined && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  const response = await fetch(path, { ...init, headers });
  if (!response.ok) throw await toApiError(response);
  if (response.status === 204) return undefined as T;
  const text = await response.text();
  return (text ? JSON.parse(text) : undefined) as T;
}
