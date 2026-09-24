import { cn } from "@/lib/utils";

/** How full the conversation's context is, for the meter by the composer. */
export type Meter = {
  tokens: number;
  /** True until the next answer reports the model's own count, for example after a model switch. */
  estimated: boolean;
  /** Unknown when the provider does not report it. */
  contextLength: number | null;
};

const compact = new Intl.NumberFormat("en", { notation: "compact", maximumFractionDigits: 1 });

export function formatTokens(tokens: number): string {
  return compact.format(tokens).toLowerCase();
}

/** A small bar and figure: the tokens in use against the model's context length. */
export function ContextMeter({ meter }: { meter: Meter | null }) {
  if (!meter) return null;
  const { tokens, estimated, contextLength } = meter;
  const share = contextLength ? tokens / contextLength : null;
  const over = share !== null && share > 1;
  const figure = contextLength
    ? `${estimated ? "About " : ""}${formatTokens(tokens)} of ${formatTokens(contextLength)} tokens`
    : `${estimated ? "About " : ""}${formatTokens(tokens)} tokens in use`;

  return (
    <div
      className={cn(
        "flex items-center gap-2 text-xs",
        over ? "text-destructive" : "text-muted-foreground",
      )}
    >
      {share !== null && (
        <div
          role="meter"
          aria-label="Context used"
          aria-valuemin={0}
          aria-valuemax={contextLength ?? undefined}
          aria-valuenow={tokens}
          aria-valuetext={figure}
          className="h-1.5 w-16 overflow-hidden rounded-full bg-muted"
        >
          <div
            className={cn("h-full rounded-full", over ? "bg-destructive" : "bg-primary/70")}
            style={{ width: `${Math.min(share, 1) * 100}%` }}
          />
        </div>
      )}
      <span data-testid="context-figure">
        {figure}
        {over && ", over the limit"}
        {estimated && (
          <span title="Models count tokens differently. The figure is exact after the next answer.">
            {" "}
            (estimate)
          </span>
        )}
      </span>
    </div>
  );
}
