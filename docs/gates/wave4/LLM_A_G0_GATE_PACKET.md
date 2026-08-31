# W4-LLM-A G0 Gate Packet

Status: `G0-S SOL PASS / FAKE-TRANSPORT G1 AUTHORIZED / REAL LLM CALLS 0`

The historical independent structured-LLM account preflight is availability evidence
only and must not be repeated. This packet authorizes no Provider call.

## Audit history

Sol High reviewed the pre-existing contracts and exact code baseline and returned:

`CHANGES_REQUIRED / P0=0 / P1=6 / P2=0`

The six design findings were:

1. no exact Beijing Chat endpoint/body/timeout/redirect/request-hash contract;
2. only an output schema ID, with Provider-authored Maya IDs still implied;
3. no durable accepted LLM stage or atomic Turn/Evidence/usage success boundary;
4. one budget row per scope, so Debate Embedding and LLM caps could collide;
5. no exact per-turn owner-bound teacher discovery/confirmation/retry design;
6. no exact-message privacy scan or same-tokenizer identity across attempts.

The first repair re-audit closed those six categories but found four remaining P1
ambiguities. The current contract additionally freezes:

1. `-1` as a non-index sentinel only for whole-turn engagement and `question.mode=none`,
   with exact mode/target/text cross-rules and rejection before indexing;
2. the exact Chat choice/role/finish/usage envelope: only `finish_reason=stop` can enter
   product validation; `length` is staged repairable and every refusal/tool/filter/
   wrong-model/usage failure is terminal;
3. automatic attempt 2 only under a teacher-confirmed two-attempt/full-cost manifest,
   with a closed transport classification table for pre-byte connect, write/read
   uncertainty and every HTTP response;
4. a 1,510-token worst-case output reservation, immutable Decimal price-card fields,
   cached-token fallback, upward CNY rounding, usage overrun handling and permanent
   worst-case allocation for every accepted/unknown attempt.

The next re-audit found one final P1: structure-repair feedback was not part of the
ProviderDataCall allowlist or teacher-confirmed manifest. The current candidate adds a
closed `server_authored_structure_repair_feedback` class and binds the finite
`repair_feedback_v1` grammar/hash
`d5b81d460ecd713f4b3d52b5732efc935b63455c2a29b5a5ab2471b17d00050b` before
attempt 1. Attempt 2 adds only that field, receives its own request hash and is
rescanned; rejected values and messages can never be copied.

## Repair authority

The current candidate freezes the missing decisions in:

- `docs/contracts/wave4/LLM_A_RUNTIME_V1.md`;
- `docs/contracts/wave4/LLM_TURN_OUTPUT_SCHEMA_V1.json` with SHA-256
  `1c401df76683a38aaa2206ea49df181d37aaf470e57b37f05c534f543f8eff7c`;
- `docs/contracts/wave4/LLM_REPAIR_FEEDBACK_V1.json` with SHA-256
  `d5b81d460ecd713f4b3d52b5732efc935b63455c2a29b5a5ab2471b17d00050b`;
- revised `PROVIDER_DATA_CALL_V1.md` and `PROMPT_BUDGET_V1.md` cross-references.

The exact request is one no-redirect Beijing Chat Completion using
`qwen3.7-plus-2026-05-26`, two canonical messages, `enable_thinking=false`,
`stream=false`, `temperature=0.2`, `top_p=0.8`, `max_completion_tokens=1500`, `n=1`
and strict JSON Schema. No tools, search, Provider conversation state or fallback exists.

The Provider output uses bounded catalog references instead of claim/evidence/query/
question/participant IDs. The server maps references, derives IDs and speech spans, and
then runs the existing phase, EvidenceTrace and Snapshot validators.

Migration `0014_llm_runtime_budget_buckets` is required before adapter/runtime work. It
adds operation-isolated budget buckets, exact Debate/Turn manifest owners and accepted
LLM stage/usage records while preserving every 0001–0013 row and historical Debate.

Each exact turn manifest is teacher-discoverable only through Debate/course ownership.
Before confirmation there is no reservation or call. Confirmation-required and proven
not-sent remain non-terminal and need explicit retry. Accepted output is staged before
local validation; Turn, EvidenceTrace, usage and operation success publish atomically.
Startup and acceptance-unknown perform zero calls.

Actual two-message text is scanned before manifest and again before send using identity
tokens from the authoritative course/member graph. The real request requires one pinned
supplier-compatible tokenizer; the conservative fallback can reject but cannot authorize
a real call. Attempt 2 preserves every base hash, receipt and tokenizer identity.

## Gate caps

- 2 Agents × 2 rounds: at most 8 charged LLM attempts and CNY 1.20;
- 5 Agents × 2 rounds: at most 20 charged attempts and CNY 3.00;
- each request: 32,000 input tokens, 96 KiB canonical user bytes, 1,500 requested output
  tokens and CNY 0.15;
- LLM-A, Embedding query, LLM-B, TTS and Voice buckets are non-transferable.

## G0-S result

Sol High verified the original six findings, the four retry/response/budget follow-ups
and the final repair-feedback allowlist/manifest boundary on exact clean SHA `4182d1a`.
Result: `PASS / P0=0 / P1=0 / P2=0`.

This authorizes Issues #22–#24 for migration, adapter and runtime work with fake
transports only. Workers cannot sign G2 and no real request is part of implementation
acceptance; the historical LLM preflight remains non-repeatable.
