// @vitest-environment jsdom
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { errorResponse, fakeApi, json, loadout, loadoutEntry } from "@/test/fake-api";

import { ModelSettingsSection } from "./model-settings";

vi.mock("@/lib/redirect-to-login", () => ({ redirectToLogin: vi.fn() }));

afterEach(() => {
  vi.unstubAllGlobals();
  vi.clearAllMocks();
});

const nebius = {
  id: "nebius",
  label: "Nebius Token Factory",
  key_url: "",
  notice: "",
  key_required: true,
  is_custom: false,
  key_saved: true,
  key_saved_at: "2026-09-23T10:00:00Z",
};
const nvidiaNoKey = { ...nebius, id: "nvidia", label: "NVIDIA", key_saved: false, key_saved_at: undefined };

const NANO = "vendor/nano";
const BIG = "vendor/big";
const QUIET = "vendor/quiet";
const models = {
  models: [
    { id: NANO, context_length: 131072, features: { tool_calling: "supported" } },
    { id: BIG, context_length: 262144, features: { tool_calling: "supported" } },
    { id: QUIET, features: { tool_calling: "unconfirmed" } },
  ],
};

function api(settings = loadout(), extra: Parameters<typeof fakeApi>[0] = {}) {
  return fakeApi({
    "GET /api/settings/models": json(200, settings),
    "GET /api/providers": json(200, { providers: [nebius, nvidiaNoKey], custom_provider_allowed: true }),
    "GET /api/providers/nebius/models": json(200, models),
    "GET /api/settings/models/efforts": json(200, { efforts: ["low", "medium", "high"] }),
    ...extra,
  });
}

async function addModel(model: string, slot: number) {
  fireEvent.click(screen.getByRole("button", { name: "Add a model" }));
  const select = await screen.findByLabelText(`Model ${slot} model`);
  await within(select).findByRole("option", { name: model });
  fireEvent.change(select, { target: { value: model } });
}

