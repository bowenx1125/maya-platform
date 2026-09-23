# Debate generation contracts

The frozen behaviour of the real Debate path: what a Persona is, what may leave
the machine, how a turn is generated and validated, and what every provider
call must record. These are settled decisions, not proposals.

The machine-readable schemas live in `contracts/` beside the frozen OpenAPI —
`llm-turn-output.v1.schema.json` (the strict provider-output schema, hash-pinned
by `LLM_TURN_OUTPUT_SCHEMA_HASH`) and `llm-repair-feedback.v1.schema.json` (the
only server-authored repair grammar). This file explains them; it is not loaded
by any code.

Section names below replace the former one-file-per-topic layout; the old
`*_V1.md` names appear in commit history only.

---

## Settled decisions

Status: `FROZEN / REAL EMBEDDING 1024 DELTA`

1. **Why write AGENT.md?** It is student authorship compiled into a confirmed Persona
   that visibly controls six expression/argument dimensions.
2. **What may Persona change?** Tone, value priority, argument pattern, concession
   style, question style and debate strategy.
3. **What may Persona never change?** Facts/source bytes, evidence IDs, platform rules,
   permissions, schedule/state machine, language, safety validation or output schema.
4. **How is raw AGENT.md compiled/confirmed/versioned/downloaded?** By the strict local
   PersonaSpecV1 grammar and CAS state machine; raw and canonical hashes remain on the
   immutable AgentVersion and raw remains downloadable. All new Mock and real W4
   debates require confirmed Persona; legacy output is read/replay-only.
5. **How does each RAG source map to a claim?** Server query/receipt IDs and exact
   speech spans form immutable EvidenceTraceV1 rows; only used receipts are public.
6. **How is no-match explained?** “No relevant evidence found; this claim is general
   reasoning; no source is attached.”
7. **Which factual claims require evidence?** Every concrete quantity or explicit
   attribution to an expert, study, survey or report requires direct evidence; the
   existing server detector is the minimum enforcement set.
8. **Maximum input per turn?** 32,000 model tokens; output request 1,500 tokens.
9. **Maximum Provider calls per debate?** 20 Debate LLM calls for 5 Agents × 2 rounds;
   LLM-B and TTS have separate non-transferable caps.
10. **When may attempt 2 retrieve again?** Only after retrieval technical failure
    before any LLM request. Structural repair reuses the frozen receipt set.
11. **What is sent externally?** The exact allowlist in ProviderDataCallV1: structured
    current Persona, topic/rules, complete RuleSet-visible prior speeches (all earlier
    rounds for mutual learning, never same-round), current queries and evidence
    excerpts, opaque IDs and current TTS speech where applicable. The teacher
    sees the supplier, Beijing region, purpose, storage fact and no-training basis
    before confirming the exact export manifest.
12. **Are student names, nicknames, audio or identity sent?** No. Voice enrollment is
    a separate TTS Gate using one approved sample and is not an LLM/Embedding input.
13. **Model versions?** Chat, debate and report use `LLM_MODEL`
    (default `qwen3.8-max-2026-09-02`). Embedding stays `text-embedding-v4` at 1024
    dimensions and `qwen3-tts-vc-2026-01-22`; no `latest` fallback.
14. **Maximum charge?** CNY 0.15/request and CNY 3.00 per full Debate LLM run; other
    operation caps are the table in ProviderDataCallV1. Embedding additionally limits
    each item to 8,000 counted tokens and each ten-item request to 30,000.
15. **How do budget/timeout/shape/uncertain failures close?** Pre-send violations make
    zero calls; a durable atomic reservation precedes network I/O; repair uses one
    frozen retry; acceptance-unknown consumes the cap and is never retried or
    published; safe codes hide supplier details.
    W4-LLM-A uses an independent `llm_debate_turn` budget bucket, an immutable accepted
    stage and one atomic Turn/Evidence/usage/operation publication transaction as frozen
    in `LLM_A_RUNTIME_V1.md`.
16. **Which Gates are fully Mock-completable?** W4-PERSONA, W4-RAG-TRACE, W4-PROMPT and
    W4-CONTENT. Their G1/G2/G3 must finish before real Provider evidence.
17. **When does billed work begin?** Two isolated account preflight calls already
    occurred: one 256-dimension Embedding request and one structured LLM request, both
    with non-student fixtures while Maya's selectors stayed Mock. They are availability
    evidence only and are not Gate evidence. The separately authorized W4-EMBED 1024
    preflight later used exactly one safe three-text request; HTTP was 200 but local
    response parsing failed closed, so its status is `REAL EMBEDDING 1024 PREFLIGHT
FAILED` and it must not be repeated under the current Gate. The account must be a verified
    pay-as-you-go API or Token Plan Team account with an accepted
    ProviderPolicySnapshot; personal/Coding/unknown plans stop at zero calls. The
    user's standing authorization removes a repeated per-call confirmation, but no
    Gate or cap. A 256, 1024 or LLM preflight must not be repeated.

---

## Persona

Status: `FROZEN / PERSONA MOCK GATE PASS / SOL G2 PASS / REAL CALLS 0`

### Teaching contract

Students write `AGENT.md` because its confirmed structured meaning must cause visible,
explainable changes in tone, value priority, argument pattern, concession style,
question style and debate strategy. Persona must never change platform rules, debate
order, permissions, evidence identity, factual source bytes, output schema or safety
validation.

The raw Markdown is immutable authorship and remains available for preview, download,
teacher review and version comparison. A real LLM receives only the confirmed
structured provider view, never raw `AGENT.md`.

### Strict Markdown grammar

The deterministic compiler accepts UTF-8 Markdown no longer than 12,000 characters
after CRLF normalization. The only accepted document shape is:

```markdown
## <Agent display name>

### Identity

- Role: <text>
- Historical or cultural context: <text>

### Cultural lens

- <item>

### Core values

- <item>

### Initial position

<one or more paragraphs>

### Speaking style

- Tone: <text>
- Argument pattern: <text>
- Concession style: <text>
- Question style: <text>

### Debate strategy

- <item>

### Boundaries

- <item>
```

Rules are exact after trimming surrounding whitespace:

- one H1 is required and must equal the Agent display name;
- all seven H2 sections are required exactly once and in the shown order;
- field labels are ASCII and case-sensitive;
- Cultural lens, Core values, Debate strategy and Boundaries contain only flat bullet
  items; each list contains at least one unique item;
- Identity and Speaking style contain only their named flat bullet fields;
- Initial position contains plain Markdown paragraphs but no headings, HTML or links;
- prose outside the defined locations, unknown/duplicate headings, unknown fields,
  nested lists, HTML, links and empty values are compile errors, not ignored content;
- Markdown emphasis and inline code are reduced to their visible text. Their delimiters
  never become instructions.

The September 8 owner revision removes per-field character and list-count caps.
All authored fields share the 12,000-character Markdown limit, including headings,
spaces and punctuation after newline normalization. Compiler, stored/provider
schemas and paragraph-input conversion use this same policy. Nonempty values and
section structure remain required. Control and format characters other than
normalized newline/tab are rejected.

### Closed stored schema

```json
{
  "schema_version": "persona_spec_v1",
  "identity": {
    "name": "",
    "role": "",
    "historical_or_cultural_context": ""
  },
  "cultural_lens": [],
  "core_values": [],
  "initial_position": "",
  "speaking_style": {
    "tone": "",
    "argument_pattern": "",
    "concession_style": "",
    "question_style": ""
  },
  "debate_strategy": [],
  "boundaries": [],
  "source_agent_md_hash": "sha256:<hex>",
  "compiler_version": "persona_template_v1"
}
```

Each AgentVersion stores `raw_agent_md`, `raw_agent_md_hash`, canonical
`persona_spec_json`, `persona_spec_hash`, `persona_compiler_version`,
`persona_confirmation_revision`, `student_confirmed_at` and the internal confirming
user ID. `raw_agent_md` is the contract name for the existing authoritative
`AgentVersion.agent_md` value; implementation must not create a second raw text copy.
Hashes cover normalized UTF-8 bytes or canonical JSON encoded with sorted keys,
UTF-8 characters and no insignificant whitespace. The confirming user ID is never sent
to a Provider or browser DTO outside existing authorized membership views.

