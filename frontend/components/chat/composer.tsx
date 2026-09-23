"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";

export function Composer({
  disabled,
  onSend,
  children,
}: {
  /** True while an answer is arriving. */
  disabled: boolean;
  onSend: (text: string) => void;
  /** Shown under the input, for example the model picker. */
  children?: ReactNode;
}) {
  const [text, setText] = useState("");
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // A disabled textarea loses focus, so hand it back when the answer ends.
  useEffect(() => {
    if (!disabled) textareaRef.current?.focus();
  }, [disabled]);

  function submit() {
    if (disabled || text.trim() === "") return;
    onSend(text);
    setText("");
  }

  return (
    <form
      className="flex flex-col gap-2"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <div className="flex items-end gap-2">
        <Textarea
          ref={textareaRef}
          aria-label="Message"
          placeholder="Write a message, or start with a command"
          rows={1}
          className="max-h-48 min-h-9 flex-1 resize-none"
          value={text}
          disabled={disabled}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => {
            // Enter sends. Shift+Enter adds a line. Enter while composing text
            // with an input method picks a character and must not send.
            if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {
              event.preventDefault();
              submit();
            }
          }}
        />
        <Button type="submit" disabled={disabled}>
          Send
        </Button>
      </div>
      {children}
    </form>
  );
}
