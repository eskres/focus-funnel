import Link from "next/link";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import type { UsageWarning } from "@/lib/models";

export const USAGE_SETTINGS_HREF = "/settings#usage";

export function formatThreshold(warning: UsageWarning): string {
  return warning.unit === "usd"
    ? `$${warning.amount.toLocaleString("en", { minimumFractionDigits: 2, maximumFractionDigits: 6 })}`
    : `${warning.amount.toLocaleString("en")} tokens`;
}

/** Suggests /compact once the context passes the soft limit. It never blocks sending. */
export function CompactNotice({
  share,
  canAct,
  onCompact,
  onDismiss,
}: {
  /** The share of the context in use, 0 to 1, when known. */
  share: number | null;
  canAct: boolean;
  onCompact: () => void;
  onDismiss: () => void;
}) {
  const used = share === null ? "" : ` ${Math.round(share * 100)}% of the model's context is in use.`;
  return (
    <Alert>
      <AlertDescription className="flex flex-wrap items-center gap-2 text-pretty!">
        <span>
          This conversation is getting long.{used} Compact it to summarise the older messages, or
          carry on.
        </span>
        <Button size="xs" disabled={!canAct} onClick={onCompact}>
          Compact now
        </Button>
        <Button size="xs" variant="ghost" onClick={onDismiss}>
          Not now
        </Button>
      </AlertDescription>
    </Alert>
  );
}

/** Shown once a month when usage reaches the user's warning threshold. The chat carries on. */
export function UsageWarningNotice({
  warning,
  onDismiss,
}: {
  warning: UsageWarning;
  onDismiss: () => void;
}) {
  return (
    <Alert>
      <AlertDescription className="flex flex-wrap items-center gap-2 text-pretty!">
        <span>
          Your usage this month has reached your warning threshold of {formatThreshold(warning)}.
          You can keep chatting.
        </span>
        <Link href={USAGE_SETTINGS_HREF} className="underline underline-offset-2">
          See usage
        </Link>
        <Button size="xs" variant="ghost" onClick={onDismiss}>
          Dismiss
        </Button>
      </AlertDescription>
    </Alert>
  );
}