The server-only `persona_required` activation marker is not a browser or Provider
field. Migration 0012 leaves immutable published/superseded legacy rows false, marks
every still-mutable draft true and every product draft-creation path writes true.
Eligibility never infers activation from raw Markdown shape.

### Compile and confirmation state machine

`uncompiled -> compiled_unconfirmed -> confirmed`

- changing raw Markdown clears the compiled/confirmed result in the same draft
  transaction;
- compile is local and deterministic; external calls are forbidden;
- compile failure stores safe diagnostics but cannot retain a prior Persona as active;
- confirmation requires an authenticated current member of the Agent's group and an
  exact draft revision, raw hash, Persona hash and compiler version CAS;
- any intervening edit makes confirmation stale;
- publication requires `confirmed`; published raw and structured values are immutable;
- publication or a knowledge-only draft revision that leaves raw/spec bytes unchanged
  atomically advances `persona_confirmation_revision` with the AgentVersion revision;
  hashes, confirmation time and confirmer remain unchanged, and a failed CAS cannot
  half-update either state;
- legacy published AgentVersions are not backfilled or rewritten;
- after PersonaSpecV1 activation, every new debate requires every selected published
  AgentVersion to have a confirmed Persona, regardless of Mock or real Provider. Setup
  availability and start both reject a legacy selection with the stable safe code
  `persona_confirmation_required` and the authorized AgentVersion IDs;
- there is no default Persona, raw-`AGENT.md` generation fallback or Mock-only legacy
  path. A legacy version must be cloned, compiled, confirmed and republished, then used
  in a new debate;
- completed legacy debates remain readable, downloadable and replayable from their
  frozen outputs. An incomplete legacy debate may be stopped, but generation/resume is
  rejected with `persona_confirmation_required`; it cannot be silently upgraded in
  place.

### Provider view and causal acceptance

`persona_provider_view_v1` contains the seven semantic fields once, with no audit
hashes, confirmation identity or raw Markdown. The whole view is sent once per turn;
there is no second `agent_md` field.

Before an external LLM call, the Persona hash is also part of the exact teacher-signed
export manifest in ProviderDataCallV1. Its identity name is a fictional/cultural Agent
name, not a student name; personal identity in any Persona field blocks export.

Mock acceptance uses two deliberately contrasting Persona fixtures under the same
topic, stance, receipts, rules and deterministic seed. Tests must show differences in
all six allowed teaching dimensions and equality of evidence IDs, source set, order,
rules and schema. The UI compares raw versions, canonical structured differences and a
same-input Mock response pair, and labels which dimensions can and cannot change.

The deterministic Mock projects each allowed dimension as a bounded complete sentence;
it does not echo arbitrarily long legal fields verbatim. Contract-limit Persona,
identity, pending-question and evidence combinations must produce every phase within
80–190 counted words, preserve all six explainable dimensions and retain exact non-empty
EvidenceTrace. No service-layer output truncation is permitted.

The playback generation adapter rechecks every frozen participant's exact confirmed
Persona before retrieval or any Mock/real Provider call, regardless of RuleSet. A
migration-era incomplete run with an unconfirmed participant fails with
`persona_confirmation_required` and the authorized version IDs; Provider call count is
zero. Stop and completed historical read/download/Replay remain unchanged.

Long teaching dimensions project meaningful head, middle and tail authored words so a
middle-only difference remains visible without hashes or internal codes. Before any
authored phrase enters Mock speech, the projection applies the same public
source-attribution predicate as EvidenceTrace validation. Attribution, written/Arabic
quantity, URL, filename and source-shaped values become a natural
"student-authored perspective" meta sentence rather than a factual claim. Six
dimensions × three phases have pairwise-causality and source-pattern strict tests.

### Frozen Persona Mock Gate

The user froze this Gate as PASS when all seven conditions hold:

1. `AGENT.md -> PersonaSpecV1` is deterministic and stable;
2. the six core teaching dimensions are visible to the student;
3. the student must confirm the compiled Persona;
4. confirmation freezes the correct raw/spec hashes, version and compiler binding;
5. an unconfirmed Persona cannot enter any new Debate or Provider path;
6. clearly different Persona projections produce clearly different actual Mock behavior;
7. Persona cannot fabricate Evidence or leak raw/private text.

The current implementation and local acceptance matrix satisfy all seven. The Gate
does not promise that every arbitrary word-level edit inside a bounded free-text field
must produce a unique speech. If two edits have the same effective Mock projection,
that is not a Gate failure. Further uniqueness/sampling optimization is explicitly out
of scope after this PASS.

---

## Formal content

Status: `CONTENT V1 FROZEN / MOCK ACCEPTANCE PASS / REAL EMBEDDING NOT STARTED`

W4-CONTENT is Mock-only and precedes real embedding. It creates the actual TikTok
teaching corpus; W4-G0 does not pretend that placeholder or historical fixture text is
formal content.

The content packet must contain:

- one bounded English Markdown teaching document about TikTok recommendation-system
  governance, youth protection, expression, innovation and cross-cultural trade-offs;
- a source manifest with title, publisher/author, publication date, direct URL,
  access date, license/usage basis and the exact claims each source informs;
- primary/authoritative sources for law, policy, platform disclosures and quantitative
  claims; secondary commentary is labeled as interpretation;
- explicit fact/value separation and date scope;
- at least one relevant retrieval fixture, one adjacent-but-insufficient fixture and
  one clearly unrelated no-match fixture;
- content and manifest SHA-256 values plus the exact chunking version;
- no student identity, nickname, credential, private account data, audio or copyrighted
  full-text copying beyond permissible short excerpts and original synthesis.

Acceptance requires source-link review, claim/source spot checks, relevant/no-match
Mock retrieval, two contrasting Persona Mock turns over the same evidence and a
main-window teaching review. Content remains editable until that Gate signs its hashes;
real embedding cannot run earlier.

### Frozen content evidence

The seeded Demo Agents under `backend/app/modules/demo_baseline/agents/` are the current authored corpus; the earlier standalone review packet was removed once they replaced it.

- corpus SHA-256: `7fab29d2bddc241ea2021284f2766e6e6cecb705b9a56ff041838c1fe606c24a`;
- source-manifest SHA-256: `9193e384a0c29bf51274055b4cd3a6273fc6276ad14113db4b8398a335648ce5`;
- 14 claim markers map to 7 primary/authoritative sources;
- relevant fixture: matched; adjacent and unrelated fixtures: no-match with no source;
- two contrasting Persona fixtures use the same receipt while changing only their
  declared teaching priorities;
- checksum, JSON, secret/PII pattern, actual Mock lexical/vector and pytest acceptance:
  PASS;
- main-window teaching review: PASS, with first-party TikTok pages retained as labeled
  platform statements rather than independent audits;
- Provider/model calls: `0`.

Any content or manifest edit invalidates this status and requires new hashes and the
same acceptance sequence before a new real SnapshotBuild.

---

## Embedding identity

Status: `FROZEN / REAL DIMENSION 1024 / IMPLEMENTATION IN PROGRESS`

### Closed identities

Maya has exactly two allowed Embedding identities:

| Purpose                       | Provider    | Model               | Region       | Dimension | Policy version |
| ----------------------------- | ----------- | ------------------- | ------------ | --------: | -------------- |
| deterministic Mock/CI/history | `mock`      | `mock-sha256-v1`    | `local`      |       256 | `w4-mock-v1`   |
| formal real RAG               | `dashscope` | `text-embedding-v4` | `cn-beijing` |      1024 | `w4-embed-v1`  |

Model name or vector length alone never establishes compatibility. SnapshotBuild,
frozen Provider request, sanitized accepted stage, KnowledgeSnapshot, every vector row
and query embedding must agree on all five identity fields.

### Request and response

Every real provider-visible request contains exactly:

- fixed model `text-embedding-v4`;
- ordered input text array from the exact export manifest;
- `parameters.dimension = 1024`.

