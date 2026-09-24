import { redirect } from "next/navigation";

import { FirebaseLogin } from "@/components/firebase-login";
import { getAuthConfig } from "@/lib/auth-mode";
import { safeReturnTo } from "@/lib/login";

// The Firebase login page. The project's public web config is read on the
// server at run time and handed to the page, so one build serves every mode.
export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ returnTo?: string }>;
}) {
  const { returnTo } = await searchParams;
  const safe = safeReturnTo(returnTo);
  const config = getAuthConfig();
  if (config.mode !== "firebase") {
    redirect(`/auth/login?returnTo=${encodeURIComponent(safe)}`);
  }
  const { apiKey, authDomain, projectId } = config.firebase!;
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-6 p-8">
      <h1 className="text-3xl font-semibold tracking-tight">Log in to Focus Funnel</h1>
      <FirebaseLogin firebaseConfig={{ apiKey, authDomain, projectId }} returnTo={safe} />
    </main>
  );
}
