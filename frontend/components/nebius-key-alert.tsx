import Link from "next/link";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  NebiusKeyMissingError,
  NebiusKeyRejectedError,
} from "@/lib/api";

export type NebiusKeyAlertCode = "nebius_key_missing" | "nebius_key_rejected";

const messages: Record<NebiusKeyAlertCode, { title: string; description: string }> = {
  nebius_key_missing: {
    title: "No Nebius API key saved",
    description: "This feature needs your Nebius API key. Add one to continue.",
  },
  nebius_key_rejected: {
    title: "Your Nebius API key no longer works",
    description: "Nebius rejected your saved API key. Replace it to continue.",
  },
};

/** Returns the alert code for errors this component can show, else null. */
export function nebiusKeyAlertCode(error: unknown): NebiusKeyAlertCode | null {
  if (error instanceof NebiusKeyMissingError) return "nebius_key_missing";
  if (error instanceof NebiusKeyRejectedError) return "nebius_key_rejected";
  return null;
}

export function NebiusKeyAlert({ code }: { code: NebiusKeyAlertCode }) {
  const { title, description } = messages[code];
  return (
    <Alert variant="destructive">
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription>
        <p>
          {description} <Link href="/settings">Go to API key settings</Link>
        </p>
      </AlertDescription>
    </Alert>
  );
}