The API key is a transport header only. Endpoint and workspace are server configuration
only. None of them enters the request payload, browser DTO, log or persisted raw
response.

The validator requires one output per input in the original order, exactly 1024 finite
numeric values per vector and the fixed model identity. It rejects missing/malformed
items, count/order drift, 256/768/1023/1025 or any other dimension, booleans/non-numbers,
NaN and infinity. Padding, truncation, conversion and server-side repair are forbidden.

### Persistence and history

Existing Mock snapshots remain immutable at `mock/mock-sha256-v1/local/256/w4-mock-v1`.
Migration may add explicit identity columns but must not change their IDs, source bytes,
vector blobs, AgentVersion pointers or historical Debates. It must never backfill a
real identity or real vector.

A real publication creates a new immutable Snapshot and stores the real identity at the
Snapshot boundary. Vector serialization uses the validated trusted Snapshot dimension:
`struct.pack(f"<{dimension}f", ...)`; deserialization first validates blob length and
then uses the same dimension. Browser input and supplier response metadata are not
trusted identity sources.

Accepted response staging persists only local operation/build/chunk identities,
validated vectors, model/dimension/policy version and a response hash. Raw supplier
JSON and credentials are forbidden. Restart either resumes local publication from a
complete accepted stage or fails closed without a second request.

### Query compatibility

Before scoring, the query embedding identity must equal the selected Snapshot identity
on provider, model, region, dimension and policy version. The following all fail closed:

- Mock 256 query against real 1024 Snapshot;
- real 1024 query against Mock 256 Snapshot;
- same dimension but different provider/model/policy;
- malformed/mixed vector rows inside one Snapshot.

The published Snapshot identity—not the browser and not a provider default—selects the
query adapter. Every real query call still requires its own exact ProviderDataCall
policy/export/budget/failure boundary.

### Gate evidence

The earlier one-batch 256 account preflight remains basic API evidence only. Formal
1024 preflight may run once after fake-transport tests, full local checks and independent
Sol High P0/P1 closure. A successful 1024 request signs only
`REAL EMBEDDING 1024 PREFLIGHT PASS`; W4-EMBED additionally requires Maya publication,
query, retrieval, Evidence receipt, teacher confirmation, budget, restart and browser
G3 evidence.

---

## Evidence trace

Status: `CURRENT FOUR-ROUND PROTOCOL`

### Meaning

Evidence Trace proves generation lineage: which query returned which immutable chunk
and which validated speech claim selected it. It does not prove that a source or model
claim is factually correct. The UI must use “supports/used as context”, never
“fact-checked/verified true”.

### Closed records

Every retrieval subquery has a server UUID, kind, exact text, exact hash, turn ID and
snapshot ID. Every receipt adds the immutable evidence ID, chunk ID, source filename,
source locator, excerpt, score, rank and threshold key. The Provider receives query
and evidence IDs plus the necessary excerpt; it cannot assign IDs.

`source_locator` is server-derived as
`md:<source-document-uuid>:chars:<start>-<end>`, where offsets are half-open Unicode
code-point offsets into the normalized immutable Markdown source. The browser resolves
the authorized document UUID to its display filename; the locator sent to or returned
by a Provider never contains a local path.

Every key claim produces one or more trace rows:

```json
{
  "trace_version": "evidence_trace_v1",
  "turn_id": "uuid",
  "claim_id": "uuid",
  "claim_text": "exact speech slice",
  "claim_type": "factual | background | value_judgement | proposal",
  "query_id": "uuid | null",
  "query_kind": "viewpoint | pending_question | rebuttal | updated_position | context | null",
  "query_text": "string | null",
  "evidence_id": "uuid | null",
  "chunk_id": "uuid | null",
  "source_filename": "string | null",
  "source_locator": "string | null",
  "support_mode": "direct | contextual | general_reasoning | no_match",
  "speech_span": { "start_utf16": 0, "end_utf16": 0 }
}
```

Offsets are half-open UTF-16 code-unit offsets so browser slicing is exact. The server
derives the final span by matching the Provider-returned exact `claim_text` to speech;
ambiguous or non-exact matches fail validation. `claim_id` is server-derived after
validation. Multiple rows may share one claim ID when multiple actually used evidence
items support it.

### Coverage and support rules

- the Provider returns 1–12 teaching claims that cover the turn's central position,
  each new argument and each factual/background assertion containing a concrete
  quantity or explicit source attribution;
- the current server factual-pattern validator remains a lower bound. Every sentence
  it flags must be contained by a factual/background trace with `direct` evidence;
- `direct` means the excerpt directly addresses the claim; `contextual` means it only
  supplies background. Neither label asserts independent truth;
- factual quantities and claims attributed to experts, studies, surveys or reports
  require `direct` evidence;
- value judgements and proposals may use `general_reasoning` with all evidence/source
  fields null;
- `no_match` is used only when the frozen retrieval result contains no qualifying
  receipt. It has no evidence/source and is displayed as “No relevant evidence found;
  this claim is general reasoning”;
- when receipts exist but a claim does not use them, the claim uses
  `general_reasoning`, not `no_match`;
- a claim cannot cite a receipt from another AgentVersion/KnowledgeSnapshot;
- every public source must be referenced by at least one validated claim, and every
  evidence-bearing claim must resolve to a persisted used receipt;
- unused receipts are private audit data and never enter the public source list;
- one whole speech cannot be bound wholesale to one source unless its single exact
  claim span truly covers the whole speech and passes the same rules.

### Persistence and teaching UI

Turn, query, receipt, claim and span rows commit atomically with final-ready text before
TTS/publication. Replay, report input and history read the same immutable trace; they do
not regenerate it. A claim inspector shows the highlighted speech, retrieval reason,
query, source locator/excerpt and support mode. General reasoning and no-match displays
an empty source list.

For the strict Wave 4 path, an empty/malformed claim trace or a non-exact/ambiguous
speech slice fails generation closed; it is never coerced to `[]`. Corrupt persisted
trace makes Replay unavailable with a stable safe error before any normal replay event.
Legacy turns whose persisted trace is the valid empty list remain readable.

Reports may consume only evidence IDs actually used by source turns. They cannot
upgrade contextual evidence to direct or convert general reasoning into a citation.

---

## Mutual-learning RuleSet

Status: `FROZEN / P1 REPAIRED / SOL G2 PASS / REAL CALLS 0`

RuleSet ID: `ordered_multi_expert_mutual_learning_v1`

This is the only active Debate RuleSet. The old two-round demo RuleSets and
their generation path have been removed. New Debates use the reviewed real LLM
adapter and the `segments_v2` paragraph protocol.

### Round phase

The pure resolver maps the fixed four rounds to the internal phase vocabulary:

- `round_no == 1` -> `opening`;
- `round_no > 1` and `is_final_round == false` -> `exchange`;
- `is_final_round == true` -> `final_integration`.

New Debate input fixes `round_count` at four. Round 1 is Opening, round 2
Discussion, round 3 Response, and round 4 Conclusion. The internal `exchange`
phase covers rounds 2 and 3; their actual tasks remain distinct in the frozen
teacher Ruleset prompt and segment discussion context.

### Round barrier

Round 1 turns are independent. From round 2 onward, Provider/generation context
includes every successfully generated lower-index turn, including earlier
speakers in the current round. It excludes future turns, every other private
Persona and teacher-only fields.

Speaking order rotates by round while stable participant IDs preserve question
routing. Persisted predecessor IDs and transcript hashes cover the exact visible
lower-index prefix. Resume reuses completed results rather than generating them again.

### Phase requirements

#### Opening

Each expert independently gives its understanding, professional priorities, 2–4 key
claims, own-snapshot evidence or honest general reasoning/no-match, missing
information, uncertainty and initial `position_summary`. Engagements,
answered-question IDs, other-Agent evaluation, claimed consensus and targeted questions
are forbidden.

#### Exchange

Each turn answers its one required pending question when present; faithfully engages
at least one real prior-round public/final-ready claim; uses one of `agree | extend |
qualify | challenge | reconcile`; rechecks through its own snapshot; updates its
position using `unchanged | clarified | extended | qualified | partially_revised |
substantially_revised`; explains the reason and remaining uncertainty/unresolved issue;
and may ask at most one other expert one next-round question. Disagreement is never
required.

