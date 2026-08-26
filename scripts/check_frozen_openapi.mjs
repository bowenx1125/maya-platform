import { createHash } from "node:crypto";
import { copyFileSync, existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const defaultRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const rootArgument = process.argv.indexOf("--root");
const root = resolve(
  rootArgument === -1
    ? defaultRoot
    : process.argv[rootArgument + 1] || defaultRoot,
);
const source = resolve(root, "../docs/pre-code-contracts/openapi-v0.1.yaml");
const target = resolve(root, "contracts/openapi-v0.1.yaml");
const manifest = resolve(root, "contracts/openapi-v0.1.sha256");

if (process.argv.includes("--write")) {
  if (!existsSync(source)) {
    throw new Error(
      "--write requires the frozen parent OpenAPI source to exist locally",
    );
  }
  copyFileSync(source, target);
}

const targetBytes = readFileSync(target);
const expectedManifest = readFileSync(manifest, "utf8").trim().split(/\s+/)[0];
if (!/^[a-f0-9]{64}$/.test(expectedManifest)) {
  throw new Error(
    "contracts/openapi-v0.1.sha256 must contain one lowercase SHA-256 digest",
  );
}
const actualDigest = createHash("sha256").update(targetBytes).digest("hex");
if (actualDigest !== expectedManifest) {
  throw new Error(
    "contracts/openapi-v0.1.yaml does not match its in-repo SHA-256 manifest",
  );
}

if (existsSync(source)) {
  const sourceBytes = readFileSync(source);
  if (!sourceBytes.equals(targetBytes)) {
    throw new Error(
      "contracts/openapi-v0.1.yaml drifted from the frozen parent source; copy the parent byte-for-byte and rerun the check",
    );
  }
  console.log("local frozen parent byte comparison passed");
} else {
  console.log(
    "local frozen parent not present; in-repo SHA-256 manifest is authoritative",
  );
}

console.log(
  `frozen OpenAPI SHA-256 check passed (${targetBytes.byteLength} bytes)`,
);
