import { readFileSync, rmSync, writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outputArg = process.argv.indexOf("--output");
const output = resolve(
  root,
  outputArg === -1
    ? "contracts/fixtures/route-surface-server.json"
    : process.argv[outputArg + 1],
);
const redocly = resolve(root, "node_modules/.bin/redocly");
const frozen = resolve(root, "contracts/openapi-v0.1.yaml");
const temporary = resolve(output, "..", ".route-fixture-source.json");
const implemented = new Set([
  "login",
  "switchDemoIdentity",
  "listDemoIdentities",
  "quickLogin",
  "getRegistrationOptions",
  "registerStudent",
  "getCurrentUser",
  "resetStudentPassword",
  "logout",
  "listCourses",
  "getCourse",
  "listCourseGroups",
  "getGroup",
  "getCourseRoster",
  "updateCourseMember",
  "joinGroupAsTeacher",
  "leaveGroupAsTeacher",
  "listGroupAgents",
  "createAgent",
  "getAgent",
  "updateAgentMetadata",
  "deleteAgent",
  "listAgentVersions",
  "createNextAgentVersion",
  "getAgentVersion",
  "updateAgentDraft",
  "downloadAgentMd",
  "uploadAgentMd",
  "compileAgentPersona",
  "confirmAgentPersona",
  "publishAgentVersion",
  "listKnowledgeDocuments",
  "uploadKnowledgeDocument",
  "getKnowledgeDocument",
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
  "getVoiceProfile",
  "deleteVoiceProfile",
  "createVoicePreview",
  "confirmVoiceProfile",
  "getDebateRulesetDefaults",
  "listDebates",
  "createDebate",
  "getDebate",
  "updateDebateDraft",
  "startDebate",
  "retryDebatePreparation",
  "advanceDebatePlayback",
  "freezeFinalInput",
  "deleteDebateVoice",
  "regenerateDebateTurnAudio",
  "deleteDebateAll",
  "rebirthDebate",
  "remakeDebate",
  "pauseDebate",
  "resumeDebate",
  "finishDebate",
  "releaseDebate",
  "replayDebate",
  "connectDebateEvents",
  "getDebateTranscript",
  "streamRetainedTurnAudio",
  "listChatAgents",
  "listConversations",
  "createConversation",
  "getConversation",
  "sendConversationMessage",
  "getProviderSettings",
  "updateProviderSettings",
  "checkProvider",
  "updateClassroomLive",
  "getClassroomLive",
  "getLiveSnapshot",
  "getLiveAudio",
  "getTeacherInteraction",
  "openInteraction",
  "closeInteraction",
  "getClassroomInteractionForm",
  "submitVote",
  "submitBarrage",
  "getCurrentReport",
  "regenerateReport",
  "listReportRevisions",
  "getReportRevision",
  "continueRealReport",
  "downloadCurrentReport",
  "getProviderDataCallDisclosure",
  "listProviderDataCallManifests",
  "listProviderDataCallDebateManifests",
  "listProviderDataCallReportManifests",
  "listProviderDataCallPublicationManifests",
  "confirmProviderDataCallDisclosure",
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

const result = spawnSync(
  redocly,
  [
    "bundle",
    frozen,
    "--ext",
    "json",
    "--config",
    resolve(root, "contracts/redocly.yaml"),
    "-o",
    temporary,
  ],
  { cwd: root, encoding: "utf8" },
);
if (result.status !== 0)
  throw new Error(
    result.stderr || result.stdout || "could not bundle frozen OpenAPI",
  );
const source = JSON.parse(readFileSync(temporary, "utf8"));
rmSync(temporary, { force: true });
const server = {
  openapi: source.openapi,
  info: source.info,
  security: source.security,
  paths: {},
  components: source.components,
};
for (const [path, pathItem] of Object.entries(source.paths ?? {})) {
  const selected = {};
  if (pathItem.parameters)
    selected.parameters = structuredClone(pathItem.parameters);
  for (const [method, operation] of Object.entries(pathItem)) {
    if (!methods.has(method) || !implemented.has(operation.operationId))
      continue;
    selected[method] = structuredClone(operation);
    const allowedExtras =
      {
        login: ["422"],
        switchDemoIdentity: ["422"],
        logout: ["422"],
        getCourse: ["422"],
        listCourseGroups: ["422"],
        getGroup: ["422"],
      }[operation.operationId] ?? [];
    for (const status of allowedExtras)
      selected[method].responses[status] = {
        description:
          "FastAPI request validation response (explicitly allow-listed).",
        content: {
          "application/json": {
            schema: { $ref: "#/components/schemas/Error" },
          },
        },
      };
  }
  if (Object.keys(selected).some((key) => key !== "parameters"))
    server.paths[`/api/v1${path}`] = selected;
}
server.paths["/health/live"] = {
  get: {
    operationId: "health_live_health_live_get",
    responses: { 200: { description: "OK" } },
  },
};
server.paths["/health/ready"] = {
  get: {
    operationId: "health_ready_health_ready_get",
    responses: { 200: { description: "Ready" } },
  },
};
writeFileSync(output, `${JSON.stringify(server, null, 2)}\n`, "utf8");
console.log(`generated route semantic fixture ${output}`);
