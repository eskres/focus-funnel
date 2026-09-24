// Checks the auth settings once when the server starts, so a wrong setting
// stops the server with a message naming it instead of failing every request.
export async function register() {
  if (process.env.NEXT_RUNTIME !== "nodejs") return;
  // `next build` has no runtime settings; the running server is what counts.
  if (process.env.NEXT_PHASE === "phase-production-build") return;
  const { AuthConfigError, readAuthConfig } = await import("@/lib/auth-mode");
  try {
    readAuthConfig(process.env);
  } catch (error) {
    if (!(error instanceof AuthConfigError)) throw error;
    console.error(`Focus Funnel cannot start: ${error.message}`);
    process.exit(1);
  }
}
