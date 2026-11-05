import Link from "next/link";

import { DemoBar } from "@/components/demo/demo-bar";
import { DemoProvider } from "@/components/demo/demo-context";
import { SetupWizard } from "@/components/setup/setup-wizard";
import { Button } from "@/components/ui/button";
import { demoSettings } from "@/lib/demo-settings";

// The first-run setup wizard. Nothing in the app links here: the backend
// prints this address with the setup token when it starts while setup is open.
// A logged-out visitor is sent to log in by proxy.ts and comes back here.
export default async function SetupPage() {
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
          <h1 className="text-2xl font-semibold tracking-tight">Set up Focus Funnel</h1>
          <SetupWizard />
        </main>
      </div>
    </DemoProvider>
  );
}
