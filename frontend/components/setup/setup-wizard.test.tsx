// @vitest-environment jsdom
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { MODEL_SETTINGS_CHANGED } from "@/components/model-settings";
import { PROVIDER_KEYS_CHANGED, ProvidersSettings } from "@/components/providers-settings";
import { redirectToLogin } from "@/lib/redirect-to-login";
import { errorResponse, fakeApi, json, loadout } from "@/test/fake-api";

import { SETUP_TOKEN_KEY, SetupWizard } from "./setup-wizard";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));

const TOKEN = "setup-token-0123456789abcdefghij";
const TOKEN_REFUSED =
  "The setup token is missing or not valid. Use the token the backend printed in its log at its last start.";

type Item = {
  id: string;
  state: string;
  required: boolean;
  message: string;
  settings: string[];
};

const ITEMS: Record<string, Item> = {
  database: {
    id: "database",
    state: "ok",
    required: true,
    message: "Postgres answers and has pgvector 0.8.1.",
    settings: ["DATABASE_URL"],
  },
  encryption_key: {
    id: "encryption_key",
    state: "ok",
    required: true,
    message: "The key encryption key is set. Keep a copy of KEY_ENCRYPTION_KEY somewhere safe.",
    settings: ["KEY_ENCRYPTION_KEY"],
  },
  login: {
    id: "login",
    state: "ok",
    required: true,
    message:
      "OpenID Connect: issuer http://localhost:1411, client id focus-funnel-client. " +
      "Change these in .env and restart both servers.",
    settings: ["AUTH_MODE", "OIDC_ISSUER", "OIDC_CLIENT_ID", "OIDC_CLIENT_SECRET", "OIDC_INTERNAL_URL"],
  },
  allow_list: {
    id: "allow_list",
    state: "warning",
    required: false,
    message:
      "Allow-list: none set. Anyone your login provider lets in can use this instance. " +
      "Set AUTH_ALLOWED_EMAILS to limit it.",
    settings: ["AUTH_ALLOWED_EMAILS"],
  },
  search_key: {
    id: "search_key",
    state: "missing",
    required: true,
    message: "Search uses Nebius Token Factory. Save a key for it in the provider step.",
    settings: ["EMBEDDING_PROVIDER", "EMBEDDING_MODEL"],
  },
  chat_model: {
    id: "chat_model",
    state: "missing",
    required: true,
    message: "Choose a default model in the model step.",
    settings: [],
  },
  custom_provider: {
    id: "custom_provider",
    state: "info",
    required: false,
    message: "Provider presets: Nebius Token Factory, NVIDIA. Custom providers are turned off.",
    settings: ["PROVIDERS_CONFIG_PATH", "ALLOW_CUSTOM_PROVIDER"],
  },
  connectors: {
    id: "connectors",
    state: "info",
    required: false,
    message: "Connectors are off.",
    settings: ["MCP_ENABLED", "MCP_USER_CONNECTORS", "MCP_CONNECTORS_PATH"],
  },
};

function status(changes: Record<string, Partial<Item>> = {}, authMode = "oidc") {
  const items = Object.values(ITEMS).map((item) => ({ ...item, ...changes[item.id] }));
  return {
    auth_mode: authMode,
    ready: items.every((item) => !item.required || item.state === "ok"),
    items,
  };
}

const READY = {
  search_key: { state: "ok", message: "Search uses Nebius Token Factory, and your key for it is saved." },
  chat_model: { state: "ok", message: "Your default model is vendor/nano from Nebius Token Factory." },
};

const nvidia = {
  id: "nvidia",
  label: "NVIDIA",
  key_url: "",
  notice: "",
  key_required: true,
  is_custom: false,
  key_saved: false,
};

const tokenRefused = () => errorResponse(403, "setup_token_invalid", TOKEN_REFUSED);
const closed = () => errorResponse(404, "not_found", "Not found.");

