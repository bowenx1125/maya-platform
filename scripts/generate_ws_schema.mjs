import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { writeFileSync } from "node:fs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outputArg = process.argv.indexOf("--output");
const output = resolve(
  root,
  outputArg === -1
    ? "contracts/ws-events.v1.schema.json"
    : process.argv[outputArg + 1],
);
if (outputArg !== -1 && !process.argv[outputArg + 1]) {
  throw new Error("--output requires a schema file path");
}

const uuid = { type: "string", format: "uuid" };
const nullableUuid = { anyOf: [uuid, { type: "null" }] };
const isoTime = { type: "string", format: "date-time" };
const slot = { type: "string", enum: ["A", "B", "C", "D", "E"] };
const nonEmpty = { type: "string", minLength: 1 };
const publicMediaPath = {
  type: "string",
  pattern:
    "^/api/v1/debates/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}/audio/[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-5][0-9a-fA-F]{3}-[89aAbB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}$",
};
const integer = (minimum = 0, maximum) => ({
  type: "integer",
  minimum,
  ...(maximum === undefined ? {} : { maximum }),
});
const number = (minimum = 0, maximum) => ({
  type: "number",
  minimum,
  ...(maximum === undefined ? {} : { maximum }),
});
const arrayOf = (items, minItems = 0) => ({ type: "array", items, minItems });
const closed = (properties, required = []) => ({
  type: "object",
  required,
  properties,
  additionalProperties: false,
});
const nullable = (schema) => ({ anyOf: [schema, { type: "null" }] });
const segmentTurn = closed(
  {
    schema_version: { type: "string", const: "segment_turn_v2" },
    segments: arrayOf(
      closed(
        {
          text: { type: "string" },
          source_ids: arrayOf({ type: "string" }),
          reply_to: nullable({ type: "string" }),
        },
        ["text", "source_ids", "reply_to"],
      ),
    ),
  },
  ["segments"],
);
const segmentSource = closed(
  {
    source_id: { type: "string" },
    source_filename: { type: "string" },
    excerpt: { type: "string" },
    query_text: nullable({ type: "string" }),
    version_label: { type: "string" },
  },
  ["source_id", "source_filename", "excerpt", "version_label"],
);
const roundPhase = {
  type: "string",
  enum: ["opening", "exchange", "final_integration", "rebuttal"],
};
const roundCount = integer(2, 5);

