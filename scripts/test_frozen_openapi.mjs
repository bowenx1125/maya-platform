import {
  copyFileSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const tempRoot = mkdtempSync(resolve(tmpdir(), "maya-openapi-clean-checkout-"));
const checker = resolve(root, "scripts/check_frozen_openapi.mjs");
const run = () =>
  spawnSync(process.execPath, [checker, "--root", tempRoot], {
    cwd: root,
    encoding: "utf8",
  });

try {
  mkdirSync(resolve(tempRoot, "contracts"), { recursive: true });
  copyFileSync(
    resolve(root, "contracts/openapi-v0.1.yaml"),
    resolve(tempRoot, "contracts/openapi-v0.1.yaml"),
  );
  copyFileSync(
    resolve(root, "contracts/openapi-v0.1.sha256"),
    resolve(tempRoot, "contracts/openapi-v0.1.sha256"),
  );
  const clean = run();
  if (clean.status !== 0)
    throw new Error(
      `clean-checkout hash verification failed: ${clean.stderr || clean.stdout}`,
    );
  const mutated = Buffer.from(
    readFileSync(resolve(tempRoot, "contracts/openapi-v0.1.yaml")),
  );
  mutated[mutated.length - 1] = mutated[mutated.length - 1] === 10 ? 32 : 10;
  writeFileSync(resolve(tempRoot, "contracts/openapi-v0.1.yaml"), mutated);
  const drift = run();
  if (drift.status === 0)
    throw new Error(
      "clean-checkout hash verification accepted a mutated OpenAPI copy",
    );
  console.log(
    "frozen OpenAPI standalone check passed: clean checkout works without parent and drift is rejected",
  );
} finally {
  rmSync(tempRoot, { recursive: true, force: true });
}
