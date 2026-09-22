import Link from "next/link";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { ProviderKeyMissingError, ProviderKeyRejectedError } from "@/lib/api";

export type ProviderKeyAlertCode = "provider_key_missing" | "provider_key_rejected";

const titles: Record<ProviderKeyAlertCode, string> = {
  provider_key_missing: "No API key saved",
  provider_key_rejected: "Your API key no longer works",
};

/** Returns the alert code for errors this component can show, else null. */
export function providerKeyAlertCode(error: unknown): ProviderKeyAlertCode | null {
  if (error instanceof ProviderKeyMissingError) return "provider_key_missing";
  if (error instanceof ProviderKeyRejectedError) return "provider_key_rejected";
  return null;
}

/**
 * `message` is the backend's error message, which already names the
 * provider (for example "Add your NVIDIA API key in settings to use this
 * feature."), so the alert doesn't need its own copy of provider names.
 */
export function ProviderKeyAlert({
  code,
  message,
}: {
  code: ProviderKeyAlertCode;
  message: string;
}) {
  return (
    <Alert variant="destructive">
      <AlertTitle>{titles[code]}</AlertTitle>
      <AlertDescription>
        <p>
          {message} <Link href="/settings">Go to provider settings</Link>
        </p>
      </AlertDescription>
    </Alert>
  );
}