#### Final integration

Each expert answers remaining assigned questions, engages at least one important
prior-round claim, records `learned_from_others`, compares opening/final position,
states a final professional judgment, preserves consensus and disagreement, classifies
each disagreement as `different_persona_or_framework | different_evidence |
evidence_conflict | insufficient_information | value_tradeoff`, records remaining
uncertainty and produces `final_recommendation`. Question must be `none`. Material new
topics not grounded in prior discussion are rejected.

### Versioned structured result

`EngagementV1` contains `target_turn_id`, optional `target_claim_id`, one closed
relation, `faithful_summary` and `response_summary`.

`KeyClaimV1` contains server-validated `claim_id`, exact `claim_text`, `claim_type =
factual | interpretation | value_judgement | proposal`, and `used_evidence_ids` drawn
only from current-request receipts.

`MutualLearningTurnResultV1` contains speech, key claims, engagements,
`answered_question_ids`, `learned_from_others`, position summary/update/reason,
`remaining_uncertainty`, optional unresolved issue, question, and final-only
`change_from_opening`, consensus, classified disagreements and recommendation. Phase
validators close required/forbidden fields. Legacy `StructuredTurnResult` is parsed
only for legacy RuleSet rows; historical JSON is not rewritten.

### Evidence and engagements

An expert may discuss another expert's public claim, but only current-participant
receipts can appear in its `used_evidence_ids`. Concrete quantities and explicit
research/expert/report attributions require a receipt. Value judgements may use honest
general reasoning with no public source. Engagement targets must exist in the visible
prior-round set; same-round, future and missing targets fail.

### Question queue

Each non-final turn asks at most one expert question; final turns ask none. Questions
carry question/source/target IDs and become eligible only in the next round. A
deterministic assignment gives each expert at most one required question per turn,
preferring the oldest unanswered question then source turn order/ID. Answered IDs are
never reassigned. Still-unanswered questions at final integration enter unresolved
questions rather than disappearing. The queue is derived from immutable structured
turns and RuleSet plan; no Provider selects assignments.

### Deterministic Mock synthesis

After all final-integration turns are public/final-ready, a pure synthesis module
derives `MutualLearningSynthesisV1`: direct answer, consensus, complementary views,
remaining classified disagreements, position changes, evidence conflicts, remaining
uncertainty and recommended next steps. It uses only public structured fields and used
evidence lineage. It does not vote facts, force consensus, invent facts or read private
Persona/RAG. The first implementation is deterministic Mock and makes no external
call.

### Public compatibility

New Debate creation explicitly selects the new RuleSet and `round_count` 2–5. Existing
creation defaults and all persisted legacy IDs retain two-round semantics. Public DTOs
add the new RuleSet ID, dynamic positive round numbers and optional versioned
mutual-learning fields/synthesis; old payloads remain valid. WebSocket round/turn
payloads accept the dynamic round number and optional phase/round-count without
changing event names. Replay reads frozen text/audio and never regenerates.

### Acceptance

The required matrix is 2×2, 3×3 and 5×5; no new-rule business branch may compare
`round_no == 2` or use an `else` meaning round two. Tests cover barrier isolation,
engagement targets/relations, required/final fields, own-snapshot evidence,
general-reasoning no-source, one-time question assignment, old RuleSet playback/Replay,
dynamic plans, DTO/WS/generated client and complete local backend/frontend checks.

---

## Prompt budget and request

Status: `FROZEN / MOCK SOL G2 PASS / LLM-A RUNTIME DELTA CANDIDATE`

### Logical request

The Provider-visible request has exactly two messages:

1. one versioned system message containing the platform priority rules exactly once;
2. one canonical JSON user message containing `prompt_request_v1`.

The audit record stores `rule_set_id` and `rule_set_hash`, not a second Provider-visible
copy of the prose rules. `prompt_request_v1` contains:

- debate/turn/rule/phase identifiers and server-owned schedule fields;
- topic and assigned stance;
- one `persona_provider_view_v1`; raw `AGENT.md` is absent;
- for `ordered_multi_expert_mutual_learning_v1`, the complete exact speech of every
  public/final-ready turn from an earlier round, in turn-index order, exactly once
  each, plus necessary public structured fields and transcript hash;
- the pending question once;
- a query catalog and a deduplicated evidence catalog. Each evidence excerpt appears
  once and queries refer to evidence IDs;
- the closed StructuredTurnResult + EvidenceTrace output schema identifier. For real
  W4-LLM-A this identifier is not sent alone: `LLM_A_RUNTIME_V1.md` requires the
  complete strict `LLM_TURN_OUTPUT_SCHEMA_V1.json` object and its exact hash.

Other Agents' Persona, snapshot ID, teacher-only notes, user identity and private
drafts are absent. Same-round and future turns are absent even when a lower-index
same-round turn is already final-ready. Visible earlier-round speech may not be
summarized, truncated, replaced by `turn_summary` or fetched through an unversioned
provider-side state. Legacy RuleSets retain their frozen lower-turn-index context
semantics behind their existing IDs.

### Hard limits

For `llm_debate_turn_v1`:

- maximum serialized input: 32,000 model tokens before send;
- maximum canonical request bytes: 96 KiB before send;
- maximum requested output: 1,500 model tokens, with 1,510 reserved to cover the
  supplier's documented ten-token completion tolerance;
- maximum attempts per turn: 2;
- maximum LLM calls for a 5-Agent × 2-round debate: 20;
- maximum estimated charge: CNY 0.15 per request and CNY 3.00 per debate;
- any count or estimate over the limit fails before network I/O with a safe budget
  code; the turn remains unpublished and Mock is not mislabeled as real output.

**Demo V1 amendment (user decision, 2026-09-01).** Pinning a supplier-compatible
tokenizer moves to Wave 4.1, and the authorization gate that blocked the conservative
fallback is removed. The conservative counter treats each UTF-8 byte as one token, so it
over-estimates and can only reject an over-large request; it may therefore back a real
request. Its exact ID and asset hash are still recorded with every request. The
Provider's returned usage remains evidence after send, never the only budget guard.
Attempt 1 and 2 still use the same tokenizer object identity, ID and asset hash.

There is deliberately no percentage-reduction KPI. Acceptance measures the serialized
baseline and final request, proves the duplicate classes are absent, and enforces the
hard limits while preserving the full transcript.

### Attempt and retrieval semantics

Retrieval executes once and freezes the ordered query/receipt set before the first LLM
call. Attempt 2 reuses the exact receipt hash, transcript hash, Persona hash, rule hash,
model configuration and base request.

Attempt 2 is automatic only after the teacher has confirmed the exact manifest's
two-attempt maximum and full worst-case cost. It is allowed only for:

- a Provider response known to have completed but failing closed JSON/schema/rule
  validation: append only a stable safe error code and JSON pointer list as
  `repair_feedback`;
- a transport failure that the adapter can prove occurred before the supplier accepted
  the request: resend the identical frozen request once.

`LLM_A_RUNTIME_V1.md` is authoritative for the exact transport classification table.
Any HTTP status is accepted/charged; only a pre-byte DNS/TCP/TLS/connect failure is
`not_sent`. Write/read/protocol uncertainty is `acceptance_unknown` and never retries.
The pre-confirmed export manifest includes the closed
`server_authored_structure_repair_feedback` class and `repair_feedback_v1` policy hash.
Attempt 2 is rescanned before send; failed values/messages are never copied into it.

Retrieval may run a second time only when the first retrieval ended in a technical
failure before any LLM request. That is a retrieval retry, not a structure repair.

No automatic retry is allowed for an uncertain accepted/billed outcome, timeout after
acceptance cannot be excluded, budget failure, authentication/permission error, safety
refusal, unavailable fixed model, cross-snapshot evidence, stale generation fence or a
changed transcript/Persona/rule hash. These fail closed and require an operator-visible
safe state, not hidden continuation.

### Usage ledger

