// Typed client for the model settings (`/api/settings/models`).
import { apiFetch } from "@/lib/api";

export const MODEL_SETTINGS_ENDPOINT = "/api/settings/models";

export type LoadoutEntry = {
  provider_id: string;
  model: string;
  reasoning_effort: string | null;
  is_default: boolean;
  efforts: string[];
  tool_calling?: string;
  unconfirmed?: boolean;
  context_length?: number;
};

export type ModelSettings = {
  models: LoadoutEntry[];
  temperature: number | null;
  temperature_default: number;
  temperature_min: number;
  temperature_max: number;
  max_models: number;
  model_hint: string;
};

export type LoadoutEntryInput = {
  provider_id: string;
  model: string;
  reasoning_effort: string | null;
  is_default: boolean;
};

export type ProviderModel = {
  id: string;
  context_length?: number;
  prices?: { prompt: string; completion: string };
  features: { tool_calling: "supported" | "unconfirmed" | "unknown" | string };
};

export function getModelSettings(): Promise<ModelSettings> {
  return apiFetch<ModelSettings>(MODEL_SETTINGS_ENDPOINT);
}

export function saveModelSettings(
  models: LoadoutEntryInput[],
  temperature: number | null,
): Promise<ModelSettings> {
  return apiFetch<ModelSettings>(MODEL_SETTINGS_ENDPOINT, {
    method: "PUT",
    body: JSON.stringify({ models, temperature }),
  });
}

export async function getEfforts(model: string): Promise<string[]> {
  const result = await apiFetch<{ efforts: string[] }>(
    `${MODEL_SETTINGS_ENDPOINT}/efforts?model=${encodeURIComponent(model)}`,
  );
  return result.efforts;
}

export function testModel(entry: {
  provider_id: string;
  model: string;
  reasoning_effort: string | null;
}): Promise<{ ok: boolean; model: string; message: string }> {
  return apiFetch(`${MODEL_SETTINGS_ENDPOINT}/test`, {
    method: "POST",
    body: JSON.stringify(entry),
  });
}

export async function getProviderModels(providerId: string): Promise<ProviderModel[]> {
  const result = await apiFetch<{ models: ProviderModel[] }>(
    `/api/providers/${encodeURIComponent(providerId)}/models`,
  );
  return result.models;
}
