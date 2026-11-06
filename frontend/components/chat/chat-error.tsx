import { SpendCapAlert } from "@/components/chat/spend-cap-alert";
import { ModelAlert, modelAlertCode } from "@/components/model-alert";
import { ProviderKeyAlert, providerKeyAlertCode } from "@/components/provider-key-alert";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import {
  AnswerInterruptedError,
  ContextFullError,
  ConversationBusyError,
  OutputLimitReachedError,
  ProviderRateLimitedError,
  SpendCapReachedError,
  ToolLoopLimitError,
  type ApiError,
} from "@/lib/api";

const titles = new Map<unknown, string>([
  [OutputLimitReachedError, "The model ran out of room"],
  [ToolLoopLimitError, "The answer could not be completed"],
  [ProviderRateLimitedError, "Too many requests"],
  [ContextFullError, "This conversation is full"],
  [ConversationBusyError, "Still answering"],
  [AnswerInterruptedError, "The answer did not finish"],
]);

// What the chat says instead of the backend's message.
const messages = new Map<unknown, string>([
  // The server stopped or restarted while the answer ran.
  [AnswerInterruptedError, "This answer did not finish. Send the message again to retry."],
]);

// Errors a second try can fix.
const retryable = [
  OutputLimitReachedError,
  ToolLoopLimitError,
  ProviderRateLimitedError,
  AnswerInterruptedError,
];

/**
 * Shown in place of an answer. Each error code points to the place that fixes
 * it, and the backend's message says what to do.
 */
export function ChatError({
  error,
  canRetry,
  onRetry,
}: {
  error: ApiError;
  /** False while another answer is arriving. */
  canRetry: boolean;
  onRetry: () => void;
}) {
  const keyCode = providerKeyAlertCode(error);
  if (keyCode) return <ProviderKeyAlert code={keyCode} message={error.message} />;

  const modelCode = modelAlertCode(error);
  if (modelCode) return <ModelAlert code={modelCode} message={error.message} />;

  if (error instanceof SpendCapReachedError) return <SpendCapAlert message={error.message} />;

  const title = titles.get(error.constructor);
  const canTryAgain = retryable.some((ErrorClass) => error instanceof ErrorClass);
  return (
    <Alert variant="destructive">
      {title && <AlertTitle>{title}</AlertTitle>}
      <AlertDescription className="flex flex-col items-start gap-2">
        <p>{messages.get(error.constructor) ?? error.message}</p>
        {canTryAgain && (
          <Button variant="outline" size="xs" disabled={!canRetry} onClick={onRetry}>
            Try again
          </Button>
        )}
      </AlertDescription>
    </Alert>
  );
}