const retrievalSource = closed({ source_filename: nonEmpty, chunk_id: uuid }, [
  "source_filename",
]);
const evidenceTrace = closed(
  {
    trace_version: { type: "string", const: "evidence_trace_v1" },
    turn_id: nonEmpty,
    claim_id: nonEmpty,
    claim_text: nonEmpty,
    claim_type: {
      type: "string",
      enum: ["factual", "background", "value_judgement", "proposal"],
    },
    query_id: nullable(nonEmpty),
    query_kind: nullable({
      type: "string",
      enum: [
        "viewpoint",
        "pending_question",
        "rebuttal",
        "updated_position",
        "context",
      ],
    }),
    query_text: nullable({ type: "string" }),
    evidence_id: nullable(nonEmpty),
    chunk_id: nullable(nonEmpty),
    source_filename: nullable(nonEmpty),
    source_locator: nullable(nonEmpty),
    support_mode: {
      type: "string",
      enum: ["direct", "contextual", "general_reasoning", "no_match"],
    },
    speech_span: closed({ start_utf16: integer(0), end_utf16: integer(0) }, [
      "start_utf16",
      "end_utf16",
    ]),
  },
  [
    "turn_id",
    "claim_id",
    "claim_text",
    "claim_type",
    "support_mode",
    "speech_span",
  ],
);
const publicTurn = closed(
  {
    id: uuid,
    participant_id: uuid,
    round_no: integer(1),
    phase: nullable(roundPhase),
    round_count: nullable(roundCount),
    turn_index: integer(0),
    speech: nonEmpty,
    retrieval_status: { type: "string", enum: ["matched", "no_match"] },
    grounding_mode: {
      type: "string",
      enum: ["rag_grounded", "mixed", "general_reasoning"],
    },
    sources: arrayOf(retrievalSource),
    evidence_trace: nullable(arrayOf(evidenceTrace)),
    segment_turn: nullable(segmentTurn),
    source_details: arrayOf(segmentSource),
    audio_ready: nullable({ type: "boolean" }),
  },
  [
    "id",
    "participant_id",
    "round_no",
    "turn_index",
    "speech",
    "retrieval_status",
    "grounding_mode",
    "sources",
  ],
);
const participantSlot = closed(
  {
    participant_id: uuid,
    slot,
    order_index: integer(0, 4),
    name: nonEmpty,
  },
  ["participant_id", "slot"],
);
const avatarState = closed(
  {
    participant_id: uuid,
    slot,
    motion_state: {
      type: "string",
      enum: ["idle", "listening", "speaking", "thinking", "nod_yes"],
    },
    expression: {
      type: "string",
      enum: ["neutral", "attentive", "happy", "serious_angry", "sad"],
    },
    expression_strength: { type: "string", enum: ["low", "medium", "high"] },
  },
  ["participant_id", "slot", "motion_state", "expression"],
);
const playbackState = closed(
  {
    status: {
      type: "string",
      enum: [
        "preparing",
        "ready",
        "playing",
        "paused",
        "waiting_next",
        "completed",
        "stopped",
      ],
    },
    mode: { type: "string", enum: ["live", "replay"] },
    current_turn_id: nullableUuid,
    cursor_ms: integer(0),
    playback_rate: number(0.95, 1.25),
    control_version: integer(0),
    next_turn_ready: { type: "boolean" },
  },
  [
    "status",
    "mode",
    "current_turn_id",
    "cursor_ms",
    "playback_rate",
    "control_version",
    "next_turn_ready",
  ],
);
const voteAggregate = closed(
  { participant_id: uuid, count: integer(0), percentage: number(0, 100) },
  ["participant_id", "count", "percentage"],
);
const interactionSummary = closed(
  {
    status: { type: "string", enum: ["closed", "open", "finalized"] },
    votes: arrayOf(voteAggregate),
    barrage_count: integer(0),
    total_votes: integer(0),
  },
  ["status", "votes", "barrage_count", "total_votes"],
);
const insightSummary = closed(
  {
    status: {
      type: "string",
      enum: ["not_started", "generating", "ready", "failed"],
    },
    included_count: integer(0),
    filtered_count: integer(0),
    snapshot_id: nullableUuid,
    revision: nullable(integer(1)),
  },
  ["status", "included_count", "filtered_count", "snapshot_id", "revision"],
);
const reportSummary = closed(
  {
    generation_status: {
      type: "string",
      enum: ["not_started", "generating", "ready", "failed"],
    },
    latest_attempt_status: {
      type: "string",
      enum: ["not_started", "generating", "ready", "failed"],
    },
    insight: insightSummary,
    active_revision_id: nullableUuid,
    current_success_revision_id: nullableUuid,
    current_success_word_count: nullable(integer(600, 900)),
  },
  [
    "generation_status",
    "latest_attempt_status",
    "insight",
    "active_revision_id",
    "current_success_revision_id",
    "current_success_word_count",
  ],
);
const finalStates = closed(
  {
    debate: {
      type: "string",
      enum: ["debate_finished", "completed", "failed", "stopped"],
    },
    playback: playbackState,
    interaction: { type: "string", enum: ["closed", "open", "finalized"] },
    insight: {
      type: "string",
      enum: ["not_started", "generating", "ready", "failed"],
    },
    report: {
      type: "string",
      enum: ["not_started", "generating", "ready", "failed"],
    },
  },
  ["debate"],
);

const statuses = {
  debate: {
    type: "string",
    enum: [
      "draft",
      "running",
      "debate_finished",
      "completed",
      "failed",
      "stopped",
    ],
  },
  playback: {
    type: "string",
    enum: [
      "preparing",
      "ready",
      "playing",
      "paused",
      "waiting_next",
      "completed",
      "stopped",
    ],
  },
  interaction: { type: "string", enum: ["closed", "open", "finalized"] },
  insight: {
    type: "string",
    enum: ["not_started", "generating", "ready", "failed"],
  },
  report: {
    type: "string",
    enum: ["not_started", "generating", "ready", "failed"],
  },
};

