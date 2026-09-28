import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const tempDir = mkdtempSync(resolve(tmpdir(), "maya-ws-generated-"));
const tempSchema = resolve(tempDir, "ws-events.v1.schema.json");
const tempCommands = resolve(tempDir, "ws-commands.v1.schema.json");
const tempCommandResults = resolve(
  tempDir,
  "ws-command-results.v1.schema.json",
);
const tempFixtures = resolve(tempDir, "fixtures");
const sameText = (left, right) =>
  readFileSync(left, "utf8").replace(/\r\n/g, "\n") ===
  readFileSync(right, "utf8").replace(/\r\n/g, "\n");
const run = (script, args) => {
  const result = spawnSync(process.execPath, [resolve(root, script), ...args], {
    cwd: root,
    encoding: "utf8",
  });
  if (result.status !== 0)
    throw new Error(result.stderr || result.stdout || `${script} failed`);
};

try {
  run("scripts/generate_ws_schema.mjs", ["--output", tempSchema]);
  run("scripts/generate_ws_command_schemas.mjs", [
    "--commands-output",
    tempCommands,
    "--results-output",
    tempCommandResults,
  ]);
  run("scripts/generate_ws_fixtures.mjs", ["--output-dir", tempFixtures]);
  if (
    !sameText(tempSchema, resolve(root, "contracts/ws-events.v1.schema.json"))
  )
    throw new Error("generated WebSocket schema differs from tracked output");
  if (
    !sameText(
      tempCommands,
      resolve(root, "contracts/ws-commands.v1.schema.json"),
    ) ||
    !sameText(
      tempCommandResults,
      resolve(root, "contracts/ws-command-results.v1.schema.json"),
    )
  )
    throw new Error(
      "generated WebSocket command schemas differ from tracked output",
    );
  for (const name of ["ws-events.valid.json", "ws-events.invalid.json"]) {
    if (
      !sameText(
        resolve(tempFixtures, name),
        resolve(root, "contracts/fixtures", name),
      )
    )
      throw new Error(
        `generated WebSocket fixture differs from tracked output: ${name}`,
      );
  }
  run("scripts/test_ws_events.mjs", [
    "--schema",
    tempSchema,
    "--fixtures-dir",
    tempFixtures,
  ]);
  run("scripts/test_ws_commands.mjs", []);
  console.log(
    "WebSocket generators are deterministic; schema and fixtures clean-diff check passed",
  );
} finally {
  rmSync(tempDir, { recursive: true, force: true });
}
