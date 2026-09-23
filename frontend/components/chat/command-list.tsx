import { COMMANDS } from "@/lib/chat";

export function CommandList() {
  return (
    <div className="mx-auto flex max-w-md flex-col gap-3 text-center">
      <h2 className="text-lg font-semibold tracking-tight">What is on your mind?</h2>
      <p className="text-sm text-muted-foreground">
        Write freely, or start a message with a command.
      </p>
      <ul className="flex flex-col gap-2 text-left text-sm">
        {COMMANDS.map(({ command, description }) => (
          <li key={command} className="flex items-baseline gap-3">
            <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">{command}</code>
            <span className="text-muted-foreground">{description}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
