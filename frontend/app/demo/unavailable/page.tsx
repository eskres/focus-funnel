import Link from "next/link";

import { Button } from "@/components/ui/button";

const messages: Record<string, { title: string; body: string }> = {
  full: {
    title: "The demo is full",
    body: "Too many people are trying the demo right now. Try again later.",
  },
  limit: {
    title: "Too many new sessions",
    body: "This address has started too many demo sessions. Try again later.",
  },
  error: {
    title: "The demo could not start",
    body: "Something went wrong while starting your demo session. Try again.",
  },
};

export default async function DemoUnavailablePage({
  searchParams,
}: {
  searchParams: Promise<{ reason?: string }>;
}) {
  const { reason } = await searchParams;
  const message = messages[reason ?? ""] ?? messages.error;
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-8 text-center">
      <h1 className="text-2xl font-semibold tracking-tight">{message.title}</h1>
      <p className="max-w-md text-muted-foreground">{message.body}</p>
      <Button nativeButton={false} render={<Link href="/app" />}>
        Try again
      </Button>
    </main>
  );
}