/** The settings routes the embedded provider and model sections call. */
const SETTINGS_ROUTES = {
  "GET /api/providers": json(200, { providers: [nvidia], custom_provider_allowed: false }),
  "GET /api/settings/models": json(200, loadout()),
};

function api(statusResponses: Parameters<typeof fakeApi>[0][string], extra: Parameters<typeof fakeApi>[0] = {}) {
  return fakeApi({
    "GET /api/setup/status": statusResponses,
    ...SETTINGS_ROUTES,
    ...extra,
  });
}

/** The X-Setup-Token header of each status or finish call, in order. */
function setupTokensSent(fetchMock: ReturnType<typeof fakeApi>["fetchMock"]) {
  return fetchMock.mock.calls
    .filter(([input]) => String(input).startsWith("/api/setup/"))
    .map(([, init]) => new Headers((init as RequestInit | undefined)?.headers).get("X-Setup-Token"));
}

function statusCalls(calls: ReturnType<typeof fakeApi>["calls"]) {
  return calls.filter((call) => call.path === "/api/setup/status").length;
}

async function enterToken(value = TOKEN) {
  fireEvent.change(await screen.findByLabelText("Setup token"), { target: { value } });
  fireEvent.click(screen.getByRole("button", { name: "Continue" }));
}

/** Opens the wizard with the token kept in this tab, as after a reload. */
async function openWithStoredToken() {
  sessionStorage.setItem(SETUP_TOKEN_KEY, TOKEN);
  render(<SetupWizard />);
  await screen.findByRole("heading", { name: "1. Login" });
  // The steps can be on screen before React runs their effects, so an event
  // dispatched at once could reach no listener. The embedded sections fetch
  // in the same effects pass that adds the wizard's listeners.
  await waitFor(() =>
    expect(vi.mocked(fetch).mock.calls.some(([input]) => String(input).startsWith("/api/providers"))).toBe(true),
  );
}

/** Waits for an alert holding the text (the model section may show its own alert too). */
async function findAlert(text: string) {
  return waitFor(() => {
    const alert = screen.getAllByRole("alert").find((element) => element.textContent?.includes(text));
    expect(alert).toBeDefined();
    return alert!;
  });
}

const step = (name: string) => screen.getByRole("region", { name });

beforeEach(() => {
  sessionStorage.clear();
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
  sessionStorage.clear();
});

