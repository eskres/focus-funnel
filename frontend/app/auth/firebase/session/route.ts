import { isAllowed } from "@/lib/allow-list";
import { getAuthConfig } from "@/lib/auth-mode";
import { FirebaseTokenError, verifyFirebaseIdToken } from "@/lib/firebase-server";
import { baseUrl, safeReturnTo } from "@/lib/login";
import { sessionCookies } from "@/lib/session";

function errorResponse(status: number, code: string, message: string) {
  return Response.json({ error: { code, message } }, { status });
}

// Takes the tokens from the Firebase sign-in on the login page, checks the ID
// token against Google's keys for this project, and starts the session. The
// browser signs out of Firebase right after, so only this server keeps them.
export async function POST(request: Request): Promise<Response> {
  const config = getAuthConfig();
  if (config.mode !== "firebase") return errorResponse(404, "not_found", "Not found.");

  // Only the app's own login page may start a session (no login CSRF).
  const origin = request.headers.get("origin");
  if (origin !== new URL(baseUrl(config, request)).origin) {
    return errorResponse(403, "validation_error", "Sign in from this site's login page.");
  }

  const body = (await request.json().catch(() => null)) as {
    idToken?: unknown;
    refreshToken?: unknown;
    returnTo?: unknown;
  } | null;
  if (typeof body?.idToken !== "string" || typeof body.refreshToken !== "string") {
    return errorResponse(422, "validation_error", "idToken and refreshToken are required.");
  }

  let claims;
  try {
    claims = await verifyFirebaseIdToken(body.idToken, config.firebase!);
  } catch (error) {
    if (!(error instanceof FirebaseTokenError)) throw error;
    console.warn("Firebase login: the token was refused", { reason: error.message });
    return errorResponse(401, "unauthenticated", "The login did not complete. Try again.");
  }

  if (!isAllowed(claims.email, claims.email_verified, config.allowedEmails)) {
    return errorResponse(
      403,
      "not_allowed",
      "This instance does not accept your account. Only a verified email address on its list can get in.",
    );
  }

  const cookies = await sessionCookies(
    request,
    {
      mode: "firebase",
      idToken: body.idToken,
      refreshToken: body.refreshToken,
      expiresAt: claims.exp,
    },
    config.sessionSecret,
  );
  const headers = new Headers({ "Cache-Control": "no-store" });
  for (const cookie of cookies) headers.append("set-cookie", cookie);
  return Response.json(
    { redirect: safeReturnTo(typeof body.returnTo === "string" ? body.returnTo : null) },
    { headers },
  );
}
