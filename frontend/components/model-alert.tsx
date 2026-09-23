import Link from "next/link";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  ModelNotSetError,
  ModelUnavailableError,
  ModelUnknownError,
  ModelUnsupportedError,
} from "@/lib/api";

export type ModelAlertCode =
  | "model_not_set"
  | "model_unknown"
  | "model_unsupported"
  | "model_unavailable";

export const MODEL_SETTINGS_HREF = "/settings#models";

const titles: Record<ModelAlertCode, string> = {
  model_not_set: "No chat model chosen",
  model_unknown: "This model is not in your list",
  model_unsupported: "This model cannot be used for chat",
  model_unavailable: "This model is not available",
};

/** Returns the alert code for errors this component can show, else null. */
export function modelAlertCode(error: unknown): ModelAlertCode | null {
  if (error instanceof ModelNotSetError) return "model_not_set";
  if (error instanceof ModelUnknownError) return "model_unknown";
  if (error instanceof ModelUnsupportedError) return "model_unsupported";
  if (error instanceof ModelUnavailableError) return "model_unavailable";
  return null;
}

/** `message` is the backend's message, which names the model when there is one. */
export function ModelAlert({ code, message }: { code: ModelAlertCode; message: string }) {
  return (
    <Alert variant="destructive">
      <AlertTitle>{titles[code]}</AlertTitle>
      <AlertDescription>
        <p>
          {message} <Link href={MODEL_SETTINGS_HREF}>Go to model settings</Link>
        </p>
      </AlertDescription>
    </Alert>
  );
}
