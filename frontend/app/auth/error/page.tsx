import { Button } from "@/components/ui/button";

export default function LoginFailedPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-8 text-center">
      <h1 className="text-2xl font-semibold tracking-tight">The login did not complete</h1>
      <p className="max-w-md text-muted-foreground">
        The login was cancelled, took too long, or could not be checked. You are not logged in.
      </p>
      {/* /auth/login is a route handler, so it needs a full navigation. */}
      <Button nativeButton={false} render={<a href="/auth/login" />}>
        Try again
      </Button>
    </main>
  );
}
