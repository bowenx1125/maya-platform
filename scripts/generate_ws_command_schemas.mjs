import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { writeFileSync } from "node:fs";
import { format } from "prettier";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const commandsArg = process.argv.indexOf("--commands-output");
const resultsArg = process.argv.indexOf("--results-output");
if (
  (commandsArg !== -1 && !process.argv[commandsArg + 1]) ||
  (resultsArg !== -1 && !process.argv[resultsArg + 1])
) {
  throw new Error("--commands-output and --results-output require paths");
}
const commandsOutput = resolve(
  root,
  commandsArg === -1
    ? "contracts/ws-commands.v1.schema.json"
    : process.argv[commandsArg + 1],
);
const resultsOutput = resolve(
  root,
  resultsArg === -1
    ? "contracts/ws-command-results.v1.schema.json"
    : process.argv[resultsArg + 1],
);

const uuid = { type: "string", format: "uuid" };
const isoTime = { type: "string", format: "date-time" };
const integer = (minimum = 0) => ({ type: "integer", minimum });
const nonEmpty = { type: "string", minLength: 1 };
const privateMediaUrl = {
  type: "string",
  pattern:
    "^/api/v1/debates/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}/audio/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}\\?media_ticket=[A-Za-z0-9_-]{43}$",
};
const closed = (properties, required) => ({
  type: "object",
  properties,
  required,
  additionalProperties: false,
});

const commandBase = (commandType, extraProperties, extraRequired = []) =>
  closed(
    {
      command_id: uuid,
      command_type: { type: "string", const: commandType },
      command_version: { type: "integer", const: 1 },
      debate_id: uuid,
      expected_control_version: integer(0),
      ...extraProperties,
    },
    [
      "command_id",
      "command_type",
      "command_version",
      "debate_id",
      "expected_control_version",
      ...extraRequired,
    ],
  );

const playbackAction = {
  type: "string",
  enum: ["start", "resume", "next", "replay"],
};

const commandBranches = [
  commandBase("playback.controller.acquire", {}),
  commandBase(
    "playback.media.prepare",
    {
      controller_epoch: uuid,
      turn_id: uuid,
      playback_action: playbackAction,
    },
    ["controller_epoch", "turn_id", "playback_action"],
  ),
  commandBase(
    "playback.started_ack",
    {
      controller_epoch: uuid,
      turn_id: uuid,
      playback_action: playbackAction,
    },
    ["controller_epoch", "turn_id", "playback_action"],
  ),
  commandBase("playback.ended_ack", { controller_epoch: uuid, turn_id: uuid }, [
    "controller_epoch",
    "turn_id",
  ]),
  commandBase(
    "playback.play_failed",
    {
      controller_epoch: uuid,
      turn_id: uuid,
      playback_action: playbackAction,
      failure_phase: { type: "string", enum: ["pre_ack", "post_ack"] },
      cursor_ms: integer(0),
      safe_client_code: {
        type: "string",
        enum: [
          "autoplay_blocked",
          "not_supported",
          "decode_error",
          "network_error",
          "aborted",
          "unknown",
        ],
      },
    },
    [
      "controller_epoch",
      "turn_id",
      "playback_action",
      "failure_phase",
      "cursor_ms",
      "safe_client_code",
    ],
  ),
];

const commandsSchema = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  $id: "https://maya.local/contracts/ws-commands.v1.schema.json",
  title: "Maya v1 private WebSocket playback commands",
  description:
    "Closed inbound teacher-controller commands. They never choose turns or expose prepared content.",
  oneOf: commandBranches,
};

const resultBase = (messageType, extraProperties, extraRequired = []) =>
  closed(
    {
      message_id: uuid,
      message_type: { type: "string", const: messageType },
      result_version: { type: "integer", const: 1 },
      debate_id: uuid,
      occurred_at: isoTime,
      ...extraProperties,
    },
    [
      "message_id",
      "message_type",
      "result_version",
      "debate_id",
      "occurred_at",
      ...extraRequired,
    ],
  );

const resultBranches = [
  resultBase(
    "controller.acquired",
    {
      command_id: uuid,
      controller_epoch: uuid,
      control_version: integer(0),
    },
    ["command_id", "controller_epoch", "control_version"],
  ),
  resultBase(
    "media.prepared",
    {
      command_id: uuid,
      controller_epoch: uuid,
      turn_id: uuid,
      media_url: privateMediaUrl,
      expires_at: isoTime,
    },
    ["command_id", "controller_epoch", "turn_id", "media_url", "expires_at"],
  ),
  resultBase(
    "command.rejected",
    {
      command_id: uuid,
      code: nonEmpty,
      current_control_version: integer(0),
      recoverable: { type: "boolean" },
    },
    ["command_id", "code", "current_control_version", "recoverable"],
  ),
  resultBase(
    "command.duplicate",
    {
      command_id: uuid,
      code: { type: "string", const: "duplicate_command" },
      current_control_version: integer(0),
    },
    ["command_id", "code", "current_control_version"],
  ),
  resultBase(
    "controller.revoked",
    {
      controller_epoch: uuid,
      reason: {
        type: "string",
        enum: [
          "superseded",
          "disconnected",
          "session_revoked",
          "start_next",
          "debate_terminal",
        ],
      },
    },
    ["controller_epoch", "reason"],
  ),
];

const resultsSchema = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  $id: "https://maya.local/contracts/ws-command-results.v1.schema.json",
  title: "Maya v1 private WebSocket playback command results",
  description:
    "Closed nonpersistent messages sent only to the relevant teacher controller socket; they carry no Debate sequence.",
  oneOf: resultBranches,
};

writeFileSync(
  commandsOutput,
  await format(JSON.stringify(commandsSchema), { parser: "json" }),
);
writeFileSync(
  resultsOutput,
  await format(JSON.stringify(resultsSchema), { parser: "json" }),
);
console.log(`generated ${commandsOutput}`);
console.log(`generated ${resultsOutput}`);
