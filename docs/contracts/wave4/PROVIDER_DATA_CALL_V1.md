# ProviderDataCallV1

Status: `FROZEN CANDIDATE / NOT IMPLEMENTED / REAL CALLS 0`

## Fixed supplier resources

The intended local Demo supplier is Alibaba Cloud Model Studio in the existing
`cn-beijing` workspace. Fixed identifiers are:

| Operation        | Fixed resource                                        | Mode                                                            |
| ---------------- | ----------------------------------------------------- | --------------------------------------------------------------- |
| Debate LLM       | `qwen3.7-plus-2026-05-26`                             | non-thinking, structured output, temperature `0.2`, top_p `0.8` |
| Text embedding   | `text-embedding-v4`, dimension `256`                  | synchronous, max 10 inputs/request                              |
| Voice-clone TTS  | `qwen3-tts-vc-2026-01-22`                             | HTTP, language `English`                                        |
| Voice enrollment | `qwen-voice-enrollment` targeting the fixed TTS model | separate TTS Gate only                                          |

`latest`, unversioned fallback, automatic model upgrade and cross-region fallback are
forbidden. Model unavailability requires a contract revision.

Official references checked 2026-08-30:

- <https://help.aliyun.com/zh/model-studio/text-generation-model>
- <https://help.aliyun.com/zh/model-studio/embedding>
- <https://help.aliyun.com/zh/model-studio/tts-model>
- <https://help.aliyun.com/zh/model-studio/model-pricing>

The checked documentation reports structured output for the fixed Qwen generation
family, 256-dimensional support and a ten-input batch limit for `text-embedding-v4`,
and English support for the fixed voice-clone TTS snapshot. Price values are a
preflight card, not UI content: embedding CNY 0.5/million input tokens and TTS CNY
0.8/10,000 billed characters were the Beijing list prices at review time. The LLM Gate
must refresh its price card from the official account/region before the first request;
if that refresh makes a frozen cap impossible, it stops.

## External data matrix

| Data                                 |            LLM |      Embedding |                 TTS | Rule                                   |
| ------------------------------------ | -------------: | -------------: | ------------------: | -------------------------------------- |
| topic and platform rules             |            yes |     query only |                  no | no user identity                       |
| confirmed structured current Persona |            yes |             no |                  no | raw `AGENT.md` never sent              |
| complete predecessor speech          |            yes |             no | current speech only | public debate text only                |
| current evidence excerpt/query       |            yes |            yes |                  no | only confirmed exportable snapshot     |
| opaque evidence/query/turn IDs       |            yes |             no |                  no | supplier cannot resolve local identity |
| source filename/absolute path        |             no |             no |                  no | server resolves display metadata       |
| teacher note                         |             no |             no |                  no | internal only                          |
| student name/user ID/nickname        |             no |             no |                  no | forbidden                              |
| audio/voice sample                   |             no |             no |    speech text only | enrollment is separate Gate            |
| API key/workspace ID                 | transport only | transport only |      transport only | server secret; never prompt/log/DTO    |

Before real LLM/Embedding, the exact KnowledgeSnapshot must have a teacher-confirmed
`external_export_allowed` record covering its hashes and asserting that it contains no
secret, credential, student identity, nickname, private audio transcript or unrelated
personal data. Confirmation is invalidated by any new snapshot; published immutable
snapshots are never modified in place.

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
fixed model, region, data-export confirmation, token/character estimate, cumulative
count/cost and generation fence. Failure produces a safe local code with zero request.

Timeouts and broken connections are classified as `not_sent`, `accepted`, or
`acceptance_unknown`. Only `not_sent` may use the one frozen retry allowed by the
operation contract. `acceptance_unknown` consumes the call/cost ceiling, stores no
generated product result and requires reconciliation; it is never automatically
retried. Supplier error bodies are redacted to stable safe codes.

Standing user authorization covers later local/private GitHub implementation and
bounded billed evidence under these Gates. It does not permit exceeding a cap, changing
model/region/data class, sending forbidden identity data or skipping the exact Gate.
