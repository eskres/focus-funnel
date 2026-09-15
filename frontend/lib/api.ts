// Typed client for the frontend's own `/api/...` proxy routes.
// Backend errors use `{ "error": { "code", "message" } }`; each known code maps
// to its own error class so callers can branch with `instanceof`.

export type ApiErrorCode =
  | "unauthenticated"
  | "validation_error"
  | "not_found"
  | "nebius_key_missing"
  | "nebius_key_invalid"
  | "nebius_key_rejected"
  | "nebius_unreachable";

export class ApiError extends Error {
  readonly code: string;
  readonly status: number;

  constructor(code: string, message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.code = code;
    this.status = status;
  }
}

export class UnauthenticatedError extends ApiError {}
export class ValidationError extends ApiError {}
export class NotFoundError extends ApiError {}
export class NebiusKeyMissingError extends ApiError {}
export class NebiusKeyInvalidError extends ApiError {}
export class NebiusKeyRejectedError extends ApiError {}
export class NebiusUnreachableError extends ApiError {}

const errorClasses: Record<ApiErrorCode, typeof ApiError> = {
  unauthenticated: UnauthenticatedError,
  validation_error: ValidationError,
  not_found: NotFoundError,
  nebius_key_missing: NebiusKeyMissingError,
  nebius_key_invalid: NebiusKeyInvalidError,
  nebius_key_rejected: NebiusKeyRejectedError,
  nebius_unreachable: NebiusUnreachableError,
};

async function toApiError(response: Response): Promise<ApiError> {
  let code = "unknown_error";
  let message = `Request failed with status ${response.status}.`;
  try {
    const body: unknown = await response.json();
    const error = (body as { error?: { code?: unknown; message?: unknown } })
      ?.error;
    if (typeof error?.code === "string") code = error.code;
    if (typeof error?.message === "string") message = error.message;
  } catch {
    // Not the shared error format; keep the generic error.
  }
  const ErrorClass = errorClasses[code as ApiErrorCode] ?? ApiError;
  return new ErrorClass(code, message, response.status);
}

/**
 * Calls a frontend API route (for example `/api/settings/api-key`) and returns
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
