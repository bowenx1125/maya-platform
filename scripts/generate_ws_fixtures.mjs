import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import { mkdirSync, writeFileSync } from "node:fs";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outputArg = process.argv.indexOf("--output-dir");
const fixtureDir = resolve(
  root,
  outputArg === -1 ? "contracts/fixtures" : process.argv[outputArg + 1],
);
if (outputArg !== -1 && !process.argv[outputArg + 1]) {
  throw new Error("--output-dir requires a fixture directory path");
}
mkdirSync(fixtureDir, { recursive: true });

const debateId = "11111111-1111-4111-8111-111111111111";
const participantA = "22222222-2222-4222-8222-222222222222";
const participantB = "33333333-3333-4333-8333-333333333333";
const turnId = "44444444-4444-4444-8444-444444444444";
const batchId = "55555555-5555-4555-8555-555555555555";
const messageId = "66666666-6666-4666-8666-666666666666";
const revisionId = "77777777-7777-4777-8777-777777777777";
const requestId = "88888888-8888-4888-8888-888888888888";
const windowId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const insightSnapshotId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const occurredAt = "2026-08-26T12:00:00.000Z";
const source = { source_filename: "fixture.md" };
const avatar = (id, slot, motion_state, expression) => ({
  participant_id: id,
  slot,
  motion_state,
  expression,
});
const envelope = (event_type, sequence, payload) => ({
  event_id: `99999999-9999-4999-8999-${String(sequence).padStart(12, "0")}`,
  event_type,
  event_version: 1,
  debate_id: debateId,
  sequence,
  occurred_at: occurredAt,
  payload,
});
const participants = [
  { participant_id: participantA, slot: "A", order_index: 0, name: "Bowen" },
  { participant_id: participantB, slot: "B", order_index: 1, name: "KaiKai" },
];
const playback = {
  status: "preparing",
  mode: "live",
  current_turn_id: null,
  cursor_ms: 0,
  control_version: 0,
  next_turn_ready: false,
};
const report = {
  generation_status: "not_started",
  latest_attempt_status: "not_started",
  insight: {
    status: "not_started",
    included_count: 0,
    filtered_count: 0,
    snapshot_id: null,
    revision: null,
  },
  active_revision_id: null,
  current_success_revision_id: null,
  current_success_word_count: null,
};
const finalStates = {
  debate: "debate_finished",
  playback,
  interaction: "closed",
  insight: "not_started",
  report: "not_started",
};

