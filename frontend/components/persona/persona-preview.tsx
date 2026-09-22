"use client";

import type { ReactNode } from "react";

import styles from "./persona-preview.module.css";

export type PersonaPreviewSpec = {
  schema_version?: string;
  identity: {
    name: string;
    role: string;
    historical_or_cultural_context: string;
  };
  cultural_lens: readonly string[];
  core_values: readonly string[];
  initial_position: string;
  speaking_style: {
    tone: string;
    argument_pattern: string;
    concession_style: string;
    question_style: string;
  };
  /** Present only on the immutable seven-section V1 projection. */
  debate_strategy?: readonly string[];
  /** Present only on the immutable seven-section V1 projection. */
  boundaries?: readonly string[];
  source_agent_md_hash?: string;
  compiler_version?: string;
};

export type PersonaPreviewSpecV1 = PersonaPreviewSpec & {
  debate_strategy: readonly string[];
  boundaries: readonly string[];
};

export type PersonaPreviewSpecV2 = Omit<
  PersonaPreviewSpec,
  "debate_strategy" | "boundaries"
> & {
  schema_version?: "persona_spec_v2";
};

export type PersonaPreviewDiagnostic = {
  code?: string;
  message: string;
  line?: number | null;
  field?: string | null;
};

export type PersonaDiffKey =
  | "tone"
  | "value_priority"
  | "argument_pattern"
  | "concession_style"
  | "question_style"
  | "debate_strategy";

export type PersonaDiff = {
  key: PersonaDiffKey;
  label: string;
  before: string;
  after: string;
  changed: boolean;
};

export type MockPersonaTeachingDimensions = {
  tone: string;
  value_priority: string;
  argument_pattern: string;
  concession_style: string;
  question_style: string;
  /** V1 only; V2 has no synthetic strategy field. */
  debate_strategy?: string;
};

export type MockPersonaTeachingDimensionsV2 = Omit<
  MockPersonaTeachingDimensions,
  "debate_strategy"
>;

export type MockPersonaResponse = {
  schema_version: "persona_mock_response_v1";
  stance: string;
  speech: string;
  position_summary: string;
  teaching_dimensions: MockPersonaTeachingDimensions;
  evidence_ids: readonly string[];
  rule_set_id: "persona_mock_teaching_v1";
  seed: number;
};

export type MockPersonaResponsePair = {
  topic: string;
  stance: string;
  seed: number;
  evidence_ids: readonly string[];
  first: MockPersonaResponse;
  second: MockPersonaResponse;
};

const mockResponseTopic = "How should a community share a scarce resource?";
// The preview intentionally uses no retrieval result.  This keeps the demo
// honest: general reasoning must not display fabricated source identifiers.
const mockResponseEvidenceIds = [] as const;

/** Build the deterministic student-facing Mock response from the stored Persona. */
export function buildMockPersonaResponse(
  persona: PersonaPreviewSpec,
  options: {
    topic: string;
    evidenceIds: readonly string[];
    stance: string;
    seed: number;
  },
): MockPersonaResponse {
  const dimensions: MockPersonaTeachingDimensions = {
    tone: persona.speaking_style.tone,
    value_priority: persona.core_values[0] ?? "the stated values",
    argument_pattern: persona.speaking_style.argument_pattern,
    concession_style: persona.speaking_style.concession_style,
    question_style: persona.speaking_style.question_style,
    ...(persona.debate_strategy?.[0]
      ? { debate_strategy: persona.debate_strategy[0] }
      : {}),
  };
  const openings = [
    "I begin by locating the question in its wider context.",
    "I begin by naming the practical choice before us.",
    "I begin by making the underlying responsibility explicit.",
    "I begin by separating what is known from what is valued.",
  ];
  const opening = openings[Math.abs(options.seed) % openings.length];
  const grounding = options.evidenceIds.length
    ? `I draw on the supplied evidence in its fixed order (${options.evidenceIds.length} item(s)).`
    : "I have no matching evidence, so this is general reasoning.";
  const speech = [
    opening,
    `My tone is ${dimensions.tone}. On ${options.topic.trim()}, I prioritize ${dimensions.value_priority}.`,
    `I use this argument pattern: ${dimensions.argument_pattern}.`,
    `When another view is reasonable, I ${dimensions.concession_style}.`,
    `I ask questions in this way: ${dimensions.question_style}.`,
    grounding,
  ];
  if (dimensions.debate_strategy) {
    speech.splice(
      5,
      0,
      `My debate strategy is to ${dimensions.debate_strategy}.`,
    );
  }
  const speechText = speech.join(" ");
  return {
    schema_version: "persona_mock_response_v1",
    stance: options.stance,
    speech: speechText,
    position_summary: dimensions.debate_strategy
      ? `Prioritize ${dimensions.value_priority} by applying ${dimensions.debate_strategy}.`
      : `Prioritize ${dimensions.value_priority}.`,
    teaching_dimensions: dimensions,
    evidence_ids: [...options.evidenceIds],
    rule_set_id: "persona_mock_teaching_v1",
    seed: options.seed,
  };
}

