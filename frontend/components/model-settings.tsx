"use client";

import { useEffect, useState } from "react";

import { ProviderKeyAlert, providerKeyAlertCode } from "@/components/provider-key-alert";
import type { ProviderStatus } from "@/components/providers-settings";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { ApiError, apiFetch, UnauthenticatedError } from "@/lib/api";
import {
  getEfforts,
  getModelSettings,
  getProviderModels,
  saveModelSettings,
  testModel,
  type ModelSettings,
  type ProviderModel,
} from "@/lib/models";
import { redirectToLogin } from "@/lib/redirect-to-login";

type Slot = {
  key: number;
  providerId: string;
  model: string;
  effort: string | null;
  efforts: string[];
};

type ModelList = { models: ProviderModel[] } | { error: ApiError };

function messageFor(error: unknown): string {
  return error instanceof ApiError ? error.message : "Something went wrong. Try again.";
}

/** A provider the user can choose models from: one with a saved key, or a saved keyless one. */
function usable(provider: ProviderStatus): boolean {
  return provider.key_saved || (!provider.key_required && Boolean(provider.key_saved_at));
}

/**
 * The chat model settings: a loadout of up to five models, one marked as the
 * default, an effort for each, and one temperature. There is deliberately no
 * reply length field: the server applies its own limit.
 */
