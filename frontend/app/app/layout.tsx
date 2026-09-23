import Link from "next/link";
import type { ReactNode } from "react";

import { ConversationsProvider } from "@/components/chat/conversations-context";
import { Sidebar } from "@/components/chat/sidebar";
import { Button } from "@/components/ui/button";

export default function AppLayout({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-screen flex-col">
      <header className="flex items-center justify-between border-b px-6 py-3">
        <span className="font-semibold">Focus Funnel</span>
        <nav className="flex items-center gap-2">
          <Button variant="ghost" nativeButton={false} render={<Link href="/settings" />}>
            Settings
          </Button>
          <Button variant="outline" nativeButton={false} render={<a href="/auth/logout" />}>
            Log out
          </Button>
        </nav>
      </header>
      <ConversationsProvider>
        <div className="flex min-h-0 flex-1">
          <Sidebar />
          <main className="flex min-h-0 flex-1 flex-col">{children}</main>
        </div>
      </ConversationsProvider>
    </div>
  );
}
