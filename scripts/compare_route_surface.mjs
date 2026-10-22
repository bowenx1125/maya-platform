import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const frozenPath = resolve(root, "contracts/openapi-v0.1.yaml");
const placeholderPath = resolve(
  root,
  "contracts/route-surface-placeholders.json",
);
const responseAllowlistPath = resolve(
  root,
  "contracts/response-contract-allowlist.json",
);
const redocly = resolve(root, "node_modules/@redocly/cli/bin/cli.js");
const implementedOperationIds = new Set([
  "login",
  "switchDemoIdentity",
  "listDemoIdentities",
  "quickLogin",
  "getCurrentUser",
  "logout",
  "listCourses",
  "getCourse",
  "listCourseGroups",
  "getGroup",
  "getGroupOverview",
  "listGroupAgents",
  "createAgent",
  "listCourseWorkspaceAgents",
  "createCourseWorkspaceAgent",
  "getAgent",
  "updateAgentMetadata",
  "deleteAgent",
  "listAgentVersions",
  "createNextAgentVersion",
  "getAgentVersion",
  "updateAgentDraft",
  "downloadAgentMd",
  "uploadAgentMd",
  "publishAgentVersion",
  "getAgentKnowledgeSets",
  "replaceAgentKnowledgeSets",
  "listKnowledgeSets",
  "createKnowledgeSet",
  "getKnowledgeSetAsset",
  "updateKnowledgeSetAsset",
  "listKnowledgeSetAssetVersions",
  "getKnowledgeSet",
  "updateKnowledgeSetMetadata",
  "deleteKnowledgeSet",
  "listKnowledgeSetAssets",
  "createKnowledgeSetAsset",
  "replaceKnowledgeSetSources",
  "removeKnowledgeSetSource",
  "listKnowledgeDocuments",
  "uploadKnowledgeDocument",
  "listCourseWorkspaceDocuments",
  "uploadCourseWorkspaceDocument",
  "getKnowledgeDocument",
  "listKnowledgeDocumentAffectedAgents",
  "listVoiceProfileAffectedAgents",
  "updateKnowledgeDocumentVisibility",
  "replaceKnowledgeDocument",
  "downloadKnowledgeDocument",
  "reindexKnowledgeDocument",
  "hideKnowledgeDocument",
  "setAgentVersionDocuments",
  "getRagPreview",
  "testAgentDraft",
  "getKnowledgeSnapshot",
  "downloadSnapshotRag",
  "downloadSnapshotDocument",
  "listPublishedAgentsForTeacher",
  "listAvatarTemplates",
  "listVoiceProfiles",
  "enrollVoice",
  "listPersonalVoiceProfiles",
  "enrollPersonalVoice",
  "getVoiceProfile",
  "deleteVoiceProfile",
  "createVoicePreview",
  "getDebateRulesetDefaults",
  "listDebates",
  "createDebate",
  "getDebate",
  "updateDebateDraft",
  "startDebate",
  "advanceDebatePlayback",
  "freezeFinalInput",
  "deleteDebateVoice",
  "regenerateDebateTurnAudio",
  "deleteDebateAll",
  "replayDebate",
  "connectDebateEvents",
  "getDebateTranscript",
  "streamRetainedTurnAudio",
  "listChatAgents",
  "listConversations",
  "createConversation",
  "getConversation",
  "streamConversationMessage",
  "deleteConversation",
  "updateConversation",
  "listConversationAttachments",
  "downloadConversationReport",
  "uploadConversationAttachment",
  "deleteConversationAttachment",
  "deleteTeam",
  "createCardRoom",
  "getCardRoom",
  "joinCardRoom",
  "leaveCardRoom",
  "startCardRoom",
  "actInCardRoom",
  "rebuyInCardRoom",
  "updateClassroomLive",
  "getClassroomLive",
  "getLiveSnapshot",
  "getLiveAudio",
  "changeCurrentPassword",
  "confirmTeamProviderStandingGrant",
  "createMemoryEntryAction",
  "downloadAssessmentCourseReport",
  "getChatStandingProviderDisclosure",
  "getKnowledgeMarkdown",
  "listCourseAssessmentAttempts",
  "deleteCourseAssessmentAttempt",
  "listMyAssessmentAttempts",
  "listBrainformKnowledge",
  "pauseTeamConversationTurn",
  "previewTeamProviderStandingGrant",
  "regenerateKnowledgeMarkdown",
  "renameKnowledgeDocument",
  "resumeTeamConversationTurn",
  "saveKnowledgeMarkdown",
  "updateCurrentUser",
  "closeInteraction",
  "confirmProviderDataCallDisclosure",
  "createTeam",
  "downloadCurrentReport",
  "finishDebate",
  "getClassroomInteractionForm",
  "getCourseRoster",
  "getCurrentReport",
  "getKnowledgeGenerationJob",
  "getProviderDataCallDisclosure",
  "getRegistrationOptions",
  "getReportRevision",
  "getTeacherInteraction",
  "getTeam",
  "joinGroupAsTeacher",
  "leaveGroupAsTeacher",
  "listCourseTeams",
  "listMayaTeams",
  "listProviderDataCallDebateManifests",
  "listProviderDataCallManifests",
  "listProviderDataCallPublicationManifests",
  "listReportRevisions",
  "openInteraction",
  "pauseDebate",
  "rebirthDebate",
  "regenerateReport",
  "registerStudent",
  "releaseDebate",
  "remakeDebate",
  "renameVoiceProfile",
  "resetStudentPassword",
  "resumeDebate",
  "retryDebatePreparation",
  "saveTeamVersion",
  "submitBarrage",
  "submitVote",
  "updateCourseMember",
]);
const methods = new Set([
  "get",
  "put",
  "post",
  "patch",
  "delete",
  "options",
  "head",
  "trace",
]);
const forbiddenResponseFieldPattern =
  /(^|[_-])(provider|model|api[_-]?key|external[_-]?voice(?:[_-]?id)?)(?=$|[_-])/i;

