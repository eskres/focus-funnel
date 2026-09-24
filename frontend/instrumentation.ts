// Checks the auth settings once when the server starts, so a wrong setting
// stops the server with a message naming it instead of failing every request.
export async function register() {
  // `next build` has no runtime settings; the running server is what counts.
  if (process.env.NEXT_PHASE === "phase-production-build") return;
  if (process.env.NEXT_RUNTIME === "nodejs") await import("./instrumentation-node");
}