describe("SetupWizard", () => {
  describe("the token", () => {
    it("asks for the token first, before any step", async () => {
      const { fetchMock } = api([tokenRefused(), json(200, status())]);
      render(<SetupWizard />);

      expect(await screen.findByLabelText("Setup token")).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "1. Login" })).not.toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      // The first call carries no token: it only asks whether setup is open.
      expect(setupTokensSent(fetchMock)).toEqual([null]);

      await enterToken();

      expect(await screen.findByRole("heading", { name: "1. Login" })).toBeInTheDocument();
      expect(setupTokensSent(fetchMock)).toEqual([null, TOKEN]);
      expect(sessionStorage.getItem(SETUP_TOKEN_KEY)).toBe(TOKEN);
    });

    it("uses the token kept in this tab without asking again", async () => {
      const { fetchMock } = api(json(200, status()));

      await openWithStoredToken();

      expect(screen.queryByLabelText("Setup token")).not.toBeInTheDocument();
      expect(setupTokensSent(fetchMock)).toEqual([TOKEN]);
    });

    it("shows a refused token, forgets it, and asks for it again", async () => {
      api([tokenRefused(), tokenRefused(), json(200, status())]);
      render(<SetupWizard />);

      await enterToken("an-old-token");

      expect(await screen.findByRole("alert")).toHaveTextContent(TOKEN_REFUSED);
      expect(sessionStorage.getItem(SETUP_TOKEN_KEY)).toBeNull();
      expect(screen.getByLabelText("Setup token")).toHaveValue("");

      await enterToken();
      expect(await screen.findByRole("heading", { name: "1. Login" })).toBeInTheDocument();
    });

    it("forgets a kept token the server refuses and asks for it again", async () => {
      api(tokenRefused());
      sessionStorage.setItem(SETUP_TOKEN_KEY, "an-old-token");
      render(<SetupWizard />);

      expect(await screen.findByRole("alert")).toHaveTextContent(TOKEN_REFUSED);
      expect(screen.getByLabelText("Setup token")).toBeInTheDocument();
      expect(sessionStorage.getItem(SETUP_TOKEN_KEY)).toBeNull();
    });

    it("says setup is not open, with links to Settings and the app, when the server answers 404", async () => {
      api(closed());
      sessionStorage.setItem(SETUP_TOKEN_KEY, TOKEN);
      render(<SetupWizard />);

      expect(await screen.findByText("Setup is not open on this server.")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
      expect(screen.getByRole("link", { name: "go to the app" })).toHaveAttribute("href", "/app");
      expect(screen.queryByLabelText("Setup token")).not.toBeInTheDocument();
      expect(sessionStorage.getItem(SETUP_TOKEN_KEY)).toBeNull();
    });

    it("says setup is not open before asking for a token when it is closed", async () => {
      api(closed());
      render(<SetupWizard />);

      expect(await screen.findByText("Setup is not open on this server.")).toBeInTheDocument();
      expect(screen.queryByLabelText("Setup token")).not.toBeInTheDocument();
    });

    it("sends a logged-out user to log in and back to /setup", async () => {
      api(errorResponse(401, "unauthenticated", "Log in to continue."));
      render(<SetupWizard />);

      await waitFor(() => expect(redirectToLogin).toHaveBeenCalledWith("/setup"));
    });
  });

  describe("the steps", () => {
    it("shows the four steps with each item's state and message", async () => {
      api(json(200, status()));
      await openWithStoredToken();

      const steps = screen.getAllByRole("region").map((region) => region.getAttribute("aria-labelledby"));
      expect(steps).toEqual(["setup-login", "setup-provider", "setup-model", "setup-server"]);

      const expectations: [string, string, string, Item][] = [
        ["1. Login", "Login", "OK", ITEMS.login],
        ["1. Login", "Allow-list", "Warning", ITEMS.allow_list],
        ["2. Provider", "Search key", "Missing", ITEMS.search_key],
        ["3. Model", "Default model", "Missing", ITEMS.chat_model],
        ["4. Server", "Database", "OK", ITEMS.database],
        ["4. Server", "Key encryption key", "OK", ITEMS.encryption_key],
        ["4. Server", "Custom provider", "Info", ITEMS.custom_provider],
        ["4. Server", "Connectors", "Info", ITEMS.connectors],
      ];
      for (const [stepName, itemName, state, item] of expectations) {
        const entry = within(step(stepName)).getByRole("listitem", { name: itemName });
        expect(entry).toHaveTextContent(state);
        expect(entry).toHaveTextContent(item.message);
      }
    });

    it("shows a failed item as failed", async () => {
      api(
        json(
          200,
          status({
            search_key: {
              state: "failed",
              message:
                "Search uses Nebius Token Factory. The saved key cannot be read with the current KEY_ENCRYPTION_KEY; save it again in the provider step.",
            },
          }),
        ),
      );
      await openWithStoredToken();

      const entry = within(step("2. Provider")).getByRole("listitem", { name: "Search key" });
      expect(entry).toHaveTextContent("Failed");
      expect(entry).toHaveTextContent("cannot be read with the current KEY_ENCRYPTION_KEY");
    });

    it("shows the login settings read-only, naming the variables, with no field to change them", async () => {
      api(json(200, status()));
      await openWithStoredToken();

      const login = step("1. Login");
      expect(login).toHaveTextContent("Mode: OpenID Connect (oidc)");
      expect(login).toHaveTextContent("issuer http://localhost:1411");
      expect(login).toHaveTextContent("client id focus-funnel-client");
      expect(login).toHaveTextContent("Allow-list: none set.");
      for (const name of [
        "AUTH_MODE",
        "OIDC_ISSUER",
        "OIDC_CLIENT_ID",
        "OIDC_CLIENT_SECRET",
        "AUTH_ALLOWED_EMAILS",
      ]) {
        expect(within(login).getAllByText(name, { selector: "code" }).length).toBeGreaterThan(0);
      }
      expect(login.querySelectorAll("input, textarea, select")).toHaveLength(0);
      expect(within(login).queryAllByRole("textbox")).toHaveLength(0);
      expect(within(login).queryAllByRole("button")).toHaveLength(0);
    });

    it("shows the allow-list entries when they are set", async () => {
      api(
        json(
          200,
          status({
            allow_list: { state: "ok", message: "Allow-list: ada@example.com, bob@example.com." },
          }),
        ),
      );
      await openWithStoredToken();

      const entry = within(step("1. Login")).getByRole("listitem", { name: "Allow-list" });
      expect(entry).toHaveTextContent("OK");
      expect(entry).toHaveTextContent("ada@example.com, bob@example.com");
    });

    it("names the search provider and shows the provider settings in the provider step", async () => {
      api(json(200, status()));
      await openWithStoredToken();

      const provider = step("2. Provider");
      expect(provider).toHaveTextContent("Search uses Nebius Token Factory.");
      expect(await within(provider).findByPlaceholderText("Paste your NVIDIA API key")).toBeInTheDocument();
    });

    it("shows the model settings in the model step", async () => {
      api(json(200, status()));
      await openWithStoredToken();

      expect(await within(step("3. Model")).findByText("Chat models")).toBeInTheDocument();
    });
  });

  describe("the status follows the steps", () => {
    it("shows a refused key as the settings page does, and fetches no status", async () => {
      const REJECTED = "NVIDIA rejected this API key.";
      const routes = {
        "PUT /api/providers/nvidia/key": errorResponse(400, "provider_key_invalid", REJECTED),
      };
      const { calls } = api(json(200, status()), routes);
      await openWithStoredToken();

      const provider = step("2. Provider");
      fireEvent.change(await within(provider).findByPlaceholderText("Paste your NVIDIA API key"), {
        target: { value: "nv-wrong-abcd" },
      });
      fireEvent.click(within(provider).getByRole("button", { name: "Save" }));

      const shown = await within(provider).findByRole("alert");
      expect(shown).toHaveTextContent(REJECTED);
      expect(statusCalls(calls)).toBe(1);

      // The settings page shows the same message for the same refusal.
      const settingsPage = render(<ProvidersSettings />);
      const page = within(settingsPage.container);
      fireEvent.change(await page.findByPlaceholderText("Paste your NVIDIA API key"), {
        target: { value: "nv-wrong-abcd" },
      });
      fireEvent.click(page.getByRole("button", { name: "Save" }));
      expect((await page.findByRole("alert")).textContent).toBe(shown.textContent);
    });

    it("reads the status again after a key is saved", async () => {
      const saved = { ...nvidia, key_saved: true, key_last4: "abcd", key_saved_at: "2026-11-05T10:00:00Z" };
      const { calls } = api(
        [json(200, status()), json(200, status({ search_key: READY.search_key }))],
        { "PUT /api/providers/nvidia/key": json(200, saved) },
      );
      await openWithStoredToken();

      const provider = step("2. Provider");
      fireEvent.change(await within(provider).findByPlaceholderText("Paste your NVIDIA API key"), {
        target: { value: "nv-secret-abcd" },
      });
      fireEvent.click(within(provider).getByRole("button", { name: "Save" }));

      await waitFor(() =>
        expect(within(step("2. Provider")).getByRole("listitem", { name: "Search key" })).toHaveTextContent("OK"),
      );
      expect(statusCalls(calls)).toBe(2);
    });

    it.each([PROVIDER_KEYS_CHANGED, MODEL_SETTINGS_CHANGED])("reads the status again on %s", async (event) => {
      const { calls, fetchMock } = api([
        json(200, status()),
        json(200, status({ chat_model: READY.chat_model })),
      ]);
      await openWithStoredToken();
      expect(statusCalls(calls)).toBe(1);

      act(() => {
        window.dispatchEvent(new Event(event));
      });

      await waitFor(() =>
        expect(within(step("3. Model")).getByRole("listitem", { name: "Default model" })).toHaveTextContent("OK"),
      );
      expect(statusCalls(calls)).toBe(2);
      expect(setupTokensSent(fetchMock)).toEqual([TOKEN, TOKEN]);
    });
  });

  describe("Finish", () => {
    it("is disabled until the status is ready", async () => {
      api([json(200, status()), json(200, status(READY))]);
      await openWithStoredToken();

      expect(screen.getByRole("button", { name: "Finish" })).toBeDisabled();

      act(() => {
        window.dispatchEvent(new Event(MODEL_SETTINGS_CHANGED));
      });

      await waitFor(() => expect(screen.getByRole("button", { name: "Finish" })).toBeEnabled());
    });

    it("says setup is complete, links to the app, and forgets the token after 204", async () => {
      const { fetchMock } = api(json(200, status(READY)), {
        "POST /api/setup/complete": new Response(null, { status: 204 }),
      });
      await openWithStoredToken();

      fireEvent.click(screen.getByRole("button", { name: "Finish" }));

      expect(await screen.findByText("Setup is complete.")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Go to the app" })).toHaveAttribute("href", "/app");
      expect(sessionStorage.getItem(SETUP_TOKEN_KEY)).toBeNull();
      expect(setupTokensSent(fetchMock)).toEqual([TOKEN, TOKEN]);
    });

    it("shows a refused token, forgets it, and asks for it again after 403", async () => {
      api(json(200, status(READY)), { "POST /api/setup/complete": tokenRefused() });
      await openWithStoredToken();

      fireEvent.click(screen.getByRole("button", { name: "Finish" }));

      await findAlert(TOKEN_REFUSED);
      expect(screen.getByLabelText("Setup token")).toBeInTheDocument();
      expect(screen.queryByRole("heading", { name: "1. Login" })).not.toBeInTheDocument();
      expect(sessionStorage.getItem(SETUP_TOKEN_KEY)).toBeNull();
    });

    it("says setup is not open, with links to Settings and the app, after 404", async () => {
      api(json(200, status(READY)), { "POST /api/setup/complete": closed() });
      await openWithStoredToken();

      fireEvent.click(screen.getByRole("button", { name: "Finish" }));

      expect(await screen.findByText("Setup is not open on this server.")).toBeInTheDocument();
      expect(screen.getByRole("link", { name: "Settings" })).toHaveAttribute("href", "/settings");
      expect(screen.getByRole("link", { name: "go to the app" })).toHaveAttribute("href", "/app");
      expect(sessionStorage.getItem(SETUP_TOKEN_KEY)).toBeNull();
    });

    it("shows the missing item after 409 and reads the status again", async () => {
      const { calls } = api([json(200, status(READY)), json(200, status({ search_key: READY.search_key }))], {
        "POST /api/setup/complete": errorResponse(
          409,
          "setup_incomplete",
          "Choose a default model in the model step.",
        ),
      });
      await openWithStoredToken();

      fireEvent.click(screen.getByRole("button", { name: "Finish" }));

      await findAlert("Choose a default model in the model step.");
      await waitFor(() => expect(screen.getByRole("button", { name: "Finish" })).toBeDisabled());
      expect(statusCalls(calls)).toBe(2);
      expect(sessionStorage.getItem(SETUP_TOKEN_KEY)).toBe(TOKEN);
    });
  });
});
