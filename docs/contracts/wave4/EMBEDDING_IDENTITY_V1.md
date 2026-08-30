# EmbeddingIdentityV1

Status: `FROZEN / REAL DIMENSION 1024 / IMPLEMENTATION IN PROGRESS`

## Closed identities

Maya has exactly two allowed Embedding identities:

| Purpose                       | Provider    | Model               | Region       | Dimension | Policy version |
| ----------------------------- | ----------- | ------------------- | ------------ | --------: | -------------- |
| deterministic Mock/CI/history | `mock`      | `mock-sha256-v1`    | `local`      |       256 | `w4-mock-v1`   |
| formal real RAG               | `dashscope` | `text-embedding-v4` | `cn-beijing` |      1024 | `w4-embed-v1`  |

Model name or vector length alone never establishes compatibility. SnapshotBuild,
frozen Provider request, sanitized accepted stage, KnowledgeSnapshot, every vector row
and query embedding must agree on all five identity fields.

## Request and response

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

## Persistence and history

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

## Query compatibility

Before scoring, the query embedding identity must equal the selected Snapshot identity
on provider, model, region, dimension and policy version. The following all fail closed:

- Mock 256 query against real 1024 Snapshot;
- real 1024 query against Mock 256 Snapshot;
- same dimension but different provider/model/policy;
- malformed/mixed vector rows inside one Snapshot.

The published Snapshot identity—not the browser and not a provider default—selects the
query adapter. Every real query call still requires its own exact ProviderDataCall
policy/export/budget/failure boundary.

## Gate evidence

The earlier one-batch 256 account preflight remains basic API evidence only. Formal
1024 preflight may run once after fake-transport tests, full local checks and independent
Sol High P0/P1 closure. A successful 1024 request signs only
`REAL EMBEDDING 1024 PREFLIGHT PASS`; W4-EMBED additionally requires Maya publication,
query, retrieval, Evidence receipt, teacher confirmation, budget, restart and browser
G3 evidence.