/** Keep topic, stance, seed, receipts, RuleSet and schema fixed for comparison. */
export function buildMockPersonaResponsePair(
  first: PersonaPreviewSpec,
  second: PersonaPreviewSpec,
  options: {
    topic?: string;
    evidenceIds?: readonly string[];
    stance?: string;
    seed?: number;
  } = {},
): MockPersonaResponsePair {
  const topic = options.topic ?? mockResponseTopic;
  const evidenceIds = options.evidenceIds ?? mockResponseEvidenceIds;
  const stance = options.stance ?? "open";
  const seed = options.seed ?? 7;
  const input = { topic, evidenceIds, stance, seed };
  const firstResponse = buildMockPersonaResponse(first, input);
  const secondResponse = buildMockPersonaResponse(second, {
    ...input,
    evidenceIds: firstResponse.evidence_ids,
  });
  return {
    topic,
    stance,
    seed,
    evidence_ids: firstResponse.evidence_ids,
    first: firstResponse,
    second: secondResponse,
  };
}

const teachingDimensions: readonly {
  key: PersonaDiffKey;
  label: string;
  read: (spec: PersonaPreviewSpec) => string;
}[] = [
  { key: "tone", label: "Tone", read: (spec) => spec.speaking_style.tone },
  {
    key: "value_priority",
    label: "Value priority",
    read: (spec) => spec.core_values.join(", "),
  },
  {
    key: "argument_pattern",
    label: "Argument pattern",
    read: (spec) => spec.speaking_style.argument_pattern,
  },
  {
    key: "concession_style",
    label: "Concession style",
    read: (spec) => spec.speaking_style.concession_style,
  },
  {
    key: "question_style",
    label: "Question style",
    read: (spec) => spec.speaking_style.question_style,
  },
];

const legacyTeachingDimension = {
  key: "debate_strategy" as const,
  label: "Debate strategy",
  read: (spec: PersonaPreviewSpec) => spec.debate_strategy?.join(", ") ?? "—",
};

/** Pure canonical field comparison used by the preview and student tests. */
export function diffPersonaSpec(
  before: PersonaPreviewSpec | null | undefined,
  after: PersonaPreviewSpec | null | undefined,
): PersonaDiff[] {
  const dimensions =
    before?.debate_strategy || after?.debate_strategy
      ? [...teachingDimensions, legacyTeachingDimension]
      : teachingDimensions;
  return dimensions.map(({ key, label, read }) => {
    const beforeValue = before ? read(before) : "—";
    const afterValue = after ? read(after) : "—";
    return {
      key,
      label,
      before: beforeValue,
      after: afterValue,
      changed: beforeValue !== afterValue,
    };
  });
}

