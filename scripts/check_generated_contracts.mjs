import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const source = resolve(root, "contracts/openapi-v0.1.yaml");
const generated = resolve(root, "frontend/lib/api/generated/schema.d.ts");
const client = resolve(root, "frontend/lib/api/generated/client.ts");
const cli = resolve(root, "node_modules/.bin/openapi-typescript");
const tempDir = mkdtempSync(resolve(tmpdir(), "maya-openapi-types-"));
const expected = resolve(tempDir, "schema.d.ts");

try {
  const result = spawnSync(cli, [source, "-o", expected], {
    cwd: root,
    encoding: "utf8",
  });
  if (result.status !== 0) {
    process.stderr.write(
      result.stderr || result.stdout || "openapi-typescript failed\n",
    );
    process.exit(result.status ?? 1);
  }

  const expectedBytes = readFileSync(expected);
  const actualBytes = readFileSync(generated);
  if (!expectedBytes.equals(actualBytes)) {
    throw new Error(
      "generated schema.d.ts differs from openapi-typescript 7.13.0 output",
    );
  }

  const clientSource = readFileSync(client, "utf8");
  for (const requiredText of [
    "openapi-fetch",
    "createPlatformClient",
    "X-CSRF-Token",
    'credentials: "include"',
  ]) {
    if (!clientSource.includes(requiredText)) {
      throw new Error(
        `platform client wrapper is missing required contract behavior: ${requiredText}`,
      );
    }
  }
  console.log(
    "generated OpenAPI types are clean and the platform client wrapper is present",
  );
} finally {
  rmSync(tempDir, { recursive: true, force: true });
}
