import Link from "next/link";

import { DemoBar } from "@/components/demo/demo-bar";
import { DemoProvider } from "@/components/demo/demo-context";
import { ModelSettingsSection } from "@/components/model-settings";
import { ProvidersSettings } from "@/components/providers-settings";
import { UsageSection } from "@/components/usage-settings";
import { Button } from "@/components/ui/button";
import { demoSettings } from "@/lib/demo-settings";

export default async function SettingsPage() {
  const demo = await demoSettings();
  return (
    <DemoProvider settings={demo}>
      <div className="flex min-h-screen flex-col">
        <header className="flex items-center justify-between border-b px-6 py-3">
          <Link href="/app" className="font-semibold">
            Focus Funnel
          </Link>
          {demo ? (
            <DemoBar />
          ) : (
            <Button variant="outline" nativeButton={false} render={<a href="/auth/logout" />}>
              Log out
            </Button>
          )}
        </header>
        <main className="mx-auto flex w-full max-w-xl flex-col gap-6 p-6">
          <h1 className="text-2xl font-semibold tracking-tight">Settings</h1>
          <ProvidersSettings />
          <ModelSettingsSection />
          <UsageSection />
        </main>
      </div>
    </DemoProvider>
  );
}
