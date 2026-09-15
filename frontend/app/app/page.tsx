import Link from "next/link";

import { Button } from "@/components/ui/button";

export default function AppPage() {
  return (
    <div className="flex min-h-screen flex-col">
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
      <main className="flex flex-1 items-center justify-center p-8">
        <p className="text-muted-foreground">Chat is coming soon.</p>
      </main>
    </div>
  );
}
