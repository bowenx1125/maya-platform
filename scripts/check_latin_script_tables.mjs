import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const generator = resolve(root, "scripts/generate_latin_script_tables.mjs");
const trackedPython = resolve(
  root,
  "backend/app/modules/debates/generated/latin_script_ranges.py",
);
const trackedTypeScript = resolve(
  root,
  "frontend/lib/generated/latin-script-ranges.ts",
);
const temporaryRoot = mkdtempSync(resolve(tmpdir(), "maya-latin-tables-"));
const generatedPython = resolve(temporaryRoot, "latin_script_ranges.py");
const generatedTypeScript = resolve(temporaryRoot, "latin-script-ranges.ts");

try {
  const result = spawnSync(
    process.execPath,
    [
      generator,
      "--python-output",
      generatedPython,
      "--typescript-output",
      generatedTypeScript,
    ],
    { cwd: root, encoding: "utf8" },
  );
  if (result.status !== 0) {
    process.stderr.write(
      result.stderr ||
        result.stdout ||
        "Latin script table generation failed\n",
    );
    process.exit(result.status ?? 1);
  }

  if (!readFileSync(generatedPython).equals(readFileSync(trackedPython))) {
    throw new Error(
      "generated Python Latin script table differs from the tracked output",
    );
  }
  if (
    !readFileSync(generatedTypeScript).equals(readFileSync(trackedTypeScript))
  ) {
    throw new Error(
      "generated TypeScript Latin script table differs from the tracked output",
    );
  }
  console.log("Latin script tables are deterministic and clean-diff verified");
} finally {
  rmSync(temporaryRoot, { recursive: true, force: true });
}
