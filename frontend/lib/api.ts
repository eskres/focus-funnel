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
  | "backend_unreachable"
  | "internal_error";

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
export class ProviderKeyMissingError extends ApiError {}
export class ProviderKeyInvalidError extends ApiError {}
export class ProviderKeyRejectedError extends ApiError {}
export class ProviderUnreachableError extends ApiError {}
export class ProviderRateLimitedError extends ApiError {}
export class ProviderRequestRefusedError extends ApiError {}
export class BackendUnreachableError extends ApiError {}
export class InternalError extends ApiError {}

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
  backend_unreachable: BackendUnreachableError,
  internal_error: InternalError,
};

function isKnownCode(code: string): code is ApiErrorCode {
  return Object.hasOwn(errorClasses, code);
}

function readErrorBody(body: unknown): { code?: string; message?: string } {
  if (typeof body !== "object" || body === null || !("error" in body)) return {};
  const { error } = body;
  if (typeof error !== "object" || error === null) return {};
  return {
    code: "code" in error && typeof error.code === "string" ? error.code : undefined,
    message:
      "message" in error && typeof error.message === "string" ? error.message : undefined,
  };
}

/** Builds the error class for a code, for example from an `error` event in a stream. */
export function createApiError(code: string, message: string, status: number): ApiError {
  const ErrorClass = isKnownCode(code) ? errorClasses[code] : ApiError;
  return new ErrorClass(code, message, status);
}

/** Reads the shared error format from a failed response. */
export async function toApiError(response: Response): Promise<ApiError> {
  // A body that is not JSON is not the shared error format: use a generic error.
  const body: unknown = await response.json().catch(() => null);
  const { code = "unknown_error", message = `Request failed with status ${response.status}.` } =
    readErrorBody(body);
  return createApiError(code, message, response.status);
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
