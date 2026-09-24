"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { UnauthenticatedError } from "@/lib/api";
import { listConversations, type ConversationList } from "@/lib/conversations";
import { redirectToLogin } from "@/lib/redirect-to-login";

type ConversationsState = {
  /** Null until the first load finishes. */
  lists: ConversationList | null;
  loadError: string | null;
  refresh: () => Promise<void>;
  /** Changes each time the user asks for a new conversation, to reset the chat. */
  newChatKey: number;
  startNewChat: () => void;
};

const ConversationsContext = createContext<ConversationsState | null>(null);

/** Holds the sidebar's lists, so the chat can refresh them after a message. */
export function ConversationsProvider({ children }: { children: ReactNode }) {
  const [lists, setLists] = useState<ConversationList | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [newChatKey, setNewChatKey] = useState(0);
  const startNewChat = useCallback(() => setNewChatKey((key) => key + 1), []);

  const refresh = useCallback(
    () =>
      listConversations().then(
        (loaded) => {
          setLists(loaded);
          setLoadError(null);
        },
        (error: unknown) => {
          if (error instanceof UnauthenticatedError) {
            redirectToLogin("/app");
            return;
          }
          setLoadError(error instanceof Error ? error.message : "Could not load conversations.");
        },
      ),
    [],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return (
    <ConversationsContext.Provider value={{ lists, loadError, refresh, newChatKey, startNewChat }}>
      {children}
    </ConversationsContext.Provider>
  );
}

/** The sidebar's lists. Outside a provider (a component test), a no-op stand-in. */
export function useConversations(): ConversationsState {
  return (
    useContext(ConversationsContext) ?? {
      lists: null,
      loadError: null,
      refresh: async () => undefined,
      newChatKey: 0,
      startNewChat: () => undefined,
    }
  );
}
