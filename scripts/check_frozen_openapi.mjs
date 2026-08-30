import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";

const defaultRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const rootArgument = process.argv.indexOf("--root");
const root = resolve(
  rootArgument === -1
    ? defaultRoot
    : process.argv[rootArgument + 1] || defaultRoot,
);
const target = resolve(root, "contracts/openapi-v0.1.yaml");
const manifest = resolve(root, "contracts/openapi-v0.1.sha256");

if (process.argv.includes("--write")) {
  throw new Error(
    "--write is unavailable: the repository contract and its SHA-256 manifest are the sole authority",
  );
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

console.log(
  `frozen OpenAPI SHA-256 check passed (${targetBytes.byteLength} bytes)`,
);
