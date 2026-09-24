// The email allow-list, as the backend applies it. The backend enforces it on
// every call; the login routes check it too so a refused user sees a clear page.

/** True when the provider says the address is verified and it is on the list, or when there is no list. */
export function isAllowed(
  email: unknown,
  emailVerified: unknown,
  allowed: string[] | null,
): boolean {
  if (allowed === null) return true;
  if (typeof email !== "string" || !email || emailVerified !== true) return false;
  const address = email.trim().toLowerCase();
  const at = address.lastIndexOf("@");
  if (allowed.includes(address)) return true;
  return at > 0 && allowed.includes(address.slice(at));
}