const serverArg = process.argv.indexOf("--server-openapi");
if (serverArg === -1) {
  if (
    process.env.CI ||
    !process.argv.includes("--allow-missing-server-openapi")
  ) {
    throw new Error(
      "generated FastAPI OpenAPI is required; pass --server-openapi PATH (CI never permits the developer skip)",
    );
  }
  console.log(
    "developer-only route comparison skip was explicitly requested; Wave 0 placeholders remain explicit in contracts/route-surface-placeholders.json",
  );
  process.exit(0);
}
const serverPath = process.argv[serverArg + 1];
if (!serverPath)
  throw new Error("--server-openapi requires a JSON or YAML file path");

function bundleToJson(inputPath) {
  const tempDir = mkdtempSync(resolve(tmpdir(), "maya-route-surface-"));
  const output = resolve(tempDir, "openapi.json");
  try {
    const result = spawnSync(
      process.execPath,
      [
        redocly,
        "bundle",
        inputPath,
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
        result.stderr || result.stdout || `could not bundle ${inputPath}`,
      );
    return JSON.parse(readFileSync(output, "utf8"));
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
}

function surface(document, prefix = "") {
  const result = new Map();
  const operationIds = new Set();
  for (const [rawPath, pathItem] of Object.entries(document.paths ?? {})) {
    for (const [method, operation] of Object.entries(pathItem)) {
      if (!methods.has(method)) continue;
      if (!operation || typeof operation.operationId !== "string") {
        throw new Error(
          `operation at ${method.toUpperCase()} ${rawPath} has no operationId`,
        );
      }
      const path =
        prefix && (rawPath === prefix || rawPath.startsWith(`${prefix}/`))
          ? rawPath.slice(prefix.length) || "/"
          : rawPath;
      const route = `${method.toUpperCase()} ${path}`;
      if (result.has(route))
        throw new Error(`duplicate method/path in route surface: ${route}`);
      if (operationIds.has(operation.operationId))
        throw new Error(
          `duplicate operationId in route surface: ${operation.operationId}`,
        );
      operationIds.add(operation.operationId);
      result.set(route, {
        method: method.toUpperCase(),
        path,
        rawPath,
        operationId: operation.operationId,
        operation,
        pathItem,
      });
    }
  }
  return result;
}

function resolveRef(document, value) {
  if (!value || typeof value !== "object" || typeof value.$ref !== "string")
    return value;
  if (!value.$ref.startsWith("#/"))
    throw new Error(
      `external reference is not allowed in semantic comparison: ${value.$ref}`,
    );
  let current = document;
  for (const part of value.$ref.slice(2).split("/"))
    current = current[part.replaceAll("~1", "/").replaceAll("~0", "~")];
  if (!current)
    throw new Error(
      `unresolved reference during semantic comparison: ${value.$ref}`,
    );
  return current;
}

function normaliseSchema(document, schema, seen = new Set()) {
  if (!schema || typeof schema !== "object") return schema;
  if (schema.$ref) {
    if (seen.has(schema.$ref)) return schema;
    const next = new Set(seen);
    next.add(schema.$ref);
    return normaliseSchema(document, resolveRef(document, schema), next);
  }
  if (!schema.allOf) {
    const copy = { ...schema };
    // OpenAPI 3.1's multi-type `type` is a set of allowed types.  Its array
    // order is not semantic, so canonicalize it before strict comparison.
    if (Array.isArray(copy.type)) copy.type = [...copy.type].sort();
    for (const keyword of ["oneOf", "anyOf"]) {
      if (Array.isArray(copy[keyword]))
        copy[keyword] = copy[keyword].map((branch) =>
          normaliseSchema(document, branch, seen),
        );
    }
    if (copy.items) copy.items = normaliseSchema(document, copy.items, seen);
    if (copy.properties)
      copy.properties = Object.fromEntries(
        Object.entries(copy.properties).map(([name, item]) => [
          name,
          normaliseSchema(document, item, seen),
        ]),
      );
    return copy;
  }
  const fragments = schema.allOf.map((fragment) =>
    normaliseSchema(document, fragment, seen),
  );
  const merged = { ...schema };
  delete merged.$ref;
  delete merged.allOf;
  merged.required = [
    ...new Set(fragments.flatMap((fragment) => fragment.required ?? [])),
  ];
  merged.properties = Object.assign(
    {},
    ...fragments.map((fragment) => fragment.properties ?? {}),
    schema.properties ?? {},
  );
  for (const fragment of fragments) {
    for (const key of [
      "type",
      "format",
      "items",
      "enum",
      "const",
      "minimum",
      "maximum",
      "minLength",
      "maxLength",
      "pattern",
      "additionalProperties",
    ]) {
      if (merged[key] === undefined && fragment[key] !== undefined)
        merged[key] = fragment[key];
    }
  }
  if (Array.isArray(merged.type)) merged.type = [...merged.type].sort();
  for (const [name, item] of Object.entries(merged.properties ?? {}))
    merged.properties[name] = normaliseSchema(document, item, seen);
  return merged;
}

function normaliseFieldName(name) {
  return name
    .replace(/([a-z0-9])([A-Z])/g, "$1_$2")
    .replaceAll("-", "_")
    .toLowerCase();
}

function findForbiddenResponseFields(
  document,
  schema,
  context,
  failures,
  seenRefs = new Set(),
  seenObjects = new Set(),
) {
  if (!schema || typeof schema !== "object" || seenObjects.has(schema)) return;
  seenObjects.add(schema);
  if (typeof schema.$ref === "string") {
    if (seenRefs.has(schema.$ref)) return;
    const refs = new Set(seenRefs);
    refs.add(schema.$ref);
    findForbiddenResponseFields(
      document,
      resolveRef(document, schema),
      context,
      failures,
      refs,
      seenObjects,
    );
    return;
  }
  for (const [name, child] of Object.entries(schema.properties ?? {})) {
    const ownerRecoveryHash =
      context === "getKnowledgeGenerationJob.response.200.application/json" &&
      name === "provider_manifest_hash" &&
      child.pattern === "^[0-9a-f]{64}$" &&
      Array.isArray(child.type) &&
      JSON.stringify([...child.type].sort()) ===
        JSON.stringify(["null", "string"]);
    if (
      forbiddenResponseFieldPattern.test(normaliseFieldName(name)) &&
      !ownerRecoveryHash
    )
      failures.push(
        `${context}: forbidden browser-visible response field ${name}`,
      );
    findForbiddenResponseFields(
      document,
      child,
      `${context}.${name}`,
      failures,
      seenRefs,
      seenObjects,
    );
  }
  for (const keyword of ["allOf", "anyOf", "oneOf", "prefixItems"])
    for (const [index, child] of (Array.isArray(schema[keyword])
      ? schema[keyword]
      : []
    ).entries())
      findForbiddenResponseFields(
        document,
        child,
        `${context}.${keyword}[${index}]`,
        failures,
        seenRefs,
        seenObjects,
      );
  findForbiddenResponseFields(
    document,
    schema.items,
    `${context}.items`,
    failures,
    seenRefs,
    seenObjects,
  );
  findForbiddenResponseFields(
    document,
    schema.additionalProperties,
    `${context}.additionalProperties`,
    failures,
    seenRefs,
    seenObjects,
  );
  for (const [name, child] of Object.entries(schema.patternProperties ?? {}))
    findForbiddenResponseFields(
      document,
      child,
      `${context}.patternProperties.${name}`,
      failures,
      seenRefs,
      seenObjects,
    );
}

function compareSchemas(expected, actual, context, errors, options = {}) {
  if (!expected || !actual) {
    if (expected !== actual) errors.push(`${context}: schema presence differs`);
    return;
  }
  const expectedUnion = expected.oneOf ?? expected.anyOf;
  const actualUnion = actual.oneOf ?? actual.anyOf;
  if (expectedUnion) {
    if (!actualUnion) {
      errors.push(`${context}: expected a union schema`);
      return;
    }
    for (const [index, expectedBranch] of expectedUnion.entries()) {
      const branchMatches = actualUnion.some((actualBranch) => {
        const branchErrors = [];
        compareSchemas(
          expectedBranch,
          actualBranch,
          `${context}[${index}]`,
          branchErrors,
          options,
        );
        return branchErrors.length === 0;
      });
      if (!branchMatches)
        errors.push(
          `${context}: no compatible server branch for frozen union member ${index}`,
        );
    }
    return;
  }
  if (actualUnion) {
    if (
      !actualUnion.every((actualBranch) => {
        const branchErrors = [];
        compareSchemas(expected, actualBranch, context, branchErrors, options);
        return branchErrors.length === 0;
      })
    )
      errors.push(`${context}: server union is wider than the frozen schema`);
    return;
  }
  const expectedType = Array.isArray(expected.type)
    ? [...expected.type].sort()
    : expected.type;
  const actualType = Array.isArray(actual.type)
    ? [...actual.type].sort()
    : actual.type;
  if (
    expected.type !== undefined &&
    JSON.stringify(actualType) !== JSON.stringify(expectedType)
  )
    errors.push(
      `${context}: type ${JSON.stringify(actual.type)} does not match ${JSON.stringify(expected.type)}`,
    );
  if (expected.format !== undefined && actual.format !== expected.format)
    errors.push(
      `${context}: format ${actual.format} does not match ${expected.format}`,
    );
  if (expected.const !== undefined && actual.const !== expected.const)
    errors.push(`${context}: const differs`);
  if (
    expected.enum !== undefined &&
    JSON.stringify(expected.enum) !== JSON.stringify(actual.enum)
  )
    errors.push(`${context}: enum differs`);
  for (const keyword of [
    "minimum",
    "maximum",
    "minLength",
    "maxLength",
    "pattern",
  ]) {
    if (
      expected[keyword] !== undefined &&
      actual[keyword] !== expected[keyword]
    )
      errors.push(`${context}: ${keyword} differs`);
  }
  if (expected.type === "array") {
    if (!actual.items) errors.push(`${context}: array items schema missing`);
    else
      compareSchemas(
        expected.items,
        actual.items,
        `${context}.items`,
        errors,
        options,
      );
  }
  if (expected.type === "object" || expected.properties) {
    const expectedRequired = [...(expected.required ?? [])].sort();
    const actualRequired = [...(actual.required ?? [])].sort();
    const allowResponseSchemaSuperset =
      options.response && options.allowResponseSchemaSuperset;
    const requiredCompatible = allowResponseSchemaSuperset
      ? expectedRequired.every((field) => actualRequired.includes(field))
      : JSON.stringify(expectedRequired) === JSON.stringify(actualRequired);
    if (!requiredCompatible)
      errors.push(
        `${context}: required fields differ (${expectedRequired.join(",")} vs ${actualRequired.join(",")})`,
      );
    const expectedNames = Object.keys(expected.properties ?? {}).sort();
    const actualNames = Object.keys(actual.properties ?? {}).sort();
    const propertiesCompatible = allowResponseSchemaSuperset
      ? expectedNames.every((name) => actualNames.includes(name))
      : JSON.stringify(expectedNames) === JSON.stringify(actualNames);
    if (!propertiesCompatible) errors.push(`${context}: property set differs`);
    for (const name of expectedNames)
      if (actual.properties?.[name])
        compareSchemas(
          expected.properties[name],
          actual.properties[name],
          `${context}.${name}`,
          errors,
          options,
        );
  }
}

function schemaErrors(
  frozenDocument,
  serverDocument,
  expectedSchema,
  actualSchema,
  context,
  options = {},
) {
  const errors = [];
  compareSchemas(
    normaliseSchema(frozenDocument, expectedSchema),
    normaliseSchema(serverDocument, actualSchema),
    context,
    errors,
    options,
  );
  return errors;
}

function parameters(document, entry) {
  const merged = new Map();
  for (const parameter of [
    ...(entry.pathItem.parameters ?? []),
    ...(entry.operation.parameters ?? []),
  ]) {
    const resolved = resolveRef(document, parameter);
    merged.set(`${resolved.in}:${resolved.name}`, resolved);
  }
  return merged;
}

function effectiveSecurity(document, entry) {
  return Object.hasOwn(entry.operation, "security")
    ? (entry.operation.security ?? [])
    : (document.security ?? []);
}

function compareImplementedOperation(
  frozenDocument,
  serverDocument,
  expected,
  actual,
  failures,
  responseAllowlist,
) {
  const operationId = expected.operationId;
  const expectedSecurity = JSON.stringify(
    effectiveSecurity(frozenDocument, expected),
  );
  const actualSecurity = JSON.stringify(
    effectiveSecurity(serverDocument, actual),
  );
  if (expectedSecurity !== actualSecurity)
    failures.push(
      `${operationId}: security differs (frozen ${expectedSecurity}, server ${actualSecurity})`,
    );
  const expectedSchemes = frozenDocument.components?.securitySchemes ?? {};
  const actualSchemes = serverDocument.components?.securitySchemes ?? {};
  for (const scheme of effectiveSecurity(frozenDocument, expected).flatMap(
    (requirement) => Object.keys(requirement),
  )) {
    const frozenScheme = expectedSchemes[scheme];
    const serverScheme = actualSchemes[scheme];
    if (!serverScheme)
      failures.push(
        `${operationId}: required security scheme ${scheme} is missing from server OpenAPI`,
      );
    else
      for (const field of ["type", "in", "name"])
        if (frozenScheme[field] !== serverScheme[field])
          failures.push(
            `${operationId}: security scheme ${scheme}.${field} differs`,
          );
  }

  const expectedParameters = parameters(frozenDocument, expected);
  const actualParameters = parameters(serverDocument, actual);
  for (const [key, frozenParameter] of expectedParameters) {
    const serverParameter = actualParameters.get(key);
    if (!serverParameter) {
      failures.push(`${operationId}: missing parameter ${key}`);
      continue;
    }
    if (Boolean(frozenParameter.required) !== Boolean(serverParameter.required))
      failures.push(`${operationId}: parameter ${key} required flag differs`);
    if (frozenParameter.schema && serverParameter.schema)
      failures.push(
        ...schemaErrors(
          frozenDocument,
          serverDocument,
          frozenParameter.schema,
          serverParameter.schema,
          `${operationId}.parameter.${key}`,
        ),
      );
  }
  for (const key of actualParameters.keys())
    if (!expectedParameters.has(key))
      failures.push(`${operationId}: unexpected parameter ${key}`);

  const frozenBody = expected.operation.requestBody;
  const serverBody = actual.operation.requestBody;
  if (Boolean(frozenBody) !== Boolean(serverBody)) {
    failures.push(`${operationId}: request body presence differs`);
  } else if (frozenBody) {
    const expectedRequestBody = resolveRef(frozenDocument, frozenBody);
    const actualRequestBody = resolveRef(serverDocument, serverBody);
    if (
      Boolean(expectedRequestBody.required) !==
      Boolean(actualRequestBody.required)
    )
      failures.push(`${operationId}: request body required flag differs`);
    const expectedMedia = Object.keys(expectedRequestBody.content ?? {}).sort();
    const actualMedia = Object.keys(actualRequestBody.content ?? {}).sort();
    if (JSON.stringify(expectedMedia) !== JSON.stringify(actualMedia))
      failures.push(`${operationId}: request body media types differ`);
    for (const media of expectedMedia) {
      if (!actualRequestBody.content?.[media]?.schema)
        failures.push(
          `${operationId}: request body schema missing for ${media}`,
        );
      else
        failures.push(
          ...schemaErrors(
            frozenDocument,
            serverDocument,
            expectedRequestBody.content[media].schema,
            actualRequestBody.content[media].schema,
            `${operationId}.request.${media}`,
          ),
        );
    }
  }

  const expectedStatuses = Object.keys(expected.operation.responses ?? {});
  const actualStatuses = Object.keys(actual.operation.responses ?? {});
  for (const status of expectedStatuses) {
    const frozenResponse = resolveRef(
      frozenDocument,
      expected.operation.responses[status],
    );
    const serverResponse = actual.operation.responses?.[status]
      ? resolveRef(serverDocument, actual.operation.responses[status])
      : undefined;
    if (!serverResponse) {
      failures.push(
        `${operationId}: frozen response ${status} is absent from server OpenAPI`,
      );
      continue;
    }
    const frozenContent = Object.keys(frozenResponse.content ?? {}).sort();
    const serverContent = Object.keys(serverResponse.content ?? {}).sort();
    if (JSON.stringify(frozenContent) !== JSON.stringify(serverContent))
      failures.push(`${operationId}: response ${status} media types differ`);
    for (const media of frozenContent) {
      if (!serverResponse.content?.[media]?.schema)
        failures.push(
          `${operationId}: response ${status} schema missing for ${media}`,
        );
      else {
        const forbidden = [];
        findForbiddenResponseFields(
          serverDocument,
          serverResponse.content[media].schema,
          `${operationId}.response.${status}.${media}`,
          forbidden,
        );
        failures.push(...forbidden);
        failures.push(
          ...schemaErrors(
            frozenDocument,
            serverDocument,
            frozenResponse.content[media].schema,
            serverResponse.content[media].schema,
            `${operationId}.response.${status}.${media}`,
            {
              response: true,
              allowResponseSchemaSuperset:
                responseAllowlist.allow_response_schema_supersets?.[
                  operationId
                ]?.[status]?.reason !== undefined,
            },
          ),
        );
      }
    }
    const frozenHeaders = new Map(
      Object.entries(frozenResponse.headers ?? {}).map(([name, header]) => [
        name.toLowerCase(),
        resolveRef(frozenDocument, header),
      ]),
    );
    const serverHeaders = new Map(
      Object.entries(serverResponse.headers ?? {}).map(([name, header]) => [
        name.toLowerCase(),
        resolveRef(serverDocument, header),
      ]),
    );
    for (const [name, frozenHeader] of frozenHeaders) {
      const serverHeader = serverHeaders.get(name);
      if (!serverHeader) {
        failures.push(
          `${operationId}: response ${status} header ${name} is missing`,
        );
        continue;
      }
      if (frozenHeader.schema && serverHeader.schema)
        failures.push(
          ...schemaErrors(
            frozenDocument,
            serverDocument,
            frozenHeader.schema,
            serverHeader.schema,
            `${operationId}.response.${status}.header.${name}`,
          ),
        );
      else if (Boolean(frozenHeader.schema) !== Boolean(serverHeader.schema))
        failures.push(
          `${operationId}: response ${status} header ${name} schema presence differs`,
        );
    }
  }
  const allowedExtraStatuses =
    responseAllowlist.allow_extra_statuses?.[operationId] ?? {};
  for (const status of actualStatuses)
    if (
      !expectedStatuses.includes(status) &&
      !allowedExtraStatuses[status]?.reason
    )
      failures.push(
        `${operationId}: unexpected response ${status} without an explicit allow-list reason`,
      );
}

const frozenDocument = bundleToJson(frozenPath);
const serverDocument = bundleToJson(resolve(root, serverPath));
const frozen = surface(frozenDocument);
const server = surface(serverDocument, "/api/v1");
const placeholders = JSON.parse(readFileSync(placeholderPath, "utf8"));
const responseAllowlist = JSON.parse(
  readFileSync(responseAllowlistPath, "utf8"),
);
const allowedMissing = placeholders.allowed_missing_operation_ids ?? {};
const allowedExtra = placeholders.allowed_extra_operation_ids ?? {};
const failures = [];
const classified = [];
const frozenByOperationId = new Map(
  [...frozen.values()].map((entry) => [entry.operationId, entry]),
);
for (const [operationId, statuses] of Object.entries(
  responseAllowlist.allow_response_schema_supersets ?? {},
)) {
  const expected = frozenByOperationId.get(operationId);
  if (!expected)
    failures.push(
      `response schema allow-list references unknown operation ${operationId}`,
    );
  for (const [status, entry] of Object.entries(statuses ?? {})) {
    if (!expected?.operation.responses?.[status])
      failures.push(
        `response schema allow-list references unknown response ${operationId}/${status}`,
      );
    if (!entry?.reason)
      failures.push(
        `response schema allow-list exception ${operationId}/${status} needs a reviewed reason`,
      );
  }
}

for (const [route, expected] of frozen) {
  const actual = server.get(route);
  const operationId = expected.operationId;
  if (!actual) {
    if (implementedOperationIds.has(operationId))
      failures.push(
        `implemented operation ${operationId} is missing (${expected.method} ${expected.path})`,
      );
    else if (
      allowedMissing[operationId]?.owner &&
      allowedMissing[operationId]?.reason
    )
      classified.push(`${operationId} (${allowedMissing[operationId].owner})`);
    else
      failures.push(
        `missing operation ${operationId} (${expected.method} ${expected.path}) without an explicit placeholder`,
      );
    continue;
  }
  if (actual.operationId !== operationId)
    failures.push(
      `operationId drift at ${route}: frozen ${operationId}, server ${actual.operationId}`,
    );
  if (implementedOperationIds.has(operationId))
    compareImplementedOperation(
      frozenDocument,
      serverDocument,
      expected,
      actual,
      failures,
      responseAllowlist,
    );
}

for (const [route, actual] of server)
  if (!frozen.has(route) && !allowedExtra[actual.operationId]?.owner)
    failures.push(
      `unexpected server operation ${actual.operationId} (${route})`,
    );
for (const [operationId, classification] of Object.entries(allowedMissing)) {
  if (!frozenByOperationId.has(operationId))
    failures.push(
      `placeholder references unknown frozen operation ${operationId}`,
    );
  if (implementedOperationIds.has(operationId))
    failures.push(
      `implemented operation ${operationId} cannot be a Wave 0 placeholder`,
    );
  if (!classification.owner || !classification.reason)
    failures.push(`placeholder ${operationId} needs owner and reason`);
}

if (failures.length)
  throw new Error(
    `route/semantic contract mismatch:\n- ${failures.join("\n- ")}`,
  );
console.log(
  `route and semantic contract match: ${implementedOperationIds.size} implemented operations; ${classified.length} explicit later-wave placeholders; health extras remain classified`,
);
