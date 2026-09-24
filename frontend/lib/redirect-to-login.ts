export function redirectToLogin(returnTo = "/settings") {
  // /auth/login is a route handler, not a page, so it needs a full browser
  // navigation rather than a client-side route change. It sends the user to
  // the login of the server's auth mode.
  const url = new URL("/auth/login", window.location.origin);
  url.searchParams.set("returnTo", returnTo);
  window.location.assign(url);
}
