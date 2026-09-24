"use client";

import { deleteApp, initializeApp, type FirebaseOptions } from "firebase/app";
import {
  GoogleAuthProvider,
  browserPopupRedirectResolver,
  inMemoryPersistence,
  initializeAuth,
  signInWithEmailAndPassword,
  signInWithPopup,
  signOut,
  type Auth,
  type UserCredential,
} from "firebase/auth";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const SESSION_ENDPOINT = "/auth/firebase/session";
const FAILED = "The login did not complete. Try again.";

/**
 * Signs in with Firebase in memory only, hands the tokens to the server, and
 * signs out at once, so no Firebase token stays in the browser.
 */
export function FirebaseLogin({
  firebaseConfig,
  returnTo,
}: {
  firebaseConfig: Pick<FirebaseOptions, "apiKey" | "authDomain" | "projectId">;
  returnTo: string;
}) {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(signIn: (auth: Auth) => Promise<UserCredential>) {
    setBusy(true);
    setError(null);
    // A fresh app per attempt, with in-memory persistence: nothing is
    // written to local storage, session storage, or IndexedDB.
    const app = initializeApp(firebaseConfig, `login-${Date.now()}`);
    const auth = initializeAuth(app, {
      persistence: inMemoryPersistence,
      popupRedirectResolver: browserPopupRedirectResolver,
    });
    let destination: string | null = null;
    try {
      const { user } = await signIn(auth);
      const response = await fetch(SESSION_ENDPOINT, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          idToken: await user.getIdToken(),
          refreshToken: user.refreshToken,
          returnTo,
        }),
      });
      if (response.ok) {
        destination = ((await response.json()) as { redirect: string }).redirect;
      } else if (response.status === 403) {
        destination = "/auth/not-allowed";
      } else {
        setError(FAILED);
      }
    } catch {
      setError(FAILED);
    } finally {
      await signOut(auth).catch(() => undefined);
      await deleteApp(app).catch(() => undefined);
      setBusy(false);
    }
    if (destination) router.replace(destination);
  }

  function signInWithEmail(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void run((auth) => signInWithEmailAndPassword(auth, email.trim(), password));
  }

  return (
    <div className="flex w-full max-w-sm flex-col gap-4">
      <Button
        type="button"
        disabled={busy}
        onClick={() => void run((auth) => signInWithPopup(auth, new GoogleAuthProvider()))}
      >
        Continue with Google
      </Button>
      <p className="text-center text-sm text-muted-foreground">or</p>
      <form className="flex flex-col gap-2" onSubmit={signInWithEmail}>
        <Input
          type="email"
          aria-label="Email"
          placeholder="Email"
          autoComplete="email"
          required
          value={email}
          onChange={(event) => setEmail(event.target.value)}
          disabled={busy}
        />
        <Input
          type="password"
          aria-label="Password"
          placeholder="Password"
          autoComplete="current-password"
          required
          value={password}
          onChange={(event) => setPassword(event.target.value)}
          disabled={busy}
        />
        <Button type="submit" variant="outline" disabled={busy}>
          {busy ? "Logging in…" : "Log in with email"}
        </Button>
      </form>
      {error && (
        <Alert variant="destructive">
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      )}
    </div>
  );
}
