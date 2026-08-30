# ProviderDataCallV1

Status: `FROZEN / CONTROL+LEDGER IMPLEMENTED CANDIDATE / RUNTIME GATES INCOMPLETE / REAL CALLS 0`

## Fixed supplier resources

The intended local Demo supplier is Alibaba Cloud Model Studio in the existing
`cn-beijing` workspace. Fixed identifiers are:

| Operation        | Fixed resource                                        | Mode                                                                    |
| ---------------- | ----------------------------------------------------- | ----------------------------------------------------------------------- |
| Debate LLM       | `qwen3.7-plus-2026-05-26`                             | non-thinking, structured output, temperature `0.2`, top_p `0.8`         |
| Text embedding   | `text-embedding-v4`, dimension `256`                  | synchronous; max 10 inputs, 8,000 tokens/item and 30,000 tokens/request |
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
family, 256-dimensional support and a ten-input batch limit for `text-embedding-v4`,
and English support for the fixed voice-clone TTS snapshot. Price values are a
preflight card, not UI content: embedding CNY 0.5/million input tokens and TTS CNY
0.8/10,000 billed characters were the Beijing list prices at review time. The LLM Gate
must refresh its price card from the official account/region before the first request;
if that refresh makes a frozen cap impossible, it stops.

The official Beijing embedding table also reports 33,000 tokens as its batch ceiling;
Maya deliberately freezes the lower 30,000-token request ceiling and an 8,000-token
per-item ceiling. W4-EMBED pins a supplier-compatible local tokenizer and asset hash.
Until that tokenizer can authorize a request, conservative preflight counts each UTF-8
byte as one token. It may reject safe text but cannot undercount a long unbroken input.

## Supplier data-processing preflight

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

## External data matrix

| Data                                 |            LLM |      Embedding |                 TTS | Rule                                   |
| ------------------------------------ | -------------: | -------------: | ------------------: | -------------------------------------- |
| topic and platform rules             |            yes |     query only |                  no | no user identity                       |
| confirmed structured current Persona |            yes |             no |                  no | raw `AGENT.md` never sent              |
| complete RuleSet-visible prior speech |            yes |             no | current speech only | mutual learning excludes same round    |
| current evidence excerpt/query       |            yes |            yes |                  no | only confirmed exportable snapshot     |
| opaque evidence/query/turn IDs       |            yes |             no |                  no | supplier cannot resolve local identity |
| source filename/absolute path        |             no |             no |                  no | server resolves display metadata       |
| teacher note                         |             no |             no |                  no | internal only                          |
| student name/user ID/nickname        |             no |             no |                  no | forbidden                              |
| audio/voice sample                   |             no |             no |    speech text only | enrollment is separate Gate            |
| API key/workspace ID                 | transport only | transport only |      transport only | server secret; never prompt/log/DTO    |

Before real LLM/Embedding, a teacher confirms an exact export manifest by CAS. The
manifest binds the PersonaSpec hash, the immutable SnapshotBuild candidate described
below, ProviderPolicySnapshot hash, operation types, data classification and a
declaration that no field contains a secret, credential, student identity/name,
nickname, private audio transcript or unrelated personal data. Any hash/revision or
policy change invalidates confirmation. Published immutable snapshots are never
modified in place.

## Pre-provider SnapshotBuild lifecycle

A real embedding call cannot depend on a KnowledgeSnapshot that is created only after
embedding. W4-EMBED therefore introduces an internal, non-public `SnapshotBuildV1`
before network I/O. Preparation freezes:

- planned AgentVersion and KnowledgeSnapshot UUIDs;
- exact draft revision and confirmed PersonaSpec hash;
- normalized source bytes, document IDs/order, source/content hashes and total size;
- chunking contract/version plus every chunk ID, source offsets, text and hash;
- fixed embedding model/dimension and the canonical build-manifest hash.

The build is not a published KnowledgeSnapshot, cannot be selected by Debate setup and
contains no vector result yet. The teacher's `external_export_allowed` CAS signs its
exact manifest hash. A changed draft/Persona/source cannot reuse the confirmation or
publish the build.