const payloads = {
  snapshot: closed(
    {
      debate_status: statuses.debate,
      playback_status: statuses.playback,
      interaction_status: statuses.interaction,
      insight_status: statuses.insight,
      report_status: statuses.report,
      final_input_frozen: { type: "boolean" },
      public_turns: arrayOf(publicTurn),
      playback: playbackState,
      interaction: interactionSummary,
      report: reportSummary,
      latest_sequence: integer(0),
    },
    [
      "debate_status",
      "playback_status",
      "interaction_status",
      "insight_status",
      "report_status",
      "public_turns",
      "playback",
      "interaction",
      "report",
      "latest_sequence",
    ],
  ),
  "debate.started": (() => {
    const payload = closed(
      {
        rule_set_id: {
          type: "string",
          enum: [
            "ordered_multi_agent_rounds_demo_v1",
            "ordered_multi_agent_rounds_demo_v2",
            "ordered_multi_expert_mutual_learning_v1",
          ],
        },
        round_count: nullable(roundCount),
        participants: arrayOf(participantSlot, 2),
        participant_slots: arrayOf(participantSlot, 2),
      },
      ["rule_set_id"],
    );
    payload.anyOf = [
      { required: ["participants"], properties: { participants: {} } },
      {
        required: ["participant_slots"],
        properties: { participant_slots: {} },
      },
    ];
    return payload;
  })(),
  "round.started": closed(
    {
      round_no: integer(1),
      phase: nullable(roundPhase),
      round_count: nullable(roundCount),
      turn_count: integer(1),
    },
    ["round_no"],
  ),
  "turn.preparing": closed(
    {
      turn_id: uuid,
      slot,
      round_no: integer(1),
      phase: nullable(roundPhase),
      round_count: nullable(roundCount),
      stage: { type: "string", enum: ["rag", "llm", "tts"] },
    },
    ["turn_id", "slot", "round_no"],
  ),
  "turn.ready": closed(
    {
      turn_id: uuid,
      slot,
      round_no: integer(1),
      phase: nullable(roundPhase),
      round_count: nullable(roundCount),
      audio_ready: { type: "boolean", const: true },
      retrieval_status: { type: "string", enum: ["matched", "no_match"] },
      grounding_mode: {
        type: "string",
        enum: ["rag_grounded", "mixed", "general_reasoning"],
      },
      audio_duration_ms: integer(0),
    },
    ["turn_id", "slot", "audio_ready", "retrieval_status"],
  ),
  "playback.started": closed(
    {
      turn_id: uuid,
      slot,
      round_no: integer(1),
      phase: nullable(roundPhase),
      round_count: nullable(roundCount),
      speech: nonEmpty,
      sources: arrayOf(retrievalSource),
      evidence_trace: nullable(arrayOf(evidenceTrace)),
      segment_turn: nullable(segmentTurn),
      source_details: arrayOf(segmentSource),
      audio_ready: nullable({ type: "boolean" }),
      playback_url: publicMediaPath,
      avatar_states: arrayOf(avatarState, 1),
      cursor_ms: { type: "integer", const: 0 },
      playback_rate: number(0.95, 1.25),
    },
    [
      "turn_id",
      "speech",
      "sources",
      "playback_url",
      "avatar_states",
      "cursor_ms",
    ],
  ),
  "playback.paused": closed(
    {
      turn_id: uuid,
      cursor_ms: integer(0),
      control_version: integer(0),
      playback_rate: number(0.95, 1.25),
    },
    ["turn_id", "cursor_ms", "control_version"],
  ),
  "playback.resumed": closed(
    {
      turn_id: uuid,
      cursor_ms: integer(0),
      control_version: integer(0),
      playback_rate: number(0.95, 1.25),
    },
    ["turn_id", "cursor_ms", "control_version"],
  ),
  "playback.skipped": closed(
    {
      turn_id: uuid,
      cursor_ms: integer(0),
      control_version: integer(0),
      playback_rate: number(0.95, 1.25),
    },
    ["turn_id", "cursor_ms", "control_version"],
  ),
  "playback.waiting_next": closed(
    {
      completed_turn_id: uuid,
      mode: { type: "string", enum: ["live", "replay"] },
      control_version: integer(0),
      next_turn_ready: { type: "boolean" },
    },
    ["completed_turn_id", "mode", "control_version", "next_turn_ready"],
  ),
  "playback.completed": closed(
    {
      turn_id: uuid,
      cursor_ms: integer(0),
      control_version: integer(0),
      playback_rate: number(0.95, 1.25),
    },
    ["turn_id", "cursor_ms", "control_version"],
  ),
  "replay.started": closed(
    {
      scope: { type: "string", enum: ["turn", "all"] },
      turn_id: nullableUuid,
      control_version: integer(0),
    },
    ["scope", "turn_id"],
  ),
  "replay.completed": closed(
    {
      scope: { type: "string", enum: ["turn", "all"] },
      turn_id: nullableUuid,
      control_version: integer(0),
    },
    ["scope", "turn_id"],
  ),
};

