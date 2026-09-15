import { Auth0Client } from "@auth0/nextjs-auth0/server";

// Domain, client id and secret, session secret, and app base URL come from the
// AUTH0_* and APP_BASE_URL environment variables (see .env.example).
export const auth0 = new Auth0Client({
  authorizationParameters: {
    // Request an access token for the FastAPI API so the backend can verify it.
    audience: process.env.AUTH0_AUDIENCE,
  },
  // The access token stays on the server: the browser never needs it, so the
  // SDK's /auth/access-token route (which returns it as JSON) is turned off.
  enableAccessTokenEndpoint: false,
  // Logins that don't name a destination (such as the landing page button)
  // return to the app instead of the public landing page.
  signInReturnToPath: "/app",
});
