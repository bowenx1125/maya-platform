// Every place that names a Node version names the one in .nvmrc (PR D).
//
// Node 24.14.0 is pinned exactly: the Latin-script tables are generated from
// its Unicode data and Prettier output must match CI byte for byte.
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const read = (path) => readFileSync(resolve(root, path), "utf8");
const pin = read(".nvmrc").trim();
const failures = [];

if (!/^\d+\.\d+\.\d+$/.test(pin)) {
  failures.push(`.nvmrc must hold one exact version, found "${pin}"`);
}
if (process.version !== `v${pin}`) {
  failures.push(`running Node ${process.version}, pinned v${pin} (.nvmrc)`);
}
for (const path of ["package.json", "frontend/package.json"]) {
  const engine = JSON.parse(read(path)).engines?.node;
  if (engine !== pin) {
    failures.push(`${path} engines.node is "${engine}", expected "${pin}"`);
  }
}
if (!/^\s*engineStrict:\s*true\s*$/m.test(read("pnpm-workspace.yaml"))) {
  failures.push("pnpm-workspace.yaml must set engineStrict: true");
}
const dockerFrom = read("frontend/Dockerfile").match(/^FROM node:([^\s@-]+)/m);
if (dockerFrom?.[1] !== pin) {
  failures.push(
    `frontend/Dockerfile uses node:${dockerFrom?.[1]}, expected node:${pin}`,
  );
}
if (
  !read(".github/workflows/wave0.yml").includes("node-version-file: .nvmrc")
) {
  failures.push(".github/workflows/wave0.yml must set up Node from .nvmrc");
}
if (
  !read("scripts/generate_latin_script_tables.mjs").includes(`Node v${pin}`)
) {
  failures.push(
    `scripts/generate_latin_script_tables.mjs must require Node v${pin}`,
  );
}

if (failures.length > 0) {
  throw new Error(`Node pin drift:\n- ${failures.join("\n- ")}`);
}
console.log(`Node pin check passed: v${pin} everywhere`);
