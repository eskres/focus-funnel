"use client";

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";

import { Button } from "@/components/ui/button";
import { DEMO_EXPIRED_EVENT, DemoSessionExpiredError } from "@/lib/api";
import { acceptDemoNotice, getMe } from "@/lib/demo";

export interface DemoState {
  /** When the session and its data are deleted. */
  expiresAt: string | null;
  noticeAccepted: boolean;
  acceptNotice: () => Promise<void>;
  keyTtlMinutes: number;
  keyMaxHours: number;
}

const DemoContext = createContext<DemoState | null>(null);

/** The demo session, or null outside demo mode. */
export function useDemo(): DemoState | null {
  return useContext(DemoContext);
}

export interface DemoSettings {
  keyTtlMinutes: number;
  keyMaxHours: number;
}

/**
 * Wraps the app in demo mode: loads the session's expiry and notice state,
 * and replaces the page with the expired screen once any call finds that the
 * session has ended. Outside demo mode (settings null) it renders children.
 */
export function DemoProvider({
  settings,
  children,
}: {
  settings: DemoSettings | null;
  children: ReactNode;
}) {
  if (!settings) return <>{children}</>;
  return <DemoSession settings={settings}>{children}</DemoSession>;
}

function DemoSession({ settings, children }: { settings: DemoSettings; children: ReactNode }) {
  const [expiresAt, setExpiresAt] = useState<string | null>(null);
  const [noticeAccepted, setNoticeAccepted] = useState(false);
  const [expired, setExpired] = useState(false);

  useEffect(() => {
    const onExpired = () => setExpired(true);
    window.addEventListener(DEMO_EXPIRED_EVENT, onExpired);
    let cancelled = false;
    getMe()
      .then((me) => {
        if (cancelled) return;
        setExpiresAt(me.expires_at ?? null);
        setNoticeAccepted(Boolean(me.demo_notice_accepted));
      })
      .catch((error: unknown) => {
        if (!cancelled && error instanceof DemoSessionExpiredError) setExpired(true);
      });
    return () => {
      cancelled = true;
      window.removeEventListener(DEMO_EXPIRED_EVENT, onExpired);
    };
  }, []);

  const acceptNotice = useCallback(async () => {
    await acceptDemoNotice();
    setNoticeAccepted(true);
  }, []);

  if (expired) return <DemoEnded reason="expired" />;
  return (
    <DemoContext.Provider value={{ expiresAt, noticeAccepted, acceptNotice, ...settings }}>
      {children}
    </DemoContext.Provider>
  );
}

/** The screen after a demo session ends, with a way to start a new one. */
export function DemoEnded({ reason }: { reason: "expired" | "ended" }) {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-8 text-center">
      <h1 className="text-2xl font-semibold tracking-tight">
        {reason === "expired" ? "Your demo session has ended" : "You ended your demo"}
      </h1>
      <p className="max-w-md text-muted-foreground">
        Its conversations, settings, and usage were deleted, and any API key this browser held is
        forgotten.
      </p>
      {/* A full page load: the proxy starts a new session for a visitor without one. */}
      <Button onClick={() => window.location.assign(new URL("/app", window.location.origin))}>
        Start again
      </Button>
    </main>
  );
}
