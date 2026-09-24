// Node.js runtime only: stop the server when the auth settings are wrong.
import { AuthConfigError, readAuthConfig } from "@/lib/auth-mode";

try {
  readAuthConfig(process.env);
} catch (error) {
  if (!(error instanceof AuthConfigError)) throw error;
  console.error(`Focus Funnel cannot start: ${error.message}`);
  process.exit(1);
}