Before the first request, chunks are packed deterministically by document order then
chunk index using a stable greedy algorithm. Each item must be at most 8,000 counted
tokens; each batch must contain at most 10 items and 30,000 counted tokens. The complete
plan must fit at most 20 requests and 120,000 total counted tokens. Count, request and
price-card allowances for the whole plan are reserved atomically; any single or total
overflow fails with zero network calls. Every planned request, including `not_sent` or
`acceptance_unknown` attempts, is accounted against the frozen request/cost rules as
specified below.

The durable operation state machine is:

`prepared -> export_confirmed -> sending -> accepted -> succeeded`

with terminal/recovery states `not_sent`, `acceptance_unknown`, `failed`, `abandoned`.
Every batch binds the build hash, batch index, chunk hashes, attempt, allowance and
usage record. `not_sent` may retry the same frozen batch within the cap.
`acceptance_unknown` consumes its request/cost allowance, never retries automatically,
and retains the non-public build until an operator reconciles a retrievable supplier
result or marks it `abandoned`. Abandonment creates no AgentVersion/KnowledgeSnapshot;
future work needs a new build and confirmation. Staged bytes are deleted only after a
terminal outcome and the existing file-recovery journal has recorded cleanup.

On success, the server verifies response count/order, dimension 256, finite numeric
values, fixed model key and every batch/build hash. One local transaction then creates
the immutable AgentVersion/KnowledgeSnapshot/vector rows from that exact build and
marks publication complete. Any validation, CAS or commit failure publishes nothing;
no existing published version or snapshot is changed. Mock embedding uses the same
build/publish invariants without external-export confirmation or network states.

## Operation caps

| Gate operation                |           Request cap | Input/output cap               | Estimated charge cap |
| ----------------------------- | --------------------: | ------------------------------ | -------------------: |
| one new real snapshot         | 20 embedding requests | 120,000 input tokens total     |             CNY 0.10 |
| W4-LLM-A 2-Agent × 2-round G3 |           8 LLM calls | PromptBudgetV1 per call        |             CNY 1.20 |
| 5-Agent × 2-round debate      |          20 LLM calls | PromptBudgetV1 per call        |             CNY 3.00 |
| one real TTS technical Gate   |     2 synthesis calls | 2,400 billed characters total  |             CNY 0.20 |
| one 5-Agent × 2-round TTS run |    10 synthesis calls | 15,000 billed characters total |             CNY 1.20 |
| new voice enrollment          |            1 creation | one approved sample            |             CNY 0.01 |

W4-LLM-B adds at most two calls for one barrage-insight snapshot and two calls for one
Maya report revision; it has a separate CNY 0.60 cap and cannot consume the Debate LLM
budget silently. Translation is outside this contract and remains Mock/disabled.

## Fail-closed and uncertainty

Pre-send validates active Gate ID/SHA, operation allowance, selector composition,
fixed model, region, allowed account product, current ProviderPolicySnapshot, exact
export-manifest/build confirmation, token/character estimate, cumulative count/cost
and generation fence. Failure produces a safe local code with zero request.

Every external request uses one shared durable reservation contract:

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
or an incomplete accepted response becomes `acceptance_unknown`; it is never retried
automatically. A complete staged accepted response resumes validation/local commit
without another Provider request. Recovery is idempotent under the unique key and
generation/build hashes.

Timeouts and broken connections are classified as `not_sent`, `accepted`, or
`acceptance_unknown`. Only `not_sent` may use the one frozen retry allowed by the
operation contract. `acceptance_unknown` consumes the call/cost ceiling, stores no
generated product result and requires reconciliation; it is never automatically
retried. Supplier error bodies are redacted to stable safe codes.

Standing user authorization covers later local/private GitHub implementation and
bounded billed evidence under these Gates. It does not permit exceeding a cap, changing
model/region/data class, sending forbidden identity data or skipping the exact Gate.
