# PromptBudgetV1 and PromptRequestV1

Status: `FROZEN CANDIDATE / NOT IMPLEMENTED`

## Logical request

The Provider-visible request has exactly two messages:

1. one versioned system message containing the platform priority rules exactly once;
2. one canonical JSON user message containing `prompt_request_v1`.

The audit record stores `rule_set_id` and `rule_set_hash`, not a second Provider-visible
copy of the prose rules. `prompt_request_v1` contains:

- debate/turn/rule/phase identifiers and server-owned schedule fields;
- topic and assigned stance;
- one `persona_provider_view_v1`; raw `AGENT.md` is absent;
- the complete exact speech of every predecessor turn, in turn-index order, exactly
  once each, plus necessary public structured fields and transcript hash;
- the pending question once;
- a query catalog and a deduplicated evidence catalog. Each evidence excerpt appears
  once and queries refer to evidence IDs;
- the closed StructuredTurnResult + EvidenceTrace output schema identifier.

Other Agents' Persona, snapshot ID, teacher-only notes, user identity and private
drafts are absent. Complete predecessor speech may not be summarized, truncated,
replaced by `turn_summary` or fetched through an unversioned provider-side state.

## Hard limits

For `llm_debate_turn_v1`:

- maximum serialized input: 32,000 model tokens before send;
- maximum canonical request bytes: 96 KiB before send;
- maximum requested output: 1,500 model tokens;
- maximum attempts per turn: 2;
- maximum LLM calls for a 5-Agent × 2-round debate: 20;
- maximum estimated charge: CNY 0.15 per request and CNY 3.00 per debate;
- any count or estimate over the limit fails before network I/O with a safe budget
  code; the turn remains unpublished and Mock is not mislabeled as real output.

W4-LLM-A must pin the supplier-compatible local tokenizer and its asset hash. Before
that tokenizer can authorize a request, a conservative fallback counts each UTF-8 byte
as one token; it may reject an otherwise valid request but cannot undercount it. The
Provider's returned usage is evidence after send, never the only budget guard.

There is deliberately no percentage-reduction KPI. Acceptance measures the serialized
baseline and final request, proves the duplicate classes are absent, and enforces the
hard limits while preserving the full transcript.

## Attempt and retrieval semantics

Retrieval executes once and freezes the ordered query/receipt set before the first LLM
call. Attempt 2 reuses the exact receipt hash, transcript hash, Persona hash, rule hash,
model configuration and base request.

Attempt 2 is allowed only for:

- a Provider response known to have completed but failing closed JSON/schema/rule
  validation: append only a stable safe error code and JSON pointer list as
  `repair_feedback`;
- a transport failure that the adapter can prove occurred before the supplier accepted
  the request: resend the identical frozen request once.

Retrieval may run a second time only when the first retrieval ended in a technical
failure before any LLM request. That is a retrieval retry, not a structure repair.

No automatic retry is allowed for an uncertain accepted/billed outcome, timeout after
acceptance cannot be excluded, budget failure, authentication/permission error, safety
refusal, unavailable fixed model, cross-snapshot evidence, stale generation fence or a
changed transcript/Persona/rule hash. These fail closed and require an operator-visible
safe state, not hidden continuation.

## Usage ledger

Every external attempt records server-side:

`provider_operation`, fixed `model_version`, `prompt_contract_version`,
`persona_spec_hash`, `rule_set_hash`, `transcript_hash`, `receipt_hash`, `input_tokens`,
`cached_input_tokens`, `output_tokens`, `attempt_no`, `retrieval_reused`, request
acceptance state, safe error code, price-card version, estimated cost and nullable
reconciled actual cost.

Before network I/O, the attempt and its worst-case count/cost allowance are atomically
reserved through the durable state machine in ProviderDataCallV1. A read-then-send
budget check is forbidden. Concurrent workers therefore cannot each observe spare
budget and exceed the Debate cap.

Supplier request IDs are encrypted/restricted operations data and never enter normal
API responses. API keys never enter the database or logs. There is no Wave 4 cost
dashboard or teacher/operator cost-display feature; the ledger exists for Gate audit,
budget enforcement and incident recovery only.
