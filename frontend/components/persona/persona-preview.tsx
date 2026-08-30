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
  debate_strategy: readonly string[];
  boundaries: readonly string[];
  source_agent_md_hash?: string;
  compiler_version?: string;
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
  {
    key: "debate_strategy",
    label: "Debate strategy",
    read: (spec) => spec.debate_strategy.join(", "),
  },
];

/** Pure canonical field comparison used by the preview and student tests. */
export function diffPersonaSpec(
  before: PersonaPreviewSpec | null | undefined,
  after: PersonaPreviewSpec | null | undefined,
): PersonaDiff[] {
  return teachingDimensions.map(({ key, label, read }) => {
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
  onCompile,
  onConfirm,
}: {
  rawAgentMd: string;
  spec?: PersonaPreviewSpec | null;
  previousSpec?: PersonaPreviewSpec | null;
  diagnostics?: readonly PersonaPreviewDiagnostic[];
  confirmed?: boolean;
  onCompile?: () => void;
  onConfirm?: () => void;
}) {
  const diff = diffPersonaSpec(previousSpec, spec);
  const hasDiff = previousSpec != null && spec != null;

  return (
    <section className="section-card" data-testid="persona-preview">
      <div className="section-card-header">
        <div>
          <h2>Structured Persona</h2>
          <p>
            A deterministic preview of what the confirmed AGENT.md teaches. It
            cannot alter evidence identity, platform rules, order, permissions,
            or the output schema.
          </p>
        </div>
        <div className={styles.statusRow}>
          <span
            className={`${styles.status} ${confirmed ? styles.statusConfirmed : spec ? styles.statusReady : styles.statusPending}`}
          >
            {confirmed ? "Confirmed" : spec ? "Preview ready" : "Needs compile"}
          </span>
          {onConfirm && spec && !confirmed ? (
            <button
              className="primary-action compact-action"
              type="button"
              onClick={onConfirm}
            >
              Confirm Persona
            </button>
          ) : onCompile && !spec ? (
            <button
              className="primary-action compact-action"
              type="button"
              onClick={onCompile}
            >
              Compile Persona
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
            <PersonaField label="Boundaries" value={spec.boundaries} />
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
            <PersonaField
              label="Debate strategy"
              value={spec.debate_strategy}
            />
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
          <div className={styles.immutable}>
            <strong>Does not change</strong>
            <span>KnowledgeSnapshot and evidence IDs</span>
            <span>Debate rules, participant order, and permissions</span>
            <span>Structured output and safety validation</span>
          </div>
        </>
      ) : (
        <div className={styles.pending}>
          <strong>
            Compile the exact authored template to preview its meaning.
          </strong>
          <span>
            The raw AGENT.md remains the source of authorship; no default
            Persona or legacy fallback is inferred.
          </span>
        </div>
      )}
      {rawAgentMd.trim() ? (
        <details className={styles.sourceDetails}>
          <summary>Authored AGENT.md</summary>
          <pre>{rawAgentMd}</pre>
        </details>
      ) : null}
    </section>
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
