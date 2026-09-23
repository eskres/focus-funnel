export function redirectToLogin(returnTo = "/settings") {
  // /auth/login is an Auth0 SDK route served by proxy.ts, not a Next.js page,
  // so it needs a full browser navigation rather than a client-side route change.
  const url = new URL("/auth/login", window.location.origin);
  url.searchParams.set("returnTo", returnTo);
  window.location.assign(url);
}