describe("ModelSettingsSection", () => {
  it("shows the default as not set, with the hint, on a first visit", async () => {
    api();
    render(<ModelSettingsSection />);

    expect(await screen.findByText("Not set")).toBeInTheDocument();
    expect(screen.getByText("Pick a model that supports tool calling.")).toBeInTheDocument();
    expect(screen.getByText("Using the system default, 0.3.")).toBeInTheDocument();
  });

  it("has no reply length field", async () => {
    api();
    render(<ModelSettingsSection />);
    await screen.findByText("Not set");

    expect(screen.queryByLabelText(/token/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/max.*tokens|reply length/i)).not.toBeInTheDocument();
  });

  it("shows the saved loadout with the default marked", async () => {
    api(
      loadout(
        [
          loadoutEntry(NANO, { reasoning_effort: "low", efforts: ["low", "high"] }),
          loadoutEntry(BIG, { is_default: true }),
        ],
        { temperature: 0.7 },
      ),
    );
    render(<ModelSettingsSection />);

    await waitFor(() => expect(screen.getByLabelText("Model 1 model")).toHaveDisplayValue(NANO));
    expect(screen.getByText(BIG, { selector: "span" })).toBeInTheDocument();
    expect(screen.getByLabelText("Model 1 reasoning effort")).toHaveDisplayValue("low");
    expect(screen.getByLabelText("Temperature")).toHaveValue(0.7);
    const second = screen.getByRole("listitem", { name: "Model 2" });
    expect(within(second).getByRole("radio")).toBeChecked();
  });

  it("adds a model and saves the loadout, default, effort, and temperature", async () => {
    const { calls } = api(loadout(), {
      "PUT /api/settings/models": json(
        200,
        loadout([loadoutEntry(NANO, { is_default: true, reasoning_effort: "medium" })], {
          temperature: 0.5,
        }),
      ),
    });
    render(<ModelSettingsSection />);
    await screen.findByText("Not set");

    await addModel(NANO, 1);
    const effort = screen.getByLabelText("Model 1 reasoning effort");
    await within(effort).findByRole("option", { name: "medium" });
    fireEvent.change(effort, { target: { value: "medium" } });
    fireEvent.change(screen.getByLabelText("Temperature"), { target: { value: "0.5" } });
    fireEvent.click(screen.getByRole("button", { name: "Save models" }));

    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    expect(calls.find((c) => c.method === "PUT")?.body).toEqual({
      models: [{ provider_id: "nebius", model: NANO, reasoning_effort: "medium", is_default: true }],
      temperature: 0.5,
    });
  });

  it("marks a model that does not report tool calling as unconfirmed", async () => {
    api();
    render(<ModelSettingsSection />);
    await screen.findByText("Not set");

    await addModel(QUIET, 1);

    expect(await screen.findByText(/Unconfirmed: the provider does not report tool calling/)).toBeInTheDocument();
  });

  it("refuses a sixth model", async () => {
    api(loadout([1, 2, 3, 4, 5].map((n) => loadoutEntry(`vendor/m${n}`))));
    render(<ModelSettingsSection />);

    const add = await screen.findByRole("button", { name: "Add a model" });
    expect(add).toBeDisabled();
    expect(screen.getByText("The loadout is full: it holds at most 5 models.")).toBeInTheDocument();
  });

  describe("refusals and Test", () => {
    it("shows a model_unknown refusal naming the model and keeps the values", async () => {
      api(loadout(), {
        "PUT /api/settings/models": errorResponse(
          400,
          "model_unknown",
          `Nebius Token Factory does not list the model '${BIG}' for your key.`,
        ),
      });
      render(<ModelSettingsSection />);
      await screen.findByText("Not set");
      await addModel(BIG, 1);
      fireEvent.change(screen.getByLabelText("Temperature"), { target: { value: "0.9" } });

      fireEvent.click(screen.getByRole("button", { name: "Save models" }));

      expect(await screen.findByRole("alert")).toHaveTextContent(BIG);
      expect(screen.getByLabelText("Model 1 model")).toHaveDisplayValue(BIG);
      expect(screen.getByLabelText("Temperature")).toHaveValue(0.9);
      expect(screen.queryByText("Saved.")).not.toBeInTheDocument();
    });

    it("reports a test success naming the model", async () => {
      const { calls } = api(loadout([loadoutEntry(NANO, { reasoning_effort: "low", efforts: ["low"] })]), {
        "POST /api/settings/models/test": json(200, {
          ok: true,
          model: NANO,
          message: `${NANO} answered and called the probe tool.`,
        }),
      });
      render(<ModelSettingsSection />);
      await waitFor(() => expect(screen.getByLabelText("Model 1 model")).toHaveDisplayValue(NANO));

      fireEvent.click(screen.getByRole("button", { name: "Test" }));

      expect(await screen.findByText(`${NANO} answered and called the probe tool.`)).toBeInTheDocument();
      expect(calls.find((c) => c.path.endsWith("/test"))?.body).toEqual({
        provider_id: "nebius",
        model: NANO,
        reasoning_effort: "low",
      });
    });

    it("reports an empty-answer failure naming the effort, and changes nothing", async () => {
      const { calls } = api(loadout([loadoutEntry(NANO, { reasoning_effort: "none", efforts: ["none"] })]), {
        "POST /api/settings/models/test": errorResponse(
          400,
          "model_unsupported",
          `The model '${NANO}' returned an empty answer with reasoning effort 'none'.`,
        ),
      });
      render(<ModelSettingsSection />);
      await waitFor(() => expect(screen.getByLabelText("Model 1 model")).toHaveDisplayValue(NANO));

      fireEvent.click(screen.getByRole("button", { name: "Test" }));

      expect(await screen.findByText(/empty answer with reasoning effort 'none'/)).toBeInTheDocument();
      expect(screen.getByLabelText("Model 1 reasoning effort")).toHaveDisplayValue("none");
      expect(calls.some((c) => c.method === "PUT")).toBe(false);
    });
  });

  describe("provider keys", () => {
    it("shows the key alert with a link and empty choosers when a model list needs a key", async () => {
      api(loadout([loadoutEntry(NANO)]), {
        "GET /api/providers/nebius/models": errorResponse(
          409,
          "provider_key_missing",
          "Add your Nebius Token Factory API key in settings to use this feature.",
        ),
      });
      render(<ModelSettingsSection />);

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent("No API key saved");
      expect(within(alert).getByRole("link", { name: "Go to provider settings" })).toHaveAttribute(
        "href",
        "/settings",
      );
      expect(screen.getByLabelText("Model 1 model")).toBeDisabled();
    });

    it("says a provider key is needed when no provider has one", async () => {
      fakeApi({
        "GET /api/settings/models": json(200, loadout()),
        "GET /api/providers": json(200, { providers: [nvidiaNoKey], custom_provider_allowed: true }),
      });
      render(<ModelSettingsSection />);

      const alert = await screen.findByRole("alert");
      expect(alert).toHaveTextContent("Add a provider API key to choose chat models.");
      expect(within(alert).getByRole("link", { name: "Go to provider settings" })).toBeInTheDocument();
    });
  });
});