const valid = [
  envelope("snapshot", 0, {
    debate_status: "running",
    playback_status: "preparing",
    interaction_status: "closed",
    insight_status: "not_started",
    report_status: "not_started",
    public_turns: [],
    playback,
    interaction: {
      status: "closed",
      votes: [],
      barrage_count: 0,
      total_votes: 0,
    },
    report,
    latest_sequence: 0,
  }),
  envelope("snapshot", 0, {
    debate_status: "running",
    playback_status: "preparing",
    interaction_status: "closed",
    insight_status: "not_started",
    report_status: "not_started",
    public_turns: [
      {
        id: turnId,
        participant_id: participantA,
        round_no: 1,
        phase: "opening",
        round_count: 3,
        turn_index: 0,
        speech: "This value judgement remains general reasoning.",
        retrieval_status: "no_match",
        grounding_mode: "general_reasoning",
        sources: [],
        evidence_trace: [
          {
            trace_version: "evidence_trace_v1",
            turn_id: turnId,
            claim_id: "claim-1",
            claim_text: "This value judgement remains general reasoning.",
            claim_type: "value_judgement",
            query_id: null,
            query_kind: null,
            query_text: null,
            evidence_id: null,
            chunk_id: null,
            source_filename: null,
            source_locator: null,
            support_mode: "no_match",
            speech_span: { start_utf16: 0, end_utf16: 47 },
          },
        ],
      },
    ],
    playback,
    interaction: {
      status: "closed",
      votes: [],
      barrage_count: 0,
      total_votes: 0,
    },
    report,
    latest_sequence: 0,
  }),
  envelope("debate.started", 2, {
    rule_set_id: "ordered_multi_expert_mutual_learning_v1",
    participants,
  }),
  envelope("debate.started", 2, {
    rule_set_id: "ordered_multi_expert_mutual_learning_v1",
    round_count: 5,
    participants,
  }),
  envelope("round.started", 3, { round_no: 1, turn_count: 2 }),
  envelope("round.started", 3, {
    round_no: 4,
    phase: "exchange",
    round_count: 5,
    turn_count: 2,
  }),
  envelope("turn.preparing", 4, {
    turn_id: turnId,
    slot: "A",
    round_no: 1,
    stage: "rag",
  }),
  envelope("turn.preparing", 4, {
    turn_id: turnId,
    slot: "A",
    round_no: 5,
    phase: "final_integration",
    round_count: 5,
    stage: "llm",
  }),
  envelope("turn.ready", 5, {
    turn_id: turnId,
    slot: "A",
    round_no: 1,
    audio_ready: true,
    retrieval_status: "matched",
    grounding_mode: "rag_grounded",
  }),
  envelope("turn.audio_ready", 5, { turn_id: turnId }),
  envelope("playback.started", 6, {
    turn_id: turnId,
    slot: "A",
    round_no: 1,
    speech: "Evidence-aware speech is disclosed only when playback begins.",
    sources: [source],
    playback_url:
      "/api/v1/debates/11111111-1111-4111-8111-111111111111/audio/44444444-4444-4444-8444-444444444444",
    avatar_states: [
      avatar(participantA, "A", "speaking", "neutral"),
      avatar(participantB, "B", "listening", "attentive"),
    ],
    cursor_ms: 0,
  }),
  envelope("playback.started", 6, {
    turn_id: turnId,
    slot: "A",
    round_no: 3,
    phase: "exchange",
    round_count: 5,
    speech: "A prior-round claim is now discussed under the round barrier.",
    sources: [],
    playback_url:
      "/api/v1/debates/11111111-1111-4111-8111-111111111111/audio/44444444-4444-4444-8444-444444444444",
    avatar_states: [avatar(participantA, "A", "speaking", "neutral")],
    cursor_ms: 0,
  }),
  envelope("playback.paused", 7, {
    turn_id: turnId,
    cursor_ms: 123,
    control_version: 1,
  }),
  envelope("playback.resumed", 8, {
    turn_id: turnId,
    cursor_ms: 123,
    control_version: 2,
  }),
  envelope("playback.skipped", 9, {
    turn_id: turnId,
    cursor_ms: 800,
    control_version: 3,
  }),
  envelope("playback.waiting_next", 10, {
    completed_turn_id: turnId,
    mode: "live",
    control_version: 4,
    next_turn_ready: true,
  }),
  envelope("playback.completed", 11, {
    turn_id: turnId,
    cursor_ms: 1200,
    control_version: 5,
  }),
  envelope("replay.started", 12, { scope: "turn", turn_id: turnId }),
  envelope("replay.completed", 13, { scope: "turn", turn_id: turnId }),
  envelope("translation.batch_started", 14, {
    batch_id: batchId,
    status: "running",
    total_items: 5,
    succeeded_items: 0,
    failed_items: 0,
  }),
  envelope("translation.batch_completed", 15, {
    batch_id: batchId,
    status: "completed",
    total_items: 5,
    succeeded_items: 5,
    failed_items: 0,
  }),
  envelope("translation.batch_failed", 16, {
    batch_id: batchId,
    status: "failed",
    total_items: 5,
    succeeded_items: 0,
    failed_items: 5,
  }),
  envelope("interaction.opened", 17, {
    window_id: windowId,
    status: "open",
    aggregate_zeros: [
      { participant_id: participantA, count: 0, percentage: 0 },
      { participant_id: participantB, count: 0, percentage: 0 },
    ],
  }),
  envelope("interaction.vote_created", 18, {
    participant_id: participantA,
    new_count: 1,
    percentage: 100,
    total_votes: 1,
  }),
  envelope("interaction.barrage_created", 19, {
    message_id: messageId,
    nickname: "Learner",
    raw_text: "What evidence should we compare?",
    sequence: 1,
  }),
  envelope("interaction.closed", 20, {
    totals: { total_votes: 1, total_barrages: 1 },
    message_count: 1,
    input_hash: "fixture-input-hash",
  }),
  envelope("barrage_insight.started", 21, { revision: 1 }),
  envelope("barrage_insight.completed", 22, {
    snapshot_id: insightSnapshotId,
    revision: 1,
    status: "ready",
    included_count: 1,
    filtered_count: 0,
  }),
  envelope("barrage_insight.failed", 23, {
    revision: 2,
    status: "failed",
    safe_error_code: "barrage_insight_failed",
  }),
  envelope("report.started", 24, {
    revision_id: revisionId,
    status: "generating",
  }),
  envelope("report.completed", 25, {
    revision_id: revisionId,
    revision_no: 1,
    status: "ready",
    current_success_revision_id: revisionId,
    latest_attempt_status: "ready",
    word_count: 640,
  }),
  envelope("report.failed", 26, {
    revision_id: revisionId,
    revision_no: 2,
    status: "failed",
    current_success_revision_id: revisionId,
    latest_attempt_status: "failed",
    safe_error_code: "report_failed",
  }),
  envelope("debate.completed", 27, {
    final_states: finalStates,
    downstream_outcome: "failed",
  }),
  envelope("debate.failed", 28, {
    final_states: { ...finalStates, debate: "failed" },
    downstream_outcome: "failed",
    safe_error_code: "turn_generation_failed",
  }),
  envelope("debate.stopped", 29, {
    final_states: { ...finalStates, debate: "stopped" },
    downstream_outcome: "stopped",
  }),
  envelope("error", 30, {
    code: "invalid_state",
    message: "The command is not valid in this state.",
    request_id: requestId,
    recoverable: true,
  }),
];

