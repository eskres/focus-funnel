import Link from "next/link";

import { ApiKeySettings } from "@/components/api-key-settings";
import { Button } from "@/components/ui/button";

export default function SettingsPage() {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="flex items-center justify-between border-b px-6 py-3">
        <Link href="/app" className="font-semibold">
          Focus Funnel
        </Link>
        <Button variant="outline" nativeButton={false} render={<a href="/auth/logout" />}>
          Log out
        </Button>
      </header>
      <main className="mx-auto flex w-full max-w-xl flex-col gap-6 p-6">
        <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
        <ApiKeySettings />
      </main>
    </div>
  );
}