export function PersonaPreview({
  rawAgentMd,
  spec,
  previousSpec,
  diagnostics = [],
  confirmed = false,
  disabled = false,
  onCompile,
  onConfirm,
}: {
  rawAgentMd: string;
  spec?: PersonaPreviewSpec | null;
  previousSpec?: PersonaPreviewSpec | null;
  diagnostics?: readonly PersonaPreviewDiagnostic[];
  confirmed?: boolean;
  disabled?: boolean;
  onCompile?: () => void;
  onConfirm?: () => void;
}) {
  const diff = diffPersonaSpec(previousSpec, spec);
  const hasDiff = previousSpec != null && spec != null;
  const mockPair = hasDiff
    ? buildMockPersonaResponsePair(previousSpec, spec)
    : null;

  return (
    <section className="section-card" data-testid="persona-preview">
      <div className="section-card-header">
        <div>
          <h2>Persona</h2>
        </div>
        <div className={styles.statusRow}>
          <span
            className={`${styles.status} ${confirmed ? styles.statusConfirmed : spec ? styles.statusReady : styles.statusPending}`}
          >
            {confirmed ? "Confirmed" : spec ? "Ready" : "Pending"}
          </span>
          {onConfirm && spec && !confirmed ? (
            <button
              className="primary-action compact-action"
              type="button"
              onClick={onConfirm}
              disabled={disabled}
            >
              Confirm
            </button>
          ) : onCompile && !spec ? (
            <button
              className="primary-action compact-action"
              type="button"
              onClick={onCompile}
              disabled={disabled}
            >
              Compile
            </button>
          ) : null}
        </div>
      </div>
      {diagnostics.length > 0 ? (
        <div className={styles.diagnostics} role="alert">
          <strong>Persona needs attention</strong>
          {diagnostics.map((diagnostic, index) => (
            <span key={`${diagnostic.code ?? "diagnostic"}-${index}`}>
              {diagnostic.message}
              {diagnostic.line ? ` (line ${diagnostic.line})` : ""}
            </span>
          ))}
        </div>
      ) : null}
      {spec ? (
        <>
          <div className={styles.identity}>
            <strong>{spec.identity.name}</strong>
            <span>{spec.identity.role}</span>
            <p>{spec.identity.historical_or_cultural_context}</p>
          </div>
          <div className={styles.semanticGrid}>
            <PersonaField label="Cultural lens" value={spec.cultural_lens} />
            <PersonaField label="Core values" value={spec.core_values} />
            <PersonaField
              label="Initial position"
              value={spec.initial_position}
            />
            {spec.boundaries ? (
              <PersonaField label="Boundaries" value={spec.boundaries} />
            ) : null}
          </div>
          <div className={styles.semanticGrid}>
            <PersonaField label="Tone" value={spec.speaking_style.tone} />
            <PersonaField
              label="Argument pattern"
              value={spec.speaking_style.argument_pattern}
            />
            <PersonaField
              label="Concession style"
              value={spec.speaking_style.concession_style}
            />
            <PersonaField
              label="Question style"
              value={spec.speaking_style.question_style}
            />
            {spec.debate_strategy ? (
              <PersonaField
                label="Debate strategy"
                value={spec.debate_strategy}
              />
            ) : null}
          </div>
          {hasDiff ? (
            <div className={styles.diffBlock}>
              <h3>Change from previous Persona</h3>
              <div className={styles.diffList}>
                {diff.map((item) => (
                  <div
                    className={styles.diffRow}
                    key={item.key}
                    data-changed={item.changed}
                  >
                    <strong>{item.label}</strong>
                    <span>
                      {item.changed
                        ? `${item.before} → ${item.after}`
                        : "Unchanged"}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          ) : null}
          {mockPair ? <MockResponsePair pair={mockPair} /> : null}
        </>
      ) : null}
      {rawAgentMd.trim() ? (
        <details className={styles.sourceDetails}>
          <summary>Source</summary>
          <pre>{rawAgentMd}</pre>
        </details>
      ) : null}
    </section>
  );
}

function MockResponsePair({ pair }: { pair: MockPersonaResponsePair }) {
  return (
    <div className={styles.mockPair} data-testid="persona-mock-response-pair">
      <div className={styles.mockPairHeader}>
        <h3>Same-input Mock response pair</h3>
      </div>
      <div className={styles.mockPairInput}>
        <span>Input</span>
        <p>
          {pair.topic} · stance: {pair.stance} · seed: {pair.seed} · evidence:{" "}
          {pair.evidence_ids.join(", ") || "none"}
        </p>
      </div>
      <div className={styles.mockPairGrid}>
        <MockResponseCard label="Previous Persona" response={pair.first} />
        <MockResponseCard label="Current Persona" response={pair.second} />
      </div>
    </div>
  );
}

function MockResponseCard({
  label,
  response,
}: {
  label: string;
  response: MockPersonaResponse;
}) {
  return (
    <article className={styles.mockCard}>
      <strong>{label}</strong>
      <p>{response.speech}</p>
      <span>Position: {response.position_summary}</span>
      <span>Evidence IDs: {response.evidence_ids.join(", ") || "none"}</span>
      <span>
        {response.rule_set_id} · {response.schema_version}
      </span>
    </article>
  );
}

function PersonaField({
  label,
  value,
}: {
  label: string;
  value: string | readonly string[];
}) {
  return (
    <div className={styles.field}>
      <span>{label}</span>
      <p>{Array.isArray(value) ? value.join(" · ") : value}</p>
    </div>
  );
}

export function PersonaImpactLegend(): ReactNode {
  return (
    <span className={styles.legend}>
      Persona controls teaching expression; it never becomes evidence or a
      platform rule.
    </span>
  );
}
