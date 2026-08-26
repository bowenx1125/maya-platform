import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const schemaArg = process.argv.indexOf("--schema");
const fixtureDirArg = process.argv.indexOf("--fixtures-dir");
const schemaPath = resolve(
  root,
  schemaArg === -1
    ? "contracts/ws-events.v1.schema.json"
    : process.argv[schemaArg + 1],
);
const fixtureDir = resolve(
  root,
  fixtureDirArg === -1 ? "contracts/fixtures" : process.argv[fixtureDirArg + 1],
);
if (
  (schemaArg !== -1 && !process.argv[schemaArg + 1]) ||
  (fixtureDirArg !== -1 && !process.argv[fixtureDirArg + 1])
) {
  throw new Error("--schema and --fixtures-dir require paths");
}
const readJson = (filePath) => JSON.parse(readFileSync(filePath, "utf8"));
const schema = readJson(schemaPath);
const validFixtures = readJson(resolve(fixtureDir, "ws-events.valid.json"));
const invalidFixtures = readJson(resolve(fixtureDir, "ws-events.invalid.json"));

const ajv = new Ajv2020({ allErrors: true, strict: true });
addFormats(ajv);
const validate = ajv.compile(schema);

for (const [index, event] of validFixtures.entries()) {
  if (!validate(event)) {
    throw new Error(
      `positive fixture ${index + 1} (${event.event_type}) rejected: ${ajv.errorsText(validate.errors)}`,
    );
  }
}

for (const fixture of invalidFixtures) {
  if (validate(fixture.event)) {
    throw new Error(`negative fixture unexpectedly accepted: ${fixture.name}`);
  }
}

console.log(
  `WebSocket schema: ${validFixtures.length} positive and ${invalidFixtures.length} negative fixtures passed`,
);
console.log(
  "Duplicate-key JSON is intentionally not used: standard JSON parsers keep only the last duplicate key; sequence-shape negatives cover parser-independent validation.",
);
