import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const fixture = resolve(root, "contracts/fixtures/route-surface-server.json");
const tempDir = mkdtempSync(resolve(tmpdir(), "maya-route-surface-test-"));
const generator = resolve(root, "scripts/generate_route_fixture.mjs");
const comparator = resolve(root, "scripts/compare_route_surface.mjs");

function run(command, args) {
  return spawnSync(command, args, {
    cwd: root,
    encoding: "utf8",
    env: { ...process.env, CI: "true" },
  });
}

try {
  const generatedPath = resolve(tempDir, "route-surface-server.json");
  const generated = run(process.execPath, [
    generator,
    "--output",
    generatedPath,
  ]);
  if (generated.status !== 0)
    throw new Error(
      generated.stderr || generated.stdout || "route fixture generator failed",
    );
  if (!readFileSync(generatedPath).equals(readFileSync(fixture)))
    throw new Error("route fixture generator output is not deterministic");

  const positive = run(process.execPath, [
    comparator,
    "--server-openapi",
    fixture,
  ]);
  if (positive.status !== 0)
    throw new Error(
      `positive route fixture rejected: ${positive.stderr || positive.stdout}`,
    );

  const base = JSON.parse(readFileSync(fixture, "utf8"));
  const cases = [
    [
      "missing inherited SessionCookie security",
      (doc) => {
        delete doc.security;
      },
    ],
    [
      "missing session security scheme",
      (doc) => {
        delete doc.components.securitySchemes.sessionCookie;
      },
    ],
    [
      "missing CSRF parameter",
      (doc) => {
        delete doc.paths["/api/v1/auth/logout"].post.parameters;
      },
    ],
    [
      "missing request body",
      (doc) => {
        delete doc.paths["/api/v1/auth/switch"].post.requestBody;
      },
    ],
    [
      "missing frozen error response",
      (doc) => {
        delete doc.paths["/api/v1/auth/login"].post.responses["401"];
      },
    ],
    [
      "incompatible response field",
      (doc) => {
        doc.components.schemas.Uuid.type = "integer";
      },
    ],
    [
      "harmless extra response field",
      (doc) => {
        doc.components.schemas.AuthSession.properties.debug_label = {
          type: "string",
        };
      },
    ],
    [
      "provider response field",
      (doc) => {
        doc.components.schemas.AuthSession.properties.provider = {
          type: "string",
        };
      },
    ],
    [
      "model response field",
      (doc) => {
        doc.components.schemas.AuthSession.properties.model = {
          type: "string",
        };
      },
    ],
    [
      "api_key and key response fields",
      (doc) => {
        doc.components.schemas.AuthSession.properties.api_key = {
          type: "string",
        };
        doc.components.schemas.AuthSession.properties.key = {
          type: "string",
        };
      },
    ],
    [
      "external_voice_id response field",
      (doc) => {
        doc.components.schemas.AuthSession.properties.external_voice_id = {
          type: "string",
        };
      },
    ],
  ];
  for (const [name, mutate] of cases) {
    const candidate = structuredClone(base);
    mutate(candidate);
    const candidatePath = resolve(
      tempDir,
      `${name.replaceAll(/[^a-z0-9]+/gi, "-")}.json`,
    );
    writeFileSync(
      candidatePath,
      `${JSON.stringify(candidate, null, 2)}\n`,
      "utf8",
    );
    const result = run(process.execPath, [
      comparator,
      "--server-openapi",
      candidatePath,
    ]);
    if (result.status === 0)
      throw new Error(`negative route fixture unexpectedly passed: ${name}`);
  }
  console.log(
    `route semantic comparator: positive fixture and ${cases.length} negative cases passed`,
  );
} finally {
  rmSync(tempDir, { recursive: true, force: true });
}