Every external attempt records server-side:

`provider_operation`, fixed `model_version`, `prompt_contract_version`,
`persona_spec_hash`, `rule_set_hash`, `transcript_hash`, `receipt_hash`, `input_tokens`,
`cached_input_tokens`, `output_tokens`, `attempt_no`, `retrieval_reused`, request
acceptance state, safe error code, price-card version, estimated cost and nullable
reconciled actual cost.

Price-card fields, Decimal ceiling, cached-token fallback, missing usage and overrun
rules are frozen in `LLM_A_RUNTIME_V1.md`. An accepted/unknown attempt retains its full
worst-case allocation; only proven not-sent releases atomically before another
reservation.

Before network I/O, the attempt and its worst-case count/cost allowance are atomically
reserved through the durable state machine in ProviderDataCallV1 and the
`llm_debate_turn` budget bucket. A read-then-send budget check is forbidden. Concurrent
workers therefore cannot each observe spare budget and exceed the Debate cap, while an
Embedding-query reservation cannot consume or install the LLM allowance.

Supplier request IDs are encrypted/restricted operations data and never enter normal
API responses. API keys never enter the database or logs. There is no Wave 4 cost
dashboard or teacher/operator cost-display feature; the ledger exists for Gate audit,
budget enforcement and incident recovery only.

---

## Provider control ledger

Status: `FROZEN / REAL EMBEDDING DIMENSION 1024 / RUNTIME GATES INCOMPLETE / FORMAL MAYA RUNTIME CALLS 0`

### Fixed supplier resources

The intended local Demo supplier is Alibaba Cloud Model Studio in the existing
`cn-beijing` workspace. Fixed identifiers are:

| Operation        | Fixed resource                                        | Mode                                                                    |
| ---------------- | ----------------------------------------------------- | ----------------------------------------------------------------------- |
| Debate LLM       | `LLM_MODEL`, default `qwen3.8-max-2026-09-02`         | exact Chat/JSON-Schema wire in `LLM_A_RUNTIME_V1.md`                    |
| Text embedding   | `text-embedding-v4`, dimension `1024`                 | synchronous; max 10 inputs, 8,000 tokens/item and 30,000 tokens/request |
| Voice-clone TTS  | `qwen3-tts-vc-2026-01-22`                             | HTTP, language `English`                                                |
| Voice enrollment | `qwen-voice-enrollment` targeting the fixed TTS model | separate TTS Gate only                                                  |

`latest`, unversioned fallback, automatic model upgrade and cross-region fallback are
forbidden. Model unavailability requires a contract revision.

Official references checked 2026-08-30:

- <https://help.aliyun.com/zh/model-studio/text-generation-model>
- <https://help.aliyun.com/zh/model-studio/embedding>
- <https://help.aliyun.com/zh/model-studio/tts-model>
- <https://help.aliyun.com/zh/model-studio/model-pricing>
- <https://help.aliyun.com/zh/model-studio/privacy-notice>
- <https://help.aliyun.com/zh/model-studio/what-is-model-studio>

The checked documentation reports structured output for the fixed Qwen generation
family, selectable dimensions including 1024 and a ten-input batch limit for
`text-embedding-v4`,
and English support for the fixed voice-clone TTS snapshot. Embedding and TTS
list prices are not a call gate. The LLM model is `LLM_MODEL`, not a supplier
price card.

The exact W4-LLM-A endpoint, body, strict provider-output schema, durable runner,
teacher confirmation, budget buckets, privacy scanner and atomic publication contract
are frozen separately in `LLM_A_RUNTIME_V1.md` and
`LLM_TURN_OUTPUT_SCHEMA_V1.json`. A schema ID alone never authorizes a request.

The official Beijing embedding table also reports 33,000 tokens as its batch ceiling;
Maya deliberately freezes the lower 30,000-token request ceiling and an 8,000-token
per-item ceiling. W4-EMBED pins a supplier-compatible local tokenizer and asset hash.
Until that tokenizer can authorize a request, conservative preflight counts each UTF-8
byte as one token. It may reject safe text but cannot undercount a long unbroken input.

An independent, no-student-data account preflight recorded one successful 256-dimension
Embedding request and one successful structured LLM request. Those two calls prove only
basic account/workspace/API availability. They did not change Maya's all-Mock runtime,
do not authorize another 256 or LLM preflight, and are not a W4-EMBED/W4-LLM Gate PASS.
The user subsequently froze the formal real Embedding dimension at 1024. A separate
1024 preflight is required after fake-transport, migration, publication, query,
retrieval, restart and Sol audit boundaries pass.

### Supplier data-processing preflight

The official privacy page checked on 2026-08-30 states that call data is stored as
required by applicable law. The official product FAQ limits its no-training assurance
to pay-as-you-go API and Token Plan Team; Token Plan Personal and Coding Plan have
different terms. Maya therefore makes no “not stored” claim.

Before the first external request of a Gate, a server-side `ProviderPolicySnapshot`
and Gate evidence must verify and freeze:

- Alibaba account product type is pay-as-you-go API or Token Plan Team; Token Plan
  Personal, Coding Plan and an unknown/unverifiable plan are forbidden;
- the API key, workspace and exact endpoint belong to `cn-beijing`; a key/endpoint for
  another product or region is rejected before request construction;
- the then-current official privacy notice, product FAQ and applicable service terms
  URLs, retrieval timestamps and content hashes;
- the applicable no-training basis for that account product;
- every account/workspace inference-log, prompt/response logging, log-backflow and
  service-improvement control visible to the account. Optional content logging or
  backflow must be disabled; an unavailable or ambiguous control is a zero-call stop;
- the supplier's disclosed storage fact and any available retention/deletion setting.
  An unspecified retention duration is recorded as unknown, never invented.

The teacher export-confirmation screen names Alibaba Cloud Model Studio, Beijing, the
operation purpose, every outbound field class from the matrix below, the fact that the
supplier stores call data, the verified no-training basis and the known/unknown
retention setting. Confirmation binds the ProviderPolicySnapshot hash and export
manifest hash. A policy/account/plan/control change invalidates it. This local Demo
still sends no personal identity; formal minors/school use remains a separate privacy
and legal release Gate.

### External data matrix

| Data                                  |             LLM |      Embedding |                 TTS | Rule                                   |
| ------------------------------------- | --------------: | -------------: | ------------------: | -------------------------------------- |
| topic and platform rules              |             yes |     query only |                  no | no user identity                       |
| confirmed structured current Persona  |             yes |             no |                  no | raw `AGENT.md` never sent              |
| complete RuleSet-visible prior speech |             yes |             no | current speech only | mutual learning excludes same round    |
| current evidence excerpt/query        |             yes |            yes |                  no | only confirmed exportable snapshot     |
| opaque evidence/query/turn IDs        |             yes |             no |                  no | supplier cannot resolve local identity |
| server-authored repair code/pointers  | retry attempt 2 |             no |                  no | closed policy; never failed values     |
| source filename/absolute path         |              no |             no |                  no | server resolves display metadata       |
| teacher note                          |              no |             no |                  no | internal only                          |
| student name/user ID/nickname         |              no |             no |                  no | forbidden                              |
| audio/voice sample                    |              no |             no |    speech text only | enrollment is separate Gate            |
| API key/workspace ID                  |  transport only | transport only |      transport only | server secret; never prompt/log/DTO    |

Before real LLM/Embedding, a teacher confirms an exact export manifest by CAS. The
manifest binds the PersonaSpec hash, the immutable SnapshotBuild candidate described
below, ProviderPolicySnapshot hash, operation types, data classification and a
declaration that no field contains a secret, credential, student identity/name,
nickname, private audio transcript or unrelated personal data. Any hash/revision or
policy change invalidates confirmation. Published immutable snapshots are never
modified in place.

For LLM structure repair, the exact manifest also binds the version/hash of the closed
`repair_feedback_v1` policy and declares the
`server_authored_structure_repair_feedback` field class. That class contains only a
stable code and bounded JSON Pointers; it never contains the rejected Provider value,
response text, exception message or identity-bearing input. The teacher disclosure
shows that optional retry class and the two-attempt maximum before confirmation. The
canonical grammar is `LLM_REPAIR_FEEDBACK_V1.json`, SHA-256
`d5b81d460ecd713f4b3d52b5732efc935b63455c2a29b5a5ab2471b17d00050b`.

