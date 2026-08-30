# Maya Platform

This file is the portable authority index for Maya Platform. It is intentionally
short. Current facts live in [PROJECT_STATUS.md](PROJECT_STATUS.md); historical
discussion is never a default implementation input.

## 1. Product goal

Maya is a local-first teaching platform where student groups build culture-focused
Agents from an authored persona, an immutable Markdown RAG snapshot, a constrained
3D avatar and an optional voice. A teacher selects 2–5 published Agents in click
order, runs a fixed two-round English debate, opens anonymous classroom interaction,
and generates a civilization mutual-learning report.

The Demo principle is: complete interfaces, simple internals, and one demonstrable
main flow. Mock evidence, real-provider evidence and human acceptance must always be
reported separately.

## 2. Authority order

When two sources conflict, use this order:

1. the user's latest explicit decision;
2. [PROJECT_STATUS.md](PROJECT_STATUS.md);
3. the active Issue and Gate Packet named by `PROJECT_STATUS.md`;
4. current machine contracts under [contracts/](contracts/) and active human
   contracts under [docs/contracts/](docs/contracts/);
5. accepted ADRs under [docs/adr/](docs/adr/);
6. [ARCHITECTURE.md](ARCHITECTURE.md);
7. historical Gate packets, worklogs, original requirements and archives.

Historical files preserve evidence. They never override a later active Gate.

## 3. Required reading

The main integration window reads this file and `PROJECT_STATUS.md`, then opens only
the active Gate and directly relevant contracts/code.

An implementation or audit worker reads only:

1. `PROJECT_STATUS.md`;
2. its Issue or Task Packet;
3. the ADRs/contracts named by that packet;
4. its assigned files or candidate diff.

Workers do not read `docs/worklog/` or `docs/archive/` unless the task explicitly
requires historical evidence.

## 4. Frozen Demo boundaries

- Organization: one seeded course, one teacher and two three-student groups. Course
  and group membership are read-only in the Demo.
- Authorization: students are scoped to their group; teachers see published
  immutable history but never drafts; cross-group objects are returned as not found.
- Agent versions: published/superseded versions and their KnowledgeSnapshots are
  immutable. A new version is required for new persona or knowledge.
- Knowledge: RAG accepts Markdown only. A draft explicitly enables group documents;
  publishing freezes source bytes, chunks, vector metadata and source lineage.
- Debate: 2–5 current published Agents receive slots A–E in teacher click order.
  Legacy RuleSets retain exactly two rounds; the versioned mutual-learning RuleSet
  supports 2–5 rounds. The rules engine, not the model, chooses the order.
- Context: visibility is RuleSet-versioned. A mutual-learning turn receives the
  complete text of every public/final-ready turn from earlier rounds, exactly once,
  and never receives a same-round turn. Legacy RuleSets retain their frozen
  lower-turn-index behavior. Wave 4 may remove duplicate serialization and reuse
  stable retrieval on a structural retry, but it must not summarize visible speech.
- Evidence: only server-selected receipts actually used by a validated turn may be
  public sources. `no_match` uses general reasoning with no source.
- Playback: the ordinary teacher surface is Start / Next / Replay. Pause/resume is a
  hidden recovery primitive. Replay uses retained immutable content and never calls
  RAG, LLM, Translation or TTS generation.
- Interaction: public vote and named raw barrage are independent. Maya receives no
  nickname or raw barrage list; counts are computed by code from frozen rows.
- Language: authoritative debate speech and reports are English. Chinese is an
  on-demand derived test representation and never re-enters RAG, debate, TTS or
  report inputs.
- Runtime: Next.js + FastAPI + SQLite/local files + WebSocket behind one Caddy origin.
  No Redis, Celery, PostgreSQL or cloud storage is part of the local Demo.

## 5. Wave 4 decisions

- `AGENT.md` remains the student's immutable raw authorship. New versions will also
  carry a student-confirmed, extraction-only structured Persona; the compiler must
  not invent, improve or silently discard persona content.
- Claim-level Evidence Trace is provenance, not automatic fact verification. The
  server derives speech spans and binds claims to immutable `TurnSource` rows.
- Prompt work keeps the complete RuleSet-visible transcript: all earlier-round speech
  for mutual learning and the frozen legacy predecessor set for legacy RuleSets. It
  removes known duplicate persona/rules and reuses valid frozen retrieval receipts for
  structure-only retry.
- A numeric Token-reduction KPI and a teacher/operator cost-display feature are not
  Wave 4 tasks.
- Real Provider work remains separated by Gate. A valid key, voice enrollment,
  synthesis, model output and human acceptance are distinct evidence.

## 6. Engineering workflow

Intermediate Wave 4 coding changes follow:

`Issue -> local branch -> independent worktree -> one implementation owner -> local checks -> Sol High read-only audit -> fix/retest loop -> main-window integration`

Only the complete Wave 4 integration candidate is pushed as a Pull Request. That exact
head runs one GitHub CI through the `pull_request` workflow; after PASS the same audited
head fast-forwards canonical `main`. Intermediate branches are not pushed and do not
consume duplicate push/PR CI runs.

Shared files such as models, migrations, OpenAPI, WebSocket schemas, provider factory,
generated clients and root status are owned by the main window or an explicitly named
integrator. A worker never approves its own Gate.

Gate order is:

`G0 contract -> G0-S design challenge -> G1 implementation -> G1.5 deterministic checks -> G2 independent audit -> G3 module runtime -> G4 integration -> G5 real-service/human acceptance`

Problems are debugged and retested inside the current Gate until its frozen acceptance
criteria pass. Tests or contracts are never weakened to manufacture a pass.

## 7. Safety and scope

- Never commit API keys, `.env`, private accounts, student audio, runtime databases,
  generated media or private reference code.
- The browser uses platform DTOs only. Supplier names, model IDs, external resource
  IDs, credentials and private paths remain server-side.
- Do not copy source fragments from reference repositories. References are read-only
  design and test inputs.
- Real calls must satisfy the active Provider Gate's model, input, call-count, cost,
  timeout, privacy, retry and stop conditions before the first request.
- Docker and SQLite must not open the same live bind-mounted WAL from both host and
  container. Inspect through the API/container while the backend is running.

## 8. Document map

- [PROJECT_STATUS.md](PROJECT_STATUS.md): current phase, last signed baseline, active
  branch/PR, evidence and next Gate. Git/PR/CI owns the exact candidate SHA so the
  document does not make a self-referential SHA claim.
- [ARCHITECTURE.md](ARCHITECTURE.md): stable system and data boundaries.
- [contracts/](contracts/): current machine-readable OpenAPI/WebSocket contracts.
- [docs/contracts/](docs/contracts/): human contracts and baseline provenance.
- [docs/adr/](docs/adr/): one durable decision per file.
- [docs/gates/](docs/gates/): Gate packets and acceptance evidence.
- [docs/requirements/original.md](docs/requirements/original.md): historical source
  requirements only; not the current implementation contract.
- [docs/worklog/](docs/worklog/): historical execution record, excluded from normal
  task context.
- [docs/archive/PROJECT_MONOLITH_2026-08-30.md](docs/archive/PROJECT_MONOLITH_2026-08-30.md):
  exact pre-Wave-4 continuity monolith. Its checksum is stored beside it.
