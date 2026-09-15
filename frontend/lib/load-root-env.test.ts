import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { loadRootEnv } from "./load-root-env";

const KEYS = ["LOAD_ROOT_ENV_TEST_NEW", "LOAD_ROOT_ENV_TEST_EXISTING"];

let repoDir: string;
let frontendDir: string;

beforeEach(() => {
  repoDir = mkdtempSync(path.join(tmpdir(), "load-root-env-"));
  frontendDir = path.join(repoDir, "frontend");
  mkdirSync(frontendDir);
});

afterEach(() => {
  rmSync(repoDir, { recursive: true, force: true });
  for (const key of KEYS) {
    delete process.env[key];
  }
});

describe("loadRootEnv", () => {
  it("loads variables from the .env one folder above the frontend", () => {
    writeFileSync(path.join(repoDir, ".env"), "LOAD_ROOT_ENV_TEST_NEW=from-root\n");

    expect(loadRootEnv(frontendDir)).toBe(path.join(repoDir, ".env"));
    expect(process.env.LOAD_ROOT_ENV_TEST_NEW).toBe("from-root");
  });

  it("keeps variables that are already set", () => {
    process.env.LOAD_ROOT_ENV_TEST_EXISTING = "from-environment";
    writeFileSync(path.join(repoDir, ".env"), "LOAD_ROOT_ENV_TEST_EXISTING=from-root\n");

    loadRootEnv(frontendDir);

    expect(process.env.LOAD_ROOT_ENV_TEST_EXISTING).toBe("from-environment");
  });

  it("does nothing when there is no root .env", () => {
    expect(loadRootEnv(frontendDir)).toBeNull();
    expect(process.env.LOAD_ROOT_ENV_TEST_NEW).toBeUndefined();
  });
});
