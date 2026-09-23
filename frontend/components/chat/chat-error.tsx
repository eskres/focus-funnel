import { ProviderKeyAlert, providerKeyAlertCode } from "@/components/provider-key-alert";
import { Alert, AlertDescription } from "@/components/ui/alert";
import type { ApiError } from "@/lib/api";

/** Shown in place of an answer. Each error code points to the place that fixes it. */
export function ChatError({ error }: { error: ApiError }) {
  const keyCode = providerKeyAlertCode(error);
  if (keyCode) return <ProviderKeyAlert code={keyCode} message={error.message} />;

  return (
    <Alert variant="destructive">
      <AlertDescription>{error.message}</AlertDescription>
    </Alert>
  );
}
