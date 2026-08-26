import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const checker = resolve(root, "scripts/check_openapi_responses.mjs");
const allowlist = resolve(root, "contracts/response-contract-allowlist.json");
const tempDir = mkdtempSync(resolve(tmpdir(), "maya-response-check-"));

function run(path) {
  return spawnSync(process.execPath, [checker, "--allowlist", path], {
    cwd: root,
    encoding: "utf8",
    env: { ...process.env, CI: "true" },
  });
}

try {
  const positive = run(allowlist);
  if (positive.status !== 0)
    throw new Error(
      positive.stderr ||
        positive.stdout ||
        "response contract rejected its frozen allow-list",
    );

  const invalid = JSON.parse(readFileSync(allowlist, "utf8"));
  invalid.allow_missing_2xx.connectDebateEvents.required_status = "200";
  const invalidPath = resolve(tempDir, "invalid-allowlist.json");
  writeFileSync(invalidPath, `${JSON.stringify(invalid, null, 2)}\n`, "utf8");
  const negative = run(invalidPath);
  if (negative.status === 0)
    throw new Error("invalid 2xx exception unexpectedly passed");

  console.log(
    "response contract checker: frozen allow-list passed and invalid 2xx exception was rejected",
  );
} finally {
  rmSync(tempDir, { recursive: true, force: true });
}
