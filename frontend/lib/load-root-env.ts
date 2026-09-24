import { existsSync } from "node:fs";
import path from "node:path";

/**
 * Loads the repo-root `.env` (one level above `frontendDir`) into `process.env`.
 *
 * `next dev` only reads env files from the Next.js project folder, but this
 * repo keeps its single `.env` at the root (docker-compose passes it to the
 * containers). Without this, a local `npm run dev` has no AUTH_MODE or other
 * login settings and refuses to start.
 *
 * Variables that are already set win, so compose's `env_file` values, shell
 * exports, and `frontend/.env*` files are never overridden. `@next/env`'s
 * `loadEnvConfig` is not used because it caches its first result and would
 * silently skip a second folder.
 *
 * Returns the loaded file path, or null when there is no root `.env` (for
 * example inside the Docker build, where only `frontend/` is copied).
 */
export function loadRootEnv(frontendDir: string): string | null {
  const envPath = path.resolve(frontendDir, "..", ".env");
  if (!existsSync(envPath)) {
    return null;
  }
  process.loadEnvFile(envPath);
  return envPath;
}
