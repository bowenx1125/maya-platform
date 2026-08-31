# W4-LLM-A Runtime and Wire Contract V1

Status: `DESIGN FROZEN CANDIDATE / G0-S REAUDIT PENDING / REAL LLM IMPLEMENTATION NOT AUTHORIZED`

This contract closes the design decisions required before a real debate-turn LLM can
be implemented. It does not authorize a Provider call. The earlier one-call account
preflight remains availability evidence only and must not be repeated.

## Fixed wire resource

The only W4-LLM-A resource is:

- method: `POST`;
- endpoint: `https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com/compatible-mode/v1/chat/completions`;
- model: `qwen3.7-plus-2026-05-26`;
- region: `cn-beijing`;
- response mode: one non-streaming OpenAI-compatible Chat Completion;
- transport: one injected no-redirect HTTP attempt, connect timeout 5 seconds, total/read
  timeout 120 seconds;
- redirects, regional fallback, model fallback, `latest`, SDK retry and HTTP retry are
  forbidden.

The exact Provider-visible JSON object contains only:

```json
{
  "model": "qwen3.7-plus-2026-05-26",
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
policy hash and export-manifest hash. Authorization is excluded. The resolved endpoint
participates ephemerally in the hash input, but the workspace value and raw endpoint are
never persisted or exposed; only the resulting request hash is stored.

Official references checked 2026-08-31:

- <https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions>
- <https://help.aliyun.com/zh/model-studio/qwen-structured-output>
- <https://help.aliyun.com/zh/model-studio/qwen3-7-plus>

## Closed Provider output

The supplier schema is the exact repository file
`LLM_TURN_OUTPUT_SCHEMA_V1.json`, SHA-256
`3f580bc66e642f9dee7666b544d77e220a86fe6656b187e8752774e5636af6e8`.
The schema name is `maya_llm_turn_output_v1`; `strict=true` and every object has
`additionalProperties=false`.

The Provider never authors Maya IDs. In particular it cannot output `claim_id`,
`evidence_id`, `query_id`, `question_id`, participant IDs or arbitrary target turn IDs.
It returns only bounded integer references into the exact ordered catalogs in the frozen
request:

- `used_evidence_refs[]` indexes the current request's evidence catalog;
- `target_turn_ref` and `target_claim_ref` index visible prior-turn catalogs;
- `target_participant_ref` indexes the allowed next-question target catalog;
- `answered_required_question` is a boolean; the server maps `true` only to the one
  assigned pending question.

The server rejects an out-of-range reference, maps valid references to its own IDs,
requires every `claim_text` to be an exact speech substring, derives UTF-16 spans and
claim IDs, then applies the existing RuleSet, EvidenceTrace and cross-Snapshot validators.
Opening/exchange/final field rules remain those of
`ordered_multi_expert_mutual_learning_v1`; the JSON Schema does not replace phase
validation.

A successful HTTP response must have exactly one choice, a non-empty assistant content
string, the fixed model identity, non-negative integer usage and a supported finish
reason. Content is parsed as JSON and validated again locally against the exact schema.
Missing/extra fields, refusal, tool output, wrong model, malformed usage, invalid JSON,
schema failure, RuleSet failure or Evidence failure never reaches `final_ready`.

## Outbound privacy boundary

Before manifest persistence and again immediately before `sending`, the server scans the
exact two messages and field paths. The allowlist is limited to the data classes in
ProviderDataCallV1. It rejects credentials, authorization material, workspace values,
student/user/member identity tokens, names, nicknames, email/phone/UUID-shaped private
values, teacher notes, raw `AGENT.md`, source filenames/paths and fields outside the
allowlist.

Identity tokens come from the authoritative course/group/member graph, not a caller
default. They are passed into the Persona provider-view builder and the final exact
message scanner. A rejection occurs before manifest, operation, reservation or network
I/O and returns a safe code without the matched text.

The export manifest contains hashes and the approved field classes, not raw messages.
Teacher disclosure remains the only browser surface that names the supplier. Ordinary
REST and WebSocket payloads expose only safe retry/status codes.

## Durable operation and atomic publication

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
retried. An accepted complete stage can be validated/published locally. Only a proven
`not_sent` attempt may create attempt 2, and only within the frozen two-attempt limit.

## Budget buckets and migration 0014

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
Each request also retains the PromptBudgetV1 32,000-input-token, 96-KiB canonical-user,
1,500-output-token and CNY 0.15 ceilings. Attempt 2 consumes a call and budget; it is not
free. The ninth Gate-fixture call or any concurrent over-allocation fails before send.

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

## Teacher confirmation and retry

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
screen, confirms by policy/manifest/revision CAS, then explicitly retries the pending
non-terminal turn. Confirmation-required and proven-not-sent states leave the Debate
running; ordinary WS carries only the safe code.

## Tokenizer and retry continuity

The first real LLM attempt requires a reviewed supplier-compatible local tokenizer with
immutable ID and asset hash. UTF-8 conservative counting may reject preparation but
cannot authorize a real request. Attempt 2 must use the same tokenizer object identity,
ID/hash, exact base request, retrieval receipts, rule/persona/transcript hashes and model
configuration. Structure repair may add only the frozen safe code and JSON pointer list.
No retrieval or identity-bearing text is added.

## G1 authorization tests

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
12. legacy RuleSets, Mock LLM, Replay and historical turns remain unchanged.

Only a subsequent Sol High `PASS / P0=0 / P1=0` on this contract authorizes Luna to
implement W4-LLM-A. No real LLM request is part of G1/G2 because the prior account
preflight cannot be repeated.
