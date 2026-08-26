import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import Ajv2020 from "ajv/dist/2020.js";
import addFormats from "ajv-formats";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const readJson = (path) =>
  JSON.parse(readFileSync(resolve(root, path), "utf8"));
const ajv = new Ajv2020({ allErrors: true, strict: true });
addFormats(ajv);

const suites = [
  {
    name: "commands",
    schema: "contracts/ws-commands.v1.schema.json",
    valid: "contracts/fixtures/ws-commands.valid.json",
    invalid: "contracts/fixtures/ws-commands.invalid.json",
  },
  {
    name: "command results",
    schema: "contracts/ws-command-results.v1.schema.json",
    valid: "contracts/fixtures/ws-command-results.valid.json",
    invalid: "contracts/fixtures/ws-command-results.invalid.json",
  },
];

for (const suite of suites) {
  const validate = ajv.compile(readJson(suite.schema));
  const positive = readJson(suite.valid);
  const negative = readJson(suite.invalid);
  for (const [index, value] of positive.entries()) {
    if (!validate(value)) {
      throw new Error(
        `${suite.name} positive ${index + 1} rejected: ${ajv.errorsText(validate.errors)}`,
      );
    }
  }
  for (const fixture of negative) {
    if (validate(fixture.value)) {
      throw new Error(
        `${suite.name} negative unexpectedly accepted: ${fixture.name}`,
      );
    }
  }
  console.log(
    `${suite.name}: ${positive.length} positive and ${negative.length} negative fixtures passed`,
  );
}
