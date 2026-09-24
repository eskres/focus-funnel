"use client";

import { Chat } from "@/components/chat/chat";
import { useConversations } from "@/components/chat/conversations-context";

/**
 * A new, empty chat. A chat that starts a conversation moves the address to
 * /app/<id> without leaving this page, so going back to /app would keep it:
 * the key makes each new conversation a fresh chat.
 */
export function NewChat() {
  const { newChatKey } = useConversations();
  return <Chat key={`new-${newChatKey}`} />;
}
