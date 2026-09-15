import type { NextConfig } from "next";

import { loadRootEnv } from "./lib/load-root-env";

// The only env file is the repo-root .env; load it for local `next dev`,
// `next build`, and `next start`. Existing variables (compose env_file) win.
loadRootEnv(__dirname);

const nextConfig: NextConfig = {
  output: "standalone",
  reactCompiler: true,
};

export default nextConfig;