### Pre-provider SnapshotBuild lifecycle

A real embedding call cannot depend on a KnowledgeSnapshot that is created only after
embedding. W4-EMBED therefore introduces an internal, non-public `SnapshotBuildV1`
before network I/O. Preparation freezes:

- planned AgentVersion and KnowledgeSnapshot UUIDs;
- exact draft revision and confirmed PersonaSpec hash;
- normalized source bytes, document IDs/order, source/content hashes and total size;
- chunking contract/version plus every chunk ID, source offsets, text and hash;
- fixed embedding provider/model/region/dimension/policy version and the canonical
  build-manifest hash.

The build is not a published KnowledgeSnapshot, cannot be selected by Debate setup and
contains no vector result yet. The teacher's `external_export_allowed` CAS signs its
exact manifest hash. A changed draft/Persona/source cannot reuse the confirmation or
publish the build.

Before the first request, chunks are packed deterministically by document order then
chunk index using a stable greedy algorithm. Each batch contains at most 10 items and
is packed toward 30,000 counted tokens. On September 23, 2026 the owner removed the
snapshot ceilings of 20 requests, 120,000 total counted tokens and CNY 0.10. Those
totals no longer reject a plan or the `embedding_snapshot` scope reservation. Each
planned request, including `not_sent` or `acceptance_unknown` attempts, is still
recorded on the ledger.

The durable operation state machine is:

`prepared -> export_confirmed -> sending -> accepted -> succeeded`

with terminal/recovery states `not_sent`, `acceptance_unknown`, `failed`, `abandoned`.
Every batch binds the build hash, batch index, chunk hashes, attempt, allowance and
usage record. `not_sent` may retry the same frozen batch within the cap. An
`acceptance_unknown` batch that still has a matching staged response is restored and
is not resent. An `acceptance_unknown` batch with no staged response may be sent
again on the next attempt, up to three attempts for that build; that retry can charge
the batch again. Accepted batches are not resent. Abandonment creates no
AgentVersion/KnowledgeSnapshot; future work needs a new build and confirmation.
Staged bytes are deleted only after a terminal outcome and the existing file-recovery
journal has recorded cleanup.

On success, the server verifies response count/order, dimension 1024, finite numeric
values, fixed model key and every batch/build hash. One local transaction then creates
the immutable AgentVersion/KnowledgeSnapshot/vector rows from that exact build and
marks publication complete. Any validation, CAS or commit failure publishes nothing;
no existing published version or snapshot is changed. Mock embedding remains the
separate `mock / mock-sha256-v1 / local / 256 / w4-mock-v1` identity and uses the same
build/publish invariants without external-export confirmation or network states.

Every DashScope request must visibly declare `parameters.dimension = 1024`; supplier
defaults are forbidden. That value is part of the frozen request hash and must match
the SnapshotBuild, export manifest, staged response, persisted Snapshot identity and
query identity. The server never pads, truncates or converts a wrong-dimensional
response.

Real query retrieval must match the published Snapshot on provider, model, region,
dimension and embedding policy version. A Mock query against a real Snapshot, a real
query against a Mock Snapshot, or any other identity mismatch fails closed before
scoring.

### Operation caps

| Gate operation                |           Request cap | Input/output cap               | Estimated charge cap |
| ----------------------------- | --------------------: | ------------------------------ | -------------------: |
| one new real snapshot         |                 none | 10 items / 30,000 tokens per batch |                 none |
| W4-LLM-A 2-Agent × 2-round G3 |           8 LLM calls | PromptBudgetV1 per call        |             CNY 1.20 |
| 5-Agent × 2-round debate      |          20 LLM calls | PromptBudgetV1 per call        |             CNY 3.00 |
| one real TTS technical Gate   |     2 synthesis calls | 2,400 billed characters total  |             CNY 0.20 |
| one 5-Agent × 2-round TTS run |    10 synthesis calls | 15,000 billed characters total |             CNY 1.20 |
| new voice enrollment          |            1 creation | one approved sample            |             CNY 0.01 |

W4-LLM-B adds at most two calls for one barrage-insight snapshot and two calls for one
Maya report revision; it has a separate CNY 0.60 cap and cannot consume the Debate LLM
budget silently. Translation is outside this contract and remains Mock/disabled.

### Fail-closed and uncertainty

Pre-send validates active Gate ID/SHA, operation allowance, selector composition,
fixed model, region, allowed account product, current ProviderPolicySnapshot, exact
export-manifest/build confirmation, token/character estimate, cumulative count/cost
and generation fence. Failure produces a safe local code with zero request.

Every external request uses one shared durable reservation contract. Budget allocation
is additionally isolated by the closed `(scope_id, budget_bucket)` identity in
`LLM_A_RUNTIME_V1.md`; one operation cannot consume another operation's allowance:

`prepared -> reserved -> sending -> accepted -> succeeded`

with terminal/recovery states `not_sent`, `acceptance_unknown`, `failed` and
`abandoned`. `(scope_id, provider_operation, logical_item_id, attempt_no)` is unique.
`scope_id` is the exact Debate, SnapshotBuild, report/insight revision or TTS Gate run.

- `prepared` contains the frozen request hash and conservative maximum usage/cost;
- one independent database transaction/CAS atomically verifies the scope cap, reserves
  one call plus the maximum cost, and commits `reserved` before any network I/O;
- another durable transition commits `sending` immediately before the adapter may
  touch the network. Sending without that committed state is forbidden;
- response acceptance and sanitized response/usage staging are durably recorded before
  validation or product publication;
- validation failure records `failed` with consumed usage and may open only the next
  contract-authorized attempt;
- validated product rows and the final usage ledger commit atomically with
  `succeeded`; a product result cannot exist without its ledger and vice versa.

Concurrent reservations serialize on the scope budget row, so total reserved plus
consumed maximum cost/count cannot exceed the hard cap. `not_sent` is allowed only when
the adapter proves no supplier acceptance; it releases cost/call reservation but its
unique attempt history remains. `acceptance_unknown` and `accepted` retain their full
reservation and count against the cap unless reconciliation proves `not_sent`.

Startup recovery maps a stranded `reserved` attempt to `not_sent`, because the
network-permitted `sending` transition never committed. A stranded `sending` attempt
or an incomplete accepted response becomes `acceptance_unknown`. A complete staged
accepted response resumes validation/local commit without another Provider request.
Recovery is idempotent under the unique key and generation/build hashes.

Timeouts and broken connections are classified as `not_sent`, `accepted`, or
`acceptance_unknown`. Debate, chat and report `acceptance_unknown` consumes the
call/cost ceiling, stores no generated product result and is not automatically
retried. Snapshot embedding is the exception in the SnapshotBuild section above:
an unknown batch with no staged response may be sent again, up to three attempts.
Supplier error bodies are redacted to stable safe codes.

Standing user authorization covers later local/private GitHub implementation and
bounded billed evidence under these Gates. It does not permit exceeding a cap, changing
model/region/data class, sending forbidden identity data or skipping the exact Gate.

---

## LLM turn runtime

Status: `DESIGN FROZEN CANDIDATE / G0-S REAUDIT PENDING / REAL LLM IMPLEMENTATION NOT AUTHORIZED`

This contract closes the design decisions required before a real debate-turn LLM can
be implemented. It does not authorize a Provider call. The earlier one-call account
preflight remains availability evidence only and must not be repeated.

### Fixed wire resource

The only W4-LLM-A resource is:

- method: `POST`;
- endpoint: `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions`;
- model: `LLM_MODEL`, default `qwen3.8-max-2026-09-02`;
- region: `cn-beijing`;
- response mode: one non-streaming OpenAI-compatible Chat Completion;
- transport: one injected no-redirect HTTP attempt, connect timeout 5 seconds, total/read
  timeout 120 seconds;
