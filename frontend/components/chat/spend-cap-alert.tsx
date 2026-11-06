import Link from "next/link";

import { USAGE_SETTINGS_HREF } from "@/components/chat/chat-notices";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";

/**
 * The month's usage reached the spend cap. `message` is the backend's message,
 * which names the cap, or the chat's own text for a stored answer that ended
 * at the cap. The fix is in the usage settings.
 */
export function SpendCapAlert({ message }: { message: string }) {
  return (
    <Alert variant="destructive">
      <AlertTitle>Monthly spend cap reached</AlertTitle>
      <AlertDescription>
        <p>
          <span>{message}</span> <Link href={USAGE_SETTINGS_HREF}>Go to usage settings</Link>
        </p>
      </AlertDescription>
    </Alert>
  );
}