const invalid = [
  {
    name: "turn.ready exposes speech",
    event: envelope("turn.ready", 1, {
      turn_id: turnId,
      slot: "A",
      audio_ready: true,
      retrieval_status: "matched",
      speech: "must be hidden",
    }),
  },
  {
    name: "turn.ready exposes sources",
    event: envelope("turn.ready", 1, {
      turn_id: turnId,
      slot: "A",
      audio_ready: true,
      retrieval_status: "matched",
      sources: [source],
    }),
  },
  {
    name: "snapshot watermark mismatch",
    event: envelope("snapshot", 0, {
      debate_status: "draft",
      playback_status: "preparing",
      interaction_status: "closed",
      insight_status: "not_started",
      report_status: "not_started",
      public_turns: [],
      playback,
      interaction: {
        status: "closed",
        votes: [],
        barrage_count: 0,
        total_votes: 0,
      },
      report,
      latest_sequence: 1,
    }),
  },
  {
    name: "snapshot playback state missing derived readiness",
    event: (() => {
      const { next_turn_ready: _derived, ...legacyPlayback } = playback;
      return envelope("snapshot", 0, {
        debate_status: "draft",
        playback_status: "preparing",
        interaction_status: "closed",
        insight_status: "not_started",
        report_status: "not_started",
        public_turns: [],
        playback: legacyPlayback,
        interaction: {
          status: "closed",
          votes: [],
          barrage_count: 0,
          total_votes: 0,
        },
        report,
        latest_sequence: 0,
      });
    })(),
  },
  {
    name: "waiting event missing derived readiness",
    event: envelope("playback.waiting_next", 1, {
      completed_turn_id: turnId,
      mode: "live",
      control_version: 4,
    }),
  },
  {
    name: "waiting event exposes successor identity",
    event: envelope("playback.waiting_next", 1, {
      completed_turn_id: turnId,
      mode: "live",
      control_version: 4,
      next_turn_ready: true,
      next_turn_id: "55555555-5555-4555-8555-555555555555",
    }),
  },
  {
    name: "waiting event missing playback mode",
    event: envelope("playback.waiting_next", 1, {
      completed_turn_id: turnId,
      control_version: 4,
      next_turn_ready: true,
    }),
  },
  {
    name: "provider field is not public",
    event: envelope("playback.started", 1, {
      turn_id: turnId,
      speech: "x",
      sources: [],
      playback_url: "/audio",
      avatar_states: [avatar(participantA, "A", "speaking", "neutral")],
      cursor_ms: 0,
      provider: "supplier",
    }),
  },
  {
    name: "supplier absolute playback url is not public",
    event: envelope("playback.started", 1, {
      turn_id: turnId,
      speech: "x",
      sources: [],
      playback_url: "https://supplier.example/audio?key=secret",
      avatar_states: [avatar(participantA, "A", "speaking", "neutral")],
      cursor_ms: 0,
    }),
  },
  {
    name: "unknown event type",
    event: envelope("turn.unknown", 1, {
      turn_id: turnId,
      slot: "A",
      round_no: 1,
    }),
  },
  {
    name: "unsupported event version",
    event: {
      ...envelope("round.started", 1, { round_no: 1 }),
      event_version: 2,
    },
  },
  {
    name: "missing sequence",
    event: (() => {
      const event = envelope("round.started", 1, { round_no: 1 });
      delete event.sequence;
      return event;
    })(),
  },
  {
    name: "invalid sequence shape",
    event: envelope("round.started", 0, { round_no: 1 }),
  },
  {
    name: "malformed event payload",
    event: envelope("turn.ready", 1, {
      turn_id: turnId,
      slot: "A",
      audio_ready: false,
      retrieval_status: "matched",
    }),
  },
  {
    name: "additional envelope property",
    event: {
      ...envelope("round.started", 1, { round_no: 1 }),
      unexpected: true,
    },
  },
  {
    name: "additional payload property",
    event: envelope("round.started", 1, { round_no: 1, model: "hidden" }),
  },
  {
    name: "api_key field is not public",
    event: envelope("error", 1, {
      code: "provider_unavailable",
      message: "safe",
      request_id: requestId,
      recoverable: true,
      api_key: "hidden",
    }),
  },
  {
    name: "external_voice_id field is not public",
    event: envelope("playback.started", 1, {
      turn_id: turnId,
      speech: "x",
      sources: [],
      playback_url: "/audio",
      avatar_states: [avatar(participantA, "A", "speaking", "neutral")],
      cursor_ms: 0,
      external_voice_id: "hidden",
    }),
  },
];

const textStarted = structuredClone(
  valid.find((event) => event.event_type === "playback.started"),
);
textStarted.payload.playback_url = null;
textStarted.payload.audio_ready = false;
valid.push(textStarted);
const missingTextMarker = structuredClone(textStarted);
delete missingTextMarker.payload.audio_ready;
invalid.push({
  name: "null playback URL requires explicit no-audio marker",
  event: missingTextMarker,
});

const classroomReply = structuredClone(
  valid.find((event) => event.event_type === "playback.started"),
);
classroomReply.payload.segment_turn = {
  schema_version: "segment_turn_v2",
  segments: [
    {
      text: classroomReply.payload.speech,
      source_ids: [],
      reply_to: "B1",
      reply_text: "How should the classroom revise its criterion?",
    },
  ],
};
valid.push(classroomReply);

writeFileSync(
  resolve(fixtureDir, "ws-events.valid.json"),
  `${JSON.stringify(valid, null, 2)}\n`,
  "utf8",
);
writeFileSync(
  resolve(fixtureDir, "ws-events.invalid.json"),
  `${JSON.stringify(invalid, null, 2)}\n`,
  "utf8",
);
console.log(
  `generated ${valid.length} positive and ${invalid.length} negative WebSocket fixtures`,
);