const translationCounts = {
  batch_id: uuid,
  total_items: integer(0),
  succeeded_items: integer(0),
  failed_items: integer(0),
};
payloads["translation.batch_started"] = closed(
  { ...translationCounts, status: { type: "string", const: "running" } },
  ["batch_id", "status", "total_items", "succeeded_items", "failed_items"],
);
payloads["translation.batch_completed"] = closed(
  {
    ...translationCounts,
    status: { type: "string", enum: ["completed", "partial"] },
  },
  ["batch_id", "status", "total_items", "succeeded_items", "failed_items"],
);
payloads["translation.batch_failed"] = closed(
  { ...translationCounts, status: { type: "string", const: "failed" } },
  ["batch_id", "status", "total_items", "succeeded_items", "failed_items"],
);

payloads["interaction.opened"] = closed(
  {
    window_id: uuid,
    aggregate_zeros: arrayOf(voteAggregate),
    status: { type: "string", const: "open" },
  },
  ["window_id", "aggregate_zeros", "status"],
);
payloads["interaction.vote_created"] = closed(
  {
    participant_id: uuid,
    slot,
    new_count: integer(0),
    percentage: number(0, 100),
    total_votes: integer(0),
  },
  ["participant_id", "new_count", "percentage", "total_votes"],
);
payloads["interaction.barrage_created"] = closed(
  {
    message_id: uuid,
    nickname: nonEmpty,
    raw_text: nonEmpty,
    sequence: integer(1),
  },
  ["message_id", "nickname", "raw_text", "sequence"],
);
payloads["interaction.closed"] = closed(
  {
    totals: closed({ total_votes: integer(0), total_barrages: integer(0) }, [
      "total_votes",
      "total_barrages",
    ]),
    message_count: integer(0),
    input_hash: nonEmpty,
  },
  ["totals", "message_count", "input_hash"],
);

payloads["barrage_insight.started"] = closed(
  { revision: integer(1), status: { type: "string", const: "generating" } },
  ["revision"],
);
payloads["barrage_insight.completed"] = closed(
  {
    snapshot_id: uuid,
    revision: integer(1),
    status: { type: "string", const: "ready" },
    included_count: integer(0),
    filtered_count: integer(0),
  },
  ["snapshot_id", "revision", "status", "included_count", "filtered_count"],
);
payloads["barrage_insight.failed"] = closed(
  {
    revision: integer(1),
    status: { type: "string", const: "failed" },
    included_count: integer(0),
    filtered_count: integer(0),
    safe_error_code: nonEmpty,
  },
  ["revision", "status", "safe_error_code"],
);