- redirects, regional fallback, model fallback, `latest`, SDK retry and HTTP retry are
  forbidden.

The exact Provider-visible JSON object contains only:

```json
{
  "model": "<LLM_MODEL>",
  "messages": [
    { "role": "system", "content": "<frozen system contract>" },
    { "role": "user", "content": "<canonical PromptRequestV1 JSON>" }
  ],
  "enable_thinking": false,
  "stream": false,
  "temperature": 0.2,
  "top_p": 0.8,
  "max_completion_tokens": 1500,
  "n": 1,
  "response_format": {
    "type": "json_schema",
    "json_schema": {
      "name": "maya_llm_turn_output_v1",
      "strict": true,
      "schema": "<exact LLM_TURN_OUTPUT_SCHEMA_V1.json object>"
    }
  }
}
```

`tools`, `tool_choice`, search, code interpreter, `user`, metadata, audio, images,
`reasoning_content`, `preserve_thinking` and Provider-side conversation state are absent.
The system/user messages are the two strings already frozen by PromptRequestV1; neither
may be split, reordered or duplicated.

`max_tokens` is not used because the official Chat contract marks it for deprecation;
the fixed snapshot supports `max_completion_tokens`. The official structured-output
contract requires `enable_thinking=false` for stable JSON and supports strict JSON
Schema for the Qwen3.7-Plus family.

The request hash is SHA-256 over canonical JSON containing method, exact resolved
endpoint, the complete Provider-visible body, prompt contract version, schema hash,
tokenizer ID/hash, rule/persona/transcript/receipt hashes, turn ID, generation fence,
policy hash, export-manifest hash and repair-policy hash. Authorization is excluded. The
resolved endpoint participates ephemerally in the hash input, but the workspace value
and raw endpoint are never persisted or exposed; only the resulting request hash is
stored.

Official references checked 2026-08-31:

- <https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions>
- <https://help.aliyun.com/zh/model-studio/qwen-structured-output>
- <https://help.aliyun.com/zh/model-studio/qwen3-7-plus>

### Closed Provider output

The supplier schema is the exact repository file
`LLM_TURN_OUTPUT_SCHEMA_V1.json`, SHA-256
`77769a5fdc0e6ef368c048a6e2b28891c1702a2d904da2471bcf7b2ed9df253f`.
The schema name is `maya_llm_turn_output_v1`; `strict=true` and every object has
`additionalProperties=false`.

The Provider never authors Maya IDs. In particular it cannot output `claim_id`,
`evidence_id`, `query_id`, `question_id`, participant IDs or arbitrary target turn IDs.
It returns only bounded integer references into the exact ordered catalogs in the frozen
request:

- `used_evidence_refs[]` indexes the current request's evidence catalog;
- `target_turn_ref` indexes the visible prior-turn catalog;
- `target_claim_ref=-1` means the engagement targets the whole referenced turn and is
  never used as an array index; a non-negative value indexes only that turn's visible
  claim catalog;
- `question.mode=none` requires `target_participant_ref=-1` and `text=""`;
- `question.mode=ask` requires a non-negative `target_participant_ref` within the
  allowed next-question target catalog and non-empty text;
- `answered_required_question` is a boolean; the server maps `true` only to the one
  assigned pending question.

All other negative references, a sentinel used outside its one rule, and every
out-of-range reference are rejected before Python/SQL indexing. The server maps valid
references to its own IDs,
requires every `claim_text` to be an exact speech substring, derives UTF-16 spans and
claim IDs, then applies the existing RuleSet, EvidenceTrace and cross-Snapshot validators.
Opening/exchange/final field rules remain those of
`ordered_multi_expert_mutual_learning_v1`; the JSON Schema does not replace phase
validation.

A successful HTTP response must be `object=chat.completion`, have the exact fixed model,
and contain exactly one choice with `index=0`, `message.role=assistant`, non-empty string
content, no non-empty refusal/reasoning/tool/function field and no tool call. Only
`finish_reason=stop` is eligible for JSON and local product validation.

`finish_reason=length` is staged as an accepted, charged, truncated structure failure;
it never publishes but attempt 1 may enter the one structure-repair path below.
`content_filter`, `tool_calls`, `function_call`, `null` and every unknown finish reason
are terminal accepted failures with no retry. A wrong model, multiple choices, wrong
choice index/role or non-empty refusal/tool/reasoning content is terminal with no retry.

Usage must contain non-negative integer `prompt_tokens`, `completion_tokens` and
`total_tokens`, with `total_tokens = prompt_tokens + completion_tokens`. Optional
`prompt_tokens_details.cached_tokens` is a non-negative integer no greater than
`prompt_tokens`; when absent it is zero. Missing or malformed usage is staged as
`provider_usage_unknown`, retains the full reservation, never publishes and is not
retried. Content is parsed as JSON and validated again locally against the exact schema.
Missing/extra fields, invalid JSON, schema failure, RuleSet failure or Evidence failure
never reaches `final_ready`.

### Outbound privacy boundary

Before manifest persistence and again immediately before `sending`, the server parses
the exact two messages and validates their closed field tree. Unknown fields, duplicate
JSON keys, malformed JSON and unapproved outbound field classes fail before network
I/O. Teacher-authored Topic/Background, Persona, RAG excerpts, public speech and
classroom messages are treated as data and are not rejected by keyword, language,
phone/email/UUID, path or identity-pattern scanners. Provider credentials and endpoint
configuration are not fields in these DTOs and therefore cannot enter either message.

The export manifest contains hashes and the approved field classes, not raw messages.
Teacher disclosure remains the only browser surface that names the supplier. Ordinary
REST and WebSocket payloads expose only safe retry/status codes.

### Durable operation and atomic publication

One turn uses `provider_operation=llm_debate_turn` and the exact Debate ID as scope. Its
logical item is the immutable Turn ID. Attempt identity is unique on
`(debate_id, llm_debate_turn, turn_id, attempt_no)`.

The state machine is:

`prepared -> reserved -> sending -> accepted -> succeeded`

with `not_sent`, `acceptance_unknown`, `failed` and `abandoned` as the existing recovery
states. Before confirmation the operation is `prepared` with zero request count, zero
charged count, no reservation and no allocated budget.

After exact teacher confirmation, one transaction reserves the attempt's worst-case
tokens/cost and moves it to `reserved`. The worker records `sending` before transport.
An HTTP response known to be accepted is sanitized into an immutable LLM accepted-stage
row before product validation. That row stores no raw headers or supplier ID and binds:

- request/prompt/schema hashes and exact model;
- tokenizer ID/hash;
- rule, persona, transcript and receipt hashes;
- sanitized provider-output JSON and hash;
- input, cached-input and output Token counts;
- price-card version, estimated cost and nullable reconciled actual cost;
- attempt number, retrieval reuse and safe error code.

Publication of the validated DebateTurn structured result, EvidenceTrace rows, accepted
usage ledger and Provider operation `succeeded` is one database transaction. A failure
or stale generation fence rolls back all product success. The accepted stage remains
recoverable for a later local validation/publication pass and never triggers a startup
request.

Startup performs reconciliation only. `sending` becomes `acceptance_unknown`; it is not
retried. An accepted complete stage can be validated/published locally.

Attempt 2 is automatic only when the teacher-confirmed manifest already disclosed
`max_attempts=2` and the full two-attempt worst-case cost. It is created only after
attempt 1 reaches either:

- proven `not_sent`, in which case the base request is byte-identical; or
- accepted HTTP 200 with `finish_reason=length`, invalid JSON, schema failure or local
  RuleSet/output-structure failure, in which case only the frozen safe code and JSON
  pointer list are added as `repair_feedback`.

`repair_feedback_v1` is the exact repository file `LLM_REPAIR_FEEDBACK_V1.json`,
SHA-256 `d5b81d460ecd713f4b3d52b5732efc935b63455c2a29b5a5ab2471b17d00050b`.
It has the shape
`{"code": <enum>, "json_pointers": <array>}`. The code is one of
`output_truncated`, `json_invalid`, `schema_invalid` or `rule_invalid`. Pointers are
sorted, unique RFC 6901 paths into `LLM_TURN_OUTPUT_SCHEMA_V1`, at most 12 values and at
most 160 ASCII characters each. An invalid-JSON response uses an empty pointer list.
The object contains no failed value, excerpt, supplier message or local exception text.

