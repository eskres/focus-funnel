import { Button } from "@/components/ui/button";

export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-8 text-center">
      <h1 className="text-3xl font-semibold tracking-tight">Focus Funnel</h1>
      <p className="max-w-md text-muted-foreground">
        Dump your thoughts, file them away, and find them again when you need
        them.
      </p>
      <Button size="lg" nativeButton={false} render={<a href="/auth/login" />}>
        Log in
      </Button>
    </main>
  );
}
