import { Button } from "@/components/ui/button";

export default function NotAllowedPage() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-8 text-center">
      <h1 className="text-2xl font-semibold tracking-tight">This account is not accepted here</h1>
      <p className="max-w-md text-muted-foreground">
        This instance only accepts some accounts, and yours is not one of them. Only a verified
        email address on its list can get in. Ask the person who runs it to add your address, or
        log in with another account.
      </p>
      <Button variant="outline" nativeButton={false} render={<a href="/auth/logout" />}>
        Back to the start
      </Button>
    </main>
  );
}