The export manifest created before attempt 1 includes the
`server_authored_structure_repair_feedback` field class and the canonical
repair-policy version/hash. Teacher confirmation binds that policy, the two-attempt
maximum and full cost. Attempt 1 sends no feedback. Attempt 2 may add exactly this one
field to the canonical user object; the system message and every base user field remain
byte-identical. The exact attempt-2 request receives its own request hash and is scanned
again against the same manifest allowlist immediately before send. A feedback code or
pointer outside the closed policy is a zero-call terminal failure.

Attempt 2 is never pre-created and cannot be triggered by missing confirmation, budget,
privacy, wrong model, refusal/content filter, usage failure, HTTP rejection or
acceptance-unknown. It is the final attempt regardless of its outcome.

#### Transport and acceptance classification

| Event                                                               | State                  | Automatic attempt 2 |
| ------------------------------------------------------------------- | ---------------------- | ------------------- |
| DNS/TCP/TLS/connect failure or connect timeout before request bytes | `not_sent`             | yes, attempt 1 only |
| write timeout/error after writing may have begun                    | `acceptance_unknown`   | never               |
| read timeout, EOF or remote protocol error after send               | `acceptance_unknown`   | never               |
| any HTTP 3xx (redirects disabled), 4xx, 5xx                         | accepted `failed`      | never               |
| HTTP 200 + `stop` + valid usage                                     | `accepted`             | local validation    |
| HTTP 200 + `length` or structural invalidity + valid usage          | accepted repairable    | yes, attempt 1 only |
| HTTP 200 + refusal/filter/tool/wrong model/unknown finish/bad usage | accepted terminal fail | never               |

An HTTP status proves a response was received, not that it was free. Every HTTP outcome
holds the full charged reservation. A proven `not_sent` transition atomically releases
its reservation/allocation before attempt 2 reserves; every uncertain or accepted
attempt keeps its worst-case allocation permanently.

### Budget buckets and migration 0014

Provider budget is keyed by `(scope_id, budget_bucket)`, never by scope alone. Closed
buckets are:

- `embedding_snapshot`;
- `embedding_query`;
- `llm_debate_turn`;
- `llm_barrage_insight`;
- `llm_maya_report`;
- `tts_synthesis`;
- `voice_enrollment`.

For W4-LLM-A, a 2-Agent × 2-round Gate fixture has at most 8 charged attempts and CNY
1.20. The general 5-Agent × 2-round limit remains 20 charged attempts and CNY 3.00.
Each request retains the PromptBudgetV1 32,000-input-token, 96-KiB canonical-user and
CNY 0.15 ceilings. The request asks for 1,500 output tokens, but the official API permits
up to ten tokens of overshoot, so pre-send reserves 1,510 output tokens. The corresponding
worst-case token buckets are 268,080 for the 8-attempt fixture and 670,200 for the
20-attempt fixture. A response over 1,510 output tokens is `provider_usage_overrun`,
never publishes and is not retried.

Supplier price cards are not loaded and do not block a request. Historical ledger
columns for price-card version and cost stay in the database and are written as
zero. Missing or malformed usage, or a count above the frozen token tolerance,
still blocks product publication.

An accepted/unknown attempt never releases unused worst-case allocation; its actual cost
is an audit value only. A proven not-sent attempt releases atomically before another
reservation. Attempt 2 that reaches send consumes its own call and worst-case budget.
The ninth Gate-fixture charged call or any concurrent over-allocation fails before send.

Migration `0014_llm_runtime_budget_buckets` must:

1. recreate `provider_scope_budgets` with composite primary key
   `(scope_id, budget_bucket)` and closed bucket check;
2. backfill current rows deterministically as `embedding_snapshot` or
   `embedding_query` from their existing operations, rejecting an ambiguous populated
   scope instead of guessing;
3. add nullable Debate/Turn owner FKs and indexes to export manifests while enforcing
   both-or-neither ownership for `llm_debate_turn`;
4. add immutable accepted LLM-stage/usage rows with all hashes and accounting fields
   above;
5. preserve every 0001–0013 row and provide lossless populated downgrade/re-upgrade
   tests. Old Debate turns are not rewritten.

### Teacher confirmation and retry

Every LLM turn has one exact manifest owned through
`Turn -> Debate -> Course`, plus its participant AgentVersion/group owner. A dedicated
teacher-only pending DTO is:

```json
{
  "debate_id": "opaque-local-id",
  "items": [
    {
      "turn_id": "opaque-local-id",
      "manifest_hash": "64-lower-hex",
      "confirmation_revision": 1,
      "confirmed": false
    }
  ]
}
```

It contains no provider, model, endpoint, policy, prompt, Persona, transcript, evidence
text or usage. Authorization uses the exact Debate course. Student/other-course access
is 403 and missing Debate/Turn is 404. The teacher opens the existing exact disclosure
screen, where the disclosure includes `max_attempts=2`, the full two-attempt maximum,
the optional server-authored repair field class and repair-policy hash, confirms by
policy/manifest/revision CAS, then explicitly retries the pending non-terminal turn.
That click starts attempt 1; the two narrowly classified attempt-2 paths above are
automatic under the confirmed cap. Confirmation-required and proven-not-sent
exhaustion leave the Debate running; ordinary WS carries only the safe code.

### Tokenizer and retry continuity

**Demo V1 amendment (user decision, 2026-09-01).** The supplier-tokenizer
authorization gate is removed. W4-LLM-A never pinned a supplier tokenizer into the
product runtime, so this clause made the real Debate LLM and real Maya Report paths
unreachable: `factory.llm_provider` builds the adapter with no tokenizer and the adapter
falls back to the conservative counter, which the gate then refused. Demo V1 accepts the
conservative UTF-8 counter for a real request. It over-counts rather than under-counts,
so it can only reject an over-large request, never authorize an under-counted one. An
exact tokenizer ID and asset hash remain mandatory and are persisted with every request,
so the ledger always names the counter behind an estimate. The bounded acceptance-run
ledger, not this estimate, is what caps how many real requests may occur. Pinning a real
supplier tokenizer is Wave 4.1 work.

The original clause is retained below as the pre-Demo-V1 contract:

~~The first real LLM attempt requires a reviewed supplier-compatible local tokenizer with
immutable ID and asset hash. UTF-8 conservative counting may reject preparation but
cannot authorize a real request.~~ Attempt 2 must use the same tokenizer object identity,
ID/hash, exact base request, retrieval receipts, rule/persona/transcript hashes and model
configuration. Structure repair may add only the frozen safe code and JSON pointer list.
No retrieval or identity-bearing text is added.

### G1 authorization tests

Before implementation can receive G2 review, fake transports must prove:

1. exact endpoint/body/model/non-thinking/temperature/top-p/output cap/schema hash;
2. two messages exactly once, complete allowed prior speech, no same-round context;
3. malicious topic, Persona, prior speech, query and evidence each yield zero manifest,
   operation, reservation and call without echoing the value;
4. the Provider cannot author Maya IDs and every reference maps to a frozen catalog;
5. malformed, extra-field, wrong-model, wrong-ref and unsupported Evidence output fails;
6. stale/missing confirmation is zero-call; exact course teacher succeeds; authorization
   and 404 boundaries are stable;
7. budget buckets are independent and concurrent allocation cannot exceed 8/CNY1.20;
8. attempt 2 is only structure repair or proven-not-sent and preserves every frozen
   hash/tokenizer value;
9. `acceptance_unknown` and startup perform zero calls; an accepted stage resumes
   locally;
10. Turn, EvidenceTrace, usage and operation success commit or roll back together;
11. selector composition permits only real LLM with Embedding/TTS/Voice/Translation
    Mock or disabled;
12. the active four-round RuleSet, Mock fixtures and Replay remain independently testable.

This historical gate has been superseded by the reviewed real LLM configuration
recorded in `docs/PROJECT.md`.
