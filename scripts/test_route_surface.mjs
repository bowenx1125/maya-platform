import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const fixture = resolve(root, "contracts/fixtures/route-surface-server.json");
const placeholdersPath = resolve(
  root,
  "contracts/route-surface-placeholders.json",
);
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
  const platformOperationCount = Object.entries(base.paths)
    .filter(([path]) => path.startsWith("/api/v1/"))
    .reduce(
      (count, [, pathItem]) =>
        count +
        Object.keys(pathItem).filter((method) =>
          [
            "get",
            "put",
            "post",
            "patch",
            "delete",
            "options",
            "head",
            "trace",
          ].includes(method),
        ).length,
      0,
    );
  const placeholderContract = JSON.parse(
    readFileSync(placeholdersPath, "utf8"),
  );
  const placeholderCount = Object.keys(
    placeholderContract.allowed_missing_operation_ids ?? {},
  ).length;
  // Teams add immutable definitions, versions, and the scoped Maya directory;
  // online card rooms add seven; renaming or pinning a Chat adds one; a
  // teacher's personal voices add two; the JSON send route is gone (Chats send
  // only through messages:stream); a student's own Record adds one; Team
  // Chat attachments add three; a Team Chat HTML report download adds one; a
  // teacher deleting a Record attempt adds one; Team version lists, assessment
  // activity lists and course-report creation had no caller and are gone;
  // course provider settings (three), the Knowledge graph, Real Report
  // continue and pending report manifests had no caller and are gone;
  // Persona compile/confirm and voice confirm had no caller and are gone;
  // the Record attempt lifecycle-action route had no caller and is gone;
  // stopping a Chat turn had no caller and is gone (pause and resume stay).
  if (platformOperationCount !== 158 || placeholderCount !== 0) {
    throw new Error(
      `Wave 4 route target drifted: ${platformOperationCount} implemented / ${placeholderCount} placeholders`,
    );
  }
  const nextOperation = base.paths["/api/v1/debates/{debate_id}/next"]?.post;
  if (!nextOperation || nextOperation.operationId !== "advanceDebatePlayback") {
    throw new Error(
      "manual-advance route fixture is missing advanceDebatePlayback",
    );
  }
  if (
    JSON.stringify(Object.keys(nextOperation.responses).sort()) !==
    JSON.stringify(["200", "401", "403", "404", "409"])
  ) {
    throw new Error(
      "manual-advance route fixture has the wrong response statuses",
    );
  }
  const nullableEquivalent = structuredClone(base);
  const nullableType =
    nullableEquivalent.components.schemas.KnowledgeDocument.properties
      .safe_error_code.type;
  if (!Array.isArray(nullableType))
    throw new Error("route fixture lost the frozen nullable type array");
  nullableEquivalent.components.schemas.KnowledgeDocument.properties.safe_error_code.type =
    [...nullableType].reverse();
  const nullablePath = resolve(tempDir, "nullable-type-order.json");
  writeFileSync(
    nullablePath,
    `${JSON.stringify(nullableEquivalent, null, 2)}\n`,
    "utf8",
  );
  const nullableResult = run(process.execPath, [
    comparator,
    "--server-openapi",
    nullablePath,
  ]);
  if (nullableResult.status !== 0)
    throw new Error(
      `nullable type order should be semantically equivalent: ${nullableResult.stderr || nullableResult.stdout}`,
    );

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
      "conversation deletion security drift",
      (doc) => {
        doc.paths["/api/v1/conversations/{conversation_id}"].delete.security =
          [];
      },
    ],
    [
      "streaming request body required drift",
      (doc) => {
        doc.paths[
          "/api/v1/conversations/{conversation_id}/messages:stream"
        ].post.requestBody.required = false;
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
      "required response field drift",
      (doc) => {
        doc.components.schemas.AuthSession.required = ["user", "csrf_token"];
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
    [
      "response schema pattern drift",
      (doc) => {
        doc.components.schemas.AgentVersion.properties.version_label.pattern =
          ".*";
      },
    ],
    [
      "knowledge recovery hash wrong shape",
      (doc) => {
        doc.components.schemas.KnowledgeGenerationStatus.properties.provider_manifest_hash.pattern =
          ".*";
      },
      "forbidden browser-visible response field provider_manifest_hash",
    ],
    [
      "knowledge recovery hash wrong operation",
      (doc) => {
        doc.components.schemas.AuthSession.properties.provider_manifest_hash = {
          type: ["string", "null"],
          pattern: "^[0-9a-f]{64}$",
        };
      },
      "forbidden browser-visible response field provider_manifest_hash",
    ],
    [
      "knowledge recovery hash nested scope",
      (doc) => {
        doc.components.schemas.KnowledgeGenerationStatus.properties.detail = {
          type: "object",
          properties: {
            provider_manifest_hash: {
              type: ["string", "null"],
              pattern: "^[0-9a-f]{64}$",
            },
          },
        };
      },
      "forbidden browser-visible response field provider_manifest_hash",
    ],
    [
      "knowledge recovery hash does not allow provider operation",
      (doc) => {
        doc.components.schemas.KnowledgeGenerationStatus.properties.provider_operation =
          {
            type: "string",
          };
      },
      "forbidden browser-visible response field provider_operation",
    ],
  ];
  for (const [name, mutate, expectedFailure] of cases) {
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
    if (
      expectedFailure &&
      !(result.stderr + result.stdout).includes(expectedFailure)
    )
      throw new Error(
        `negative route fixture missed its privacy check: ${name}`,
      );
  }
  console.log(
    `route semantic comparator: positive fixture and ${cases.length} negative cases passed`,
  );
} finally {
  rmSync(tempDir, { recursive: true, force: true });
}
