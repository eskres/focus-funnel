// Typed client for the first-run setup routes (`/api/setup/...`).
// Every call carries the setup token the backend printed in its log, in the
// `X-Setup-Token` header; the API proxy forwards that header to setup routes only.
import { apiFetch } from "@/lib/api";

export const SETUP_TOKEN_HEADER = "X-Setup-Token";

export type SetupItemState = "ok" | "missing" | "failed" | "warning" | "info";

export type SetupItemId =
  | "database"
  | "encryption_key"
  | "login"
  | "allow_list"
  | "search_key"
  | "chat_model"
  | "custom_provider"
  | "connectors";

export type SetupItem = {
  id: SetupItemId | string;
  state: SetupItemState;
  required: boolean;
  message: string;
  settings: string[];
};

export type SetupStatus = {
  auth_mode: string;
  ready: boolean;
  items: SetupItem[];
};

function withToken(token: string | null): HeadersInit {
  // A missing token still reaches the backend, which answers 404 while setup
  // is closed and 403 setup_token_invalid while it is open.
  return token === null ? {} : { [SETUP_TOKEN_HEADER]: token };
}

/**
 * The setup status for the logged-in user. Throws `NotFoundError` while setup
 * is closed and `SetupTokenInvalidError` for a missing or wrong token.
 */
export function getSetupStatus(token: string | null): Promise<SetupStatus> {
  return apiFetch<SetupStatus>("/api/setup/status", { headers: withToken(token) });
}

/**
 * Finishes setup. Throws `SetupIncompleteError` naming the first missing item,
 * `SetupTokenInvalidError` for a wrong token, and `NotFoundError` once closed.
 */
export async function finishSetup(token: string): Promise<void> {
  await apiFetch<void>("/api/setup/complete", {
    method: "POST",
    headers: withToken(token),
  });
}
