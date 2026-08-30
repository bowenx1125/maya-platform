# PersonaSpecV1

Status: `FROZEN / SECOND P1 REPAIR ACTIVE / LOCAL G1.5 PASS / REAL CALLS 0`

## Teaching contract

Students write `AGENT.md` because its confirmed structured meaning must cause visible,
explainable changes in tone, value priority, argument pattern, concession style,
question style and debate strategy. Persona must never change platform rules, debate
order, permissions, evidence identity, factual source bytes, output schema or safety
validation.

The raw Markdown is immutable authorship and remains available for preview, download,
teacher review and version comparison. A real LLM receives only the confirmed
structured provider view, never raw `AGENT.md`.

## Strict Markdown grammar

The deterministic compiler accepts UTF-8 Markdown no longer than 12,000 characters
after CRLF normalization. The only accepted document shape is:

```markdown
# <Agent display name>

## Identity

- Role: <text>
- Historical or cultural context: <text>

## Cultural lens

- <item>

## Core values

- <item>

## Initial position

<one or more paragraphs>

## Speaking style

- Tone: <text>
- Argument pattern: <text>
- Concession style: <text>
- Question style: <text>

## Debate strategy

- <item>

## Boundaries

- <item>
```

Rules are exact after trimming surrounding whitespace:

- one H1 is required and must equal the Agent display name;
- all seven H2 sections are required exactly once and in the shown order;
- field labels are ASCII and case-sensitive;
- Cultural lens, Core values, Debate strategy and Boundaries contain only flat bullet
  items; each list contains 1–8 unique items;
- Identity and Speaking style contain only their named flat bullet fields;
- Initial position contains plain Markdown paragraphs but no headings, HTML or links;
- prose outside the defined locations, unknown/duplicate headings, unknown fields,
  nested lists, HTML, links and empty values are compile errors, not ignored content;
- Markdown emphasis and inline code are reduced to their visible text. Their delimiters
  never become instructions.

Scalar limits are: name 80, role 120, cultural context 1,000, initial position 1,000,
and each style field 240 characters. Every list item is 1–240 characters. Control and
format characters other than normalized newline/tab are rejected.

## Closed stored schema

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

## Compile and confirmation state machine

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

## Provider view and causal acceptance

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
