"use client";

import type { MouseEvent, ReactNode } from "react";

import { cn } from "@/lib/utils";
import { THOUGHT_PARAM, openThought } from "@/lib/thought-link";

/**
 * A link that opens a thought in the side sheet over the chat. It is a real
 * link, so it can be copied or opened in a new tab.
 */
export function ThoughtLink({
  id,
  className,
  children,
}: {
  id: string;
  className?: string;
  children: ReactNode;
}) {
  function open(event: MouseEvent<HTMLAnchorElement>) {
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) return;
    event.preventDefault();
    openThought(id);
  }

  return (
    <a
      href={`?${THOUGHT_PARAM}=${encodeURIComponent(id)}`}
      onClick={open}
      className={cn("text-primary underline-offset-4 hover:underline", className)}
    >
      {children}
    </a>
  );
}