payloads["report.started"] = closed(
  { revision_id: uuid, status: { type: "string", const: "generating" } },
  ["revision_id", "status"],
);
payloads["report.completed"] = closed(
  {
    revision_id: uuid,
    revision_no: integer(1),
    status: { type: "string", const: "ready" },
    current_success_revision_id: uuid,
    latest_attempt_status: { type: "string", const: "ready" },
    word_count: integer(600, 900),
  },
  [
    "revision_id",
    "revision_no",
    "status",
    "current_success_revision_id",
    "latest_attempt_status",
    "word_count",
  ],
);
payloads["report.failed"] = closed(
  {
    revision_id: uuid,
    revision_no: integer(1),
    status: { type: "string", const: "failed" },
    current_success_revision_id: nullableUuid,
    latest_attempt_status: { type: "string", const: "failed" },
    safe_error_code: nonEmpty,
  },
  [
    "revision_id",
    "revision_no",
    "status",
    "current_success_revision_id",
    "latest_attempt_status",
    "safe_error_code",
  ],
);

payloads["debate.completed"] = closed(
  {
    final_states: finalStates,
    downstream_outcome: {
      type: "string",
      enum: ["not_started", "ready", "failed", "completed"],
    },
    safe_error_code: nullable({ type: "string" }),
  },
  ["final_states", "downstream_outcome"],
);
payloads["debate.failed"] = closed(
  {
    final_states: finalStates,
    downstream_outcome: { type: "string", enum: ["failed", "stopped"] },
    safe_error_code: nonEmpty,
  },
  ["final_states", "downstream_outcome", "safe_error_code"],
);
payloads["debate.stopped"] = closed(
  {
    final_states: finalStates,
    downstream_outcome: { type: "string", const: "stopped" },
    safe_error_code: nullable({ type: "string" }),
  },
  ["final_states", "downstream_outcome"],
);

payloads.error = closed(
  {
    code: nonEmpty,
    message: nonEmpty,
    details: closed({
      current_revision: integer(0),
      current_control_version: integer(0),
      reason: { type: "string" },
    }),
    request_id: uuid,
    recoverable: { type: "boolean" },
  },
  ["code", "message", "request_id", "recoverable"],
);

const eventTypes = [
  "snapshot",
  "debate.started",
  "round.started",
  "turn.preparing",
  "turn.ready",
  "playback.started",
  "playback.paused",
  "playback.resumed",
  "playback.skipped",
  "playback.waiting_next",
  "playback.completed",
  "replay.started",
  "replay.completed",
  "translation.batch_started",
  "translation.batch_completed",
  "translation.batch_failed",
  "interaction.opened",
  "interaction.vote_created",
  "interaction.barrage_created",
  "interaction.closed",
  "barrage_insight.started",
  "barrage_insight.completed",
  "barrage_insight.failed",
  "report.started",
  "report.completed",
  "report.failed",
  "debate.completed",
  "debate.failed",
  "debate.stopped",
  "error",
];

const slug = (eventType) => eventType.replace(/[^a-zA-Z0-9]+/g, "_");
const eventBranch = (eventType) => ({
  type: "object",
  required: [
    "event_id",
    "event_type",
    "event_version",
    "debate_id",
    "sequence",
    "occurred_at",
    "payload",
  ],
  properties: {
    event_id: uuid,
    event_type: { type: "string", const: eventType },
    event_version: { type: "integer", const: 1 },
    debate_id: uuid,
    sequence: integer(eventType === "snapshot" ? 0 : 1),
    occurred_at: isoTime,
    payload: { $ref: `#/$defs/payload_${slug(eventType)}` },
  },
  additionalProperties: false,
});

const schema = {
  $schema: "https://json-schema.org/draft/2020-12/schema",
  $id: "https://maya.local/contracts/ws-events.v1.schema.json",
  title: "Maya v1 WebSocket events",
  description:
    "Closed, versioned platform event union. Prepared turn text is intentionally absent from turn.ready.",
  oneOf: eventTypes.map(eventBranch),
  $defs: {
    uuid,
    iso_time: isoTime,
    ...Object.fromEntries(
      eventTypes.map((eventType) => [
        `payload_${slug(eventType)}`,
        payloads[eventType],
      ]),
    ),
  },
};

writeFileSync(output, `${JSON.stringify(schema, null, 2)}\n`, "utf8");
console.log(`generated ${output}`);
