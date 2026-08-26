import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const checker = resolve(root, "scripts/check_repo_boundary.mjs");
const result = spawnSync(process.execPath, [checker, "--probe-generated"], {
  cwd: root,
  encoding: "utf8",
  env: { ...process.env, CI: "true" },
});

if (result.status !== 0) {
  throw new Error(
    result.stderr || result.stdout || "repository boundary probe failed",
  );
}

console.log(
  "repository boundary probe passed: generated API source is included in the secret scan",
);
