import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const redocly = resolve(root, "node_modules/.bin/redocly");
const source = resolve(root, "contracts/openapi-v0.1.yaml");
const allowlistArgument = process.argv.indexOf("--allowlist");
const allowlistPath = resolve(
  root,
  allowlistArgument === -1
    ? "contracts/response-contract-allowlist.json"
    : process.argv[allowlistArgument + 1] ||
        "contracts/response-contract-allowlist.json",
);

function bundle() {
  const tempDir = mkdtempSync(resolve(tmpdir(), "maya-response-contract-"));
  const output = resolve(tempDir, "openapi.json");
  try {
    const result = spawnSync(
      redocly,
      [
        "bundle",
        source,
        "--ext",
        "json",
        "--config",
        resolve(root, "contracts/redocly.yaml"),
        "-o",
        output,
      ],
      { cwd: root, encoding: "utf8" },
    );
    if (result.status !== 0)
      throw new Error(
        result.stderr || result.stdout || "Redocly bundle failed",
      );
    return JSON.parse(readFileSync(output, "utf8"));
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
}

const document = bundle();
const allowlist = JSON.parse(readFileSync(allowlistPath, "utf8"));
const operations = new Map();
for (const [path, pathItem] of Object.entries(document.paths ?? {})) {
  for (const [method, operation] of Object.entries(pathItem)) {
    if (
      ![
        "get",
        "put",
        "post",
        "patch",
        "delete",
        "options",
        "head",
        "trace",
      ].includes(method)
    )
      continue;
    if (!operation.operationId)
      throw new Error(
        `operation at ${method.toUpperCase()} ${path} has no operationId`,
      );
    operations.set(operation.operationId, {
      method: method.toUpperCase(),
      path,
      responses: operation.responses ?? {},
    });
  }
}

const failures = [];
const hasStatusClass = (responses, minimum, maximum) =>
  Object.keys(responses).some(
    (status) =>
      /^\d{3}$/.test(status) &&
      Number(status) >= minimum &&
      Number(status) <= maximum,
  );

for (const [operationId, operation] of operations) {
  const has2xx = hasStatusClass(operation.responses, 200, 299);
  const has4xx = hasStatusClass(operation.responses, 400, 499);
  const missing2xx = allowlist.allow_missing_2xx?.[operationId];
  const missing4xx = allowlist.allow_missing_4xx?.[operationId];
  if (!has2xx) {
    if (
      !missing2xx?.required_status ||
      !operation.responses[missing2xx.required_status] ||
      !missing2xx.reason
    ) {
      failures.push(
        `${operationId} (${operation.method} ${operation.path}) lacks a 2xx response without an explicit documented exception`,
      );
    } else if (
      missing2xx.required_status !== "101" ||
      operationId !== "connectDebateEvents"
    ) {
      failures.push(
        `${operationId} (${operation.method} ${operation.path}) may omit 2xx only for the frozen connectDebateEvents 101 WebSocket upgrade`,
      );
    }
  }
  if (!has4xx && !missing4xx?.reason) {
    failures.push(
      `${operationId} (${operation.method} ${operation.path}) lacks a 4xx response without an explicit documented exception`,
    );
  }
}

for (const [operationId, entry] of Object.entries(
  allowlist.allow_missing_2xx ?? {},
)) {
  if (!operations.has(operationId))
    failures.push(
      `response allowlist references unknown operation ${operationId}`,
    );
  if (!entry.required_status || !entry.reason)
    failures.push(
      `missing-2xx exception ${operationId} needs required_status and reason`,
    );
  if (entry.required_status !== "101" || operationId !== "connectDebateEvents")
    failures.push(
      `missing-2xx exception ${operationId} must be the frozen connectDebateEvents 101 WebSocket upgrade`,
    );
}
for (const [operationId, entry] of Object.entries(
  allowlist.allow_missing_4xx ?? {},
)) {
  if (!operations.has(operationId))
    failures.push(
      `response allowlist references unknown operation ${operationId}`,
    );
  if (!entry.reason)
    failures.push(`missing-4xx exception ${operationId} needs a reason`);
}
for (const [operationId, statuses] of Object.entries(
  allowlist.allow_extra_statuses ?? {},
)) {
  if (!operations.has(operationId))
    failures.push(
      `extra-status allowlist references unknown operation ${operationId}`,
    );
  for (const [status, entry] of Object.entries(statuses)) {
    if (!/^\d{3}$/.test(status) || !entry.reason)
      failures.push(
        `extra-status exception ${operationId}/${status} needs a numeric status and reason`,
      );
  }
}

if (failures.length)
  throw new Error(
    `frozen OpenAPI response contract failed:\n- ${failures.join("\n- ")}`,
  );
console.log(
  `frozen OpenAPI response contract passed: ${operations.size} operations; explicit exceptions cover only documented 101/4xx omissions`,
);