export function ModelSettingsSection() {
  const [settings, setSettings] = useState<ModelSettings | null>(null);
  const [providers, setProviders] = useState<ProviderStatus[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [slots, setSlots] = useState<Slot[]>([]);
  const [defaultKey, setDefaultKey] = useState<number | null>(null);
  const [temperature, setTemperature] = useState("");
  const [lists, setLists] = useState<Record<string, ModelList>>({});
  const [busy, setBusy] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [nextKey, setNextKey] = useState(1);

  function applySettings(loaded: ModelSettings, firstKey: number) {
    setSettings(loaded);
    const loadedSlots = loaded.models.map((entry, index) => ({
      key: firstKey + index,
      providerId: entry.provider_id,
      model: entry.model,
      effort: entry.reasoning_effort,
      efforts: entry.efforts,
    }));
    setSlots(loadedSlots);
    const defaultIndex = loaded.models.findIndex((entry) => entry.is_default);
    setDefaultKey(defaultIndex === -1 ? null : firstKey + defaultIndex);
    setTemperature(loaded.temperature === null ? "" : String(loaded.temperature));
    setNextKey(firstKey + loaded.models.length);
  }

  useEffect(() => {
    let cancelled = false;
    Promise.all([
      getModelSettings(),
      apiFetch<{ providers: ProviderStatus[] }>("/api/providers"),
    ]).then(
      ([loaded, providerList]) => {
        if (cancelled) return;
        applySettings(loaded, 1);
        setProviders(providerList.providers);
      },
      (error: unknown) => {
        if (cancelled) return;
        if (error instanceof UnauthenticatedError) {
          redirectToLogin("/settings");
          return;
        }
        setLoadError(messageFor(error));
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  // Load each provider's model list once, for the choosers.
  const providerIds = [...new Set(slots.map((slot) => slot.providerId).filter(Boolean))];
  useEffect(() => {
    for (const providerId of providerIds) {
      if (lists[providerId]) continue;
      getProviderModels(providerId).then(
        (models) => setLists((current) => ({ ...current, [providerId]: { models } })),
        (error: unknown) =>
          setLists((current) => ({
            ...current,
            [providerId]: {
              error: error instanceof ApiError ? error : new ApiError("unknown_error", messageFor(error), 0),
            },
          })),
      );
    }
    // providerIds is derived from slots; a changed list is keyed by its ids.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [providerIds.join("\u0000"), lists]);

  if (loadError) {
    return (
      <Alert variant="destructive">
        <AlertDescription>{loadError}</AlertDescription>
      </Alert>
    );
  }
  if (!settings || !providers) {
    return <p className="text-sm text-muted-foreground">Loading model settings…</p>;
  }

  const choosable = providers.filter(usable);
  const full = slots.length >= settings.max_models;
  const defaultSlot = slots.find((slot) => slot.key === defaultKey);

  function update(key: number, change: Partial<Slot>) {
    setSaved(false);
    setSlots((current) => current.map((slot) => (slot.key === key ? { ...slot, ...change } : slot)));
  }

  async function chooseModel(slot: Slot, model: string) {
    update(slot.key, { model, effort: null, efforts: [] });
    if (!model) return;
    try {
      update(slot.key, { model, effort: null, efforts: await getEfforts(model) });
    } catch {
      // The effort choice stays empty; saving still works without one.
    }
  }

  async function addSlot() {
    if (full) return;
    // A key may have been saved in the providers section since this page loaded.
    let current = choosable;
    try {
      const refreshed = await apiFetch<{ providers: ProviderStatus[] }>("/api/providers");
      setProviders(refreshed.providers);
      current = refreshed.providers.filter(usable);
    } catch {
      // Keep the list already shown.
    }
    // A list that failed for want of a key is fetched again.
    setLists((loaded) =>
      Object.fromEntries(Object.entries(loaded).filter(([, list]) => !("error" in list))),
    );
    const providerId = current[0]?.id ?? "";
    setSlots((current) => [
      ...current,
      { key: nextKey, providerId, model: "", effort: null, efforts: [] },
    ]);
    if (slots.length === 0) setDefaultKey(nextKey);
    setNextKey((key) => key + 1);
    setSaved(false);
  }

  function removeSlot(key: number) {
    setSlots((current) => current.filter((slot) => slot.key !== key));
    if (defaultKey === key) setDefaultKey(null);
    setSaved(false);
  }

  async function save() {
    setSaveError(null);
    setSaved(false);
    const incomplete = slots.find((slot) => !slot.providerId || !slot.model);
    if (incomplete) {
      setSaveError("Choose a model in every slot, or remove the empty slot.");
      return;
    }
    const value = temperature.trim() === "" ? null : Number(temperature);
    if (value !== null && Number.isNaN(value)) {
      setSaveError("Temperature must be a number.");
      return;
    }
    setBusy(true);
    try {
      const result = await saveModelSettings(
        slots.map((slot) => ({
          provider_id: slot.providerId,
          model: slot.model,
          reasoning_effort: slot.effort,
          is_default: slot.key === defaultKey,
        })),
        value,
      );
      applySettings(result, nextKey);
      setSaved(true);
    } catch (error) {
      if (error instanceof UnauthenticatedError) {
        redirectToLogin("/settings");
        return;
      }
      // The form keeps what the user entered, and the stored settings are unchanged.
      setSaveError(messageFor(error));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card id="models">
      <CardHeader>
        <CardTitle>Chat models</CardTitle>
        <CardDescription>{settings.model_hint}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {choosable.length === 0 && (
          <ProviderKeyAlert
            code="provider_key_missing"
            message="Add a provider API key to choose chat models."
          />
        )}

        <p className="text-sm">
          Default model:{" "}
          <span className="font-medium">
            {defaultSlot && defaultSlot.model ? defaultSlot.model : "Not set"}
          </span>
        </p>

        <ol aria-label="Loadout" className="flex flex-col gap-3">
          {slots.map((slot, index) => (
            <ModelSlot
              key={slot.key}
              index={index}
              slot={slot}
              providers={choosable}
              list={lists[slot.providerId]}
              isDefault={slot.key === defaultKey}
              busy={busy}
              onProvider={(providerId) =>
                update(slot.key, { providerId, model: "", effort: null, efforts: [] })
              }
              onModel={(model) => chooseModel(slot, model)}
              onEffort={(effort) => update(slot.key, { effort })}
              onDefault={() => {
                setDefaultKey(slot.key);
                setSaved(false);
              }}
              onRemove={() => removeSlot(slot.key)}
            />
          ))}
        </ol>

        <div className="flex flex-wrap items-center gap-2">
          <Button type="button" variant="outline" onClick={addSlot} disabled={full || busy}>
            Add a model
          </Button>
          {full && (
            <span className="text-sm text-muted-foreground">
              The loadout is full: it holds at most {settings.max_models} models.
            </span>
          )}
        </div>

        <label className="flex flex-col gap-1 text-sm">
          <span>Temperature</span>
          <Input
            type="number"
            aria-label="Temperature"
            className="w-32"
            step="0.1"
            min={settings.temperature_min}
            max={settings.temperature_max}
            placeholder={String(settings.temperature_default)}
            value={temperature}
            onChange={(event) => {
              setTemperature(event.target.value);
              setSaved(false);
            }}
            disabled={busy}
          />
          <span className="text-xs text-muted-foreground">
            {temperature.trim() === ""
              ? `Using the system default, ${settings.temperature_default}.`
              : `Between ${settings.temperature_min} and ${settings.temperature_max}.`}
          </span>
        </label>

        {saveError && (
          <Alert variant="destructive">
            <AlertDescription>{saveError}</AlertDescription>
          </Alert>
        )}
        {saved && <p className="text-sm text-muted-foreground">Saved.</p>}

        <div>
          <Button type="button" onClick={save} disabled={busy}>
            {busy ? "Checking…" : "Save models"}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function ModelSlot({
  index,
  slot,
  providers,
  list,
  isDefault,
  busy,
  onProvider,
  onModel,
  onEffort,
  onDefault,
  onRemove,
}: {
  index: number;
  slot: Slot;
  providers: ProviderStatus[];
  list: ModelList | undefined;
  isDefault: boolean;
  busy: boolean;
  onProvider: (providerId: string) => void;
  onModel: (model: string) => void;
  onEffort: (effort: string | null) => void;
  onDefault: () => void;
  onRemove: () => void;
}) {
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);
  const label = `Model ${index + 1}`;
  const models = list && "models" in list ? list.models : [];
  const listError = list && "error" in list ? list.error : null;
  const keyCode = listError ? providerKeyAlertCode(listError) : null;
  const listed = models.find((model) => model.id === slot.model);
  // A saved model the list no longer has is still shown, so the choice is visible.
  const options = listed || !slot.model ? models : [...models, { id: slot.model, features: { tool_calling: "unknown" } }];

  async function runTest() {
    setTesting(true);
    setTestResult(null);
    try {
      const result = await testModel({
        provider_id: slot.providerId,
        model: slot.model,
        reasoning_effort: slot.effort,
      });
      setTestResult({ ok: true, message: result.message });
    } catch (error) {
      setTestResult({ ok: false, message: messageFor(error) });
    } finally {
      setTesting(false);
    }
  }

  return (
    <li className="flex flex-col gap-2 rounded-lg border p-3" aria-label={label}>
      <div className="flex flex-wrap items-center gap-2">
        <select
          aria-label={`${label} provider`}
          className="rounded-md border bg-background px-2 py-1 text-sm"
          value={slot.providerId}
          disabled={busy}
          onChange={(event) => onProvider(event.target.value)}
        >
          {!slot.providerId && <option value="">Choose a provider</option>}
          {providers.map((provider) => (
            <option key={provider.id} value={provider.id}>
              {provider.label}
            </option>
          ))}
        </select>
        <select
          aria-label={`${label} model`}
          className="max-w-72 rounded-md border bg-background px-2 py-1 text-sm"
          value={slot.model}
          disabled={busy || Boolean(listError)}
          onChange={(event) => onModel(event.target.value)}
        >
          <option value="">{list ? "Choose a model" : "Loading models…"}</option>
          {options.map((model) => (
            <option key={model.id} value={model.id}>
              {model.id}
            </option>
          ))}
        </select>
        <select
          aria-label={`${label} reasoning effort`}
          className="rounded-md border bg-background px-2 py-1 text-sm"
          value={slot.effort ?? ""}
          disabled={busy || !slot.model}
          onChange={(event) => onEffort(event.target.value || null)}
        >
          <option value="">Default effort</option>
          {slot.efforts.map((effort) => (
            <option key={effort} value={effort}>
              {effort}
            </option>
          ))}
        </select>
      </div>
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <label className="flex items-center gap-1">
          <input
            type="radio"
            name="default-model"
            checked={isDefault}
            disabled={busy}
            onChange={onDefault}
          />
          Default
        </label>
        <Button
          type="button"
          variant="outline"
          size="xs"
          disabled={busy || testing || !slot.model}
          onClick={runTest}
        >
          {testing ? "Testing…" : "Test"}
        </Button>
        <Button type="button" variant="ghost" size="xs" disabled={busy} onClick={onRemove}>
          Remove
        </Button>
      </div>
      {listed && listed.features.tool_calling !== "supported" && (
        <p className="text-xs text-muted-foreground">
          Unconfirmed: the provider does not report tool calling for this model. Use Test to check
          it.
        </p>
      )}
      {keyCode && <ProviderKeyAlert code={keyCode} message={listError!.message} />}
      {listError && !keyCode && <p className="text-xs text-destructive">{listError.message}</p>}
      {testResult && (
        <p className={`text-xs ${testResult.ok ? "text-muted-foreground" : "text-destructive"}`}>
          {testResult.message}
        </p>
      )}
    </li>
  );
}
