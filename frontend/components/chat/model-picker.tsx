"use client";

import Link from "next/link";

import { MODEL_SETTINGS_HREF } from "@/components/model-alert";
import type { ModelChoice } from "@/lib/chat";

export type ModelOption = {
  providerId: string;
  model: string;
  /** Efforts offered for this model, from the effort table. */
  efforts: string[];
  /** The effort saved with the model in the loadout. */
  loadoutEffort: string | null;
  inLoadout: boolean;
};

export function optionKey(providerId: string, model: string): string {
  return `${providerId}\u0000${model}`;
}

// The empty value means no effort is sent, so the provider's own default applies.
const NO_EFFORT = "";

/** The model and effort dropdowns in the composer. */
export function ModelPicker({
  options,
  choice,
  disabled,
  onChange,
}: {
  options: ModelOption[];
  choice: ModelChoice | null;
  disabled: boolean;
  onChange: (choice: ModelChoice) => void;
}) {
  const selected = choice
    ? options.find((o) => o.providerId === choice.providerId && o.model === choice.model)
    : undefined;

  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      {options.length === 0 ? (
        <span>No chat model chosen.</span>
      ) : (
        <>
          <label className="flex items-center gap-1">
            <span className="sr-only">Model</span>
            <select
              aria-label="Model"
              className="max-w-64 rounded-md border bg-background px-1.5 py-1 text-xs"
              disabled={disabled}
              value={selected ? optionKey(selected.providerId, selected.model) : ""}
              onChange={(event) => {
                const option = options.find(
                  (o) => optionKey(o.providerId, o.model) === event.target.value,
                );
                if (option) {
                  onChange({
                    providerId: option.providerId,
                    model: option.model,
                    reasoningEffort: option.loadoutEffort,
                  });
                }
              }}
            >
              {!selected && <option value="">Choose a model</option>}
              {options.map((option) => (
                <option
                  key={optionKey(option.providerId, option.model)}
                  value={optionKey(option.providerId, option.model)}
                >
                  {option.model}
                  {option.inLoadout ? "" : " (not in your loadout)"}
                </option>
              ))}
            </select>
          </label>
          {selected && choice && (
            <label className="flex items-center gap-1">
              <span className="sr-only">Reasoning effort</span>
              <select
                aria-label="Reasoning effort"
                className="rounded-md border bg-background px-1.5 py-1 text-xs"
                disabled={disabled}
                value={choice.reasoningEffort ?? NO_EFFORT}
                onChange={(event) =>
                  onChange({ ...choice, reasoningEffort: event.target.value || null })
                }
              >
                <option value={NO_EFFORT}>Default effort</option>
                {selected.efforts.map((effort) => (
                  <option key={effort} value={effort}>
                    {effort}
                  </option>
                ))}
              </select>
            </label>
          )}
        </>
      )}
      <Link href={MODEL_SETTINGS_HREF} className="underline underline-offset-2 hover:text-foreground">
        Model settings
      </Link>
    </div>
  );
}
