"use client";

import { PlugIcon } from "lucide-react";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ApiError } from "@/lib/api";

/** A connector as the picker lists it. */
export type PickerConnector = {
  id: string;
  name: string;
  /** Its tools that are available and switched on in settings. */
  tools: number;
};

function plural(count: number, word: string): string {
  return `${count} ${word}${count === 1 ? "" : "s"}`;
}

/**
 * The connectors toggle beside the model picker: a checkbox per connector,
 * and how many connector tools are on against the limit. Hidden while
 * connectors are off (`connectors` is null). A connector with no switched-on
 * tools is listed but cannot be turned on. A change applies from the next
 * turn; a refused one (for example `too_many_tools`) shows the server's message.
 */
export function ConnectorPicker({
  connectors,
  on,
  maxTools,
  canChange,
  disabled,
  onChange,
}: {
  connectors: PickerConnector[] | null;
  /** The ids of the connectors that are on in the conversation. */
  on: string[];
  maxTools: number;
  /** False until the conversation exists: a new one starts with none on. */
  canChange: boolean;
  disabled: boolean;
  onChange: (connectorIds: string[]) => Promise<void>;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (connectors === null) return null;

  const toolsOn = connectors
    .filter((connector) => on.includes(connector.id))
    .reduce((sum, connector) => sum + connector.tools, 0);
  const count = `${toolsOn} of ${maxTools} tools`;

  async function toggle(id: string, checked: boolean) {
    setBusy(true);
    setError(null);
    try {
      await onChange(checked ? [...on, id] : on.filter((other) => other !== id));
    } catch (caught) {
      setError(
        caught instanceof ApiError ? caught.message : "Could not change the connectors. Try again.",
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-1">
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button
              variant="ghost"
              size="sm"
              className="h-7 gap-1 px-1.5 text-xs text-muted-foreground"
              aria-label={`Connectors: ${on.length} on, ${count}`}
              disabled={disabled}
            />
          }
        >
          <PlugIcon aria-hidden />
          Connectors{on.length > 0 ? ` (${on.length})` : ""}
        </DropdownMenuTrigger>
        <DropdownMenuContent className="w-64">
          <DropdownMenuGroup>
            <DropdownMenuLabel data-testid="connector-tool-count">{count}</DropdownMenuLabel>
            {!canChange && (
              <DropdownMenuLabel className="font-normal">
                Send a message first, then turn connectors on for this conversation.
              </DropdownMenuLabel>
            )}
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          {connectors.length === 0 ? (
            <DropdownMenuGroup>
              <DropdownMenuLabel className="font-normal">
                No connectors yet. Add one in settings.
              </DropdownMenuLabel>
            </DropdownMenuGroup>
          ) : (
            connectors.map((connector) => {
              const isOn = on.includes(connector.id);
              return (
                <DropdownMenuCheckboxItem
                  key={connector.id}
                  checked={isOn}
                  // A connector that is on can always be turned off.
                  disabled={!canChange || busy || (!isOn && connector.tools === 0)}
                  onCheckedChange={(checked) => void toggle(connector.id, checked)}
                >
                  <span className="flex flex-col">
                    <span>{connector.name}</span>
                    <span className="text-xs text-muted-foreground">
                      {connector.tools === 0
                        ? "No tools switched on in settings"
                        : plural(connector.tools, "tool")}
                    </span>
                  </span>
                </DropdownMenuCheckboxItem>
              );
            })
          )}
        </DropdownMenuContent>
      </DropdownMenu>
      {error && (
        <p role="alert" className="text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
