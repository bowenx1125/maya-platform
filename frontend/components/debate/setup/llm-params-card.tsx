"use client";

import { IconRefresh } from "../../quiet-icons";
import { SectionCard } from "../../ui";
import { useT } from "../../../lib/i18n";
import type { DebateDraftRequest, DebateLLMDefaults } from "../../../lib/api";
import styles from "./llm-params-card.module.css";
import rulesetStyles from "./ruleset-editor.module.css";
import sectionStyles from "./create-section.module.css";

export type LLMParamSpec = DebateLLMDefaults["params"][number];
export type LLMParamName = LLMParamSpec["name"];
/** One row: the value shown and whether it is sent at all. */
export type LLMParamState = { value: number | boolean | null; send: boolean };
export type LLMParamValues = Record<LLMParamName, LLMParamState>;

export const LLM_PARAMS_ANCHOR = "debate-llm-params";

// What the "?" says: meaning, range with what its ends do, suggestion
// (owner copy, 2026-10-24; ranges and extremes added and the UI made
// English-only, 2026-10-25).
const HELP: Record<LLMParamName, [string, string, string]> = {
  temperature: [
    "Randomness: higher is livelier and looser, lower is steadier and more conservative.",
    "Range: 0 up to (not including) 2. Near 0 says almost the same thing every time; near 2 jumps between words and drifts off topic.",
    "Suggested: 0.6–0.8.",
  ],
  top_p: [
    "Picks only from the words within the top cumulative probability p; a smaller p chooses more conservatively.",
    "Range: above 0, at most 1. Near 0 picks only the likeliest word and is nearly fixed; 1 means no limit.",
    "Suggested: 0.8–0.9; tune either this or temperature, not both.",
  ],
  presence_penalty: [
    "Discourages returning to topics already covered; higher leans toward new topics.",
    "Range: -2 to 2. -2 keeps circling the same topic; 2 keeps switching topics and can wander.",
    "Suggested: 0.3–0.6.",
  ],
  frequency_penalty: [
    "Discourages repeating the same word. The DashScope API does not document this parameter, so it is saved but never sent to the model.",
    "Range: -2 to 2. -2 encourages repeated words; 2 deliberately avoids words already used.",
    "Suggested: leave it unset.",
  ],
  repetition_penalty: [
    "DashScope's anti-repetition parameter; larger values repeat less.",
    "Range: above 0, at most 2; 1.0 means no penalty. Below 1 repeats more easily; near 2 avoids repetition hard and wording may feel stiff.",
    "Suggested: 1.0–1.1.",
  ],
  max_tokens: [
    "Hard cap on one answer's output, in tokens.",
    "Range: a whole number from 1 to 32768. A small cap cuts the answer short; a large one is only a ceiling and does not make answers longer.",
    "Suggested: leave it unset; a cap can cut the JSON short and fail the generation.",
  ],
  enable_thinking: [
    "Lets the model think before it answers.",
    "Values: on or off. On reasons first, which is noticeably slower and costlier; off answers directly.",
    "Suggested: off.",
  ],
  seed: [
    "Fixes the random seed so the same output can be reproduced.",
    "Range: a whole number from 0 to 2147483647. Empty is random each time; the same value with the same input tries to give the same output.",
    "Suggested: leave it unset; use it only when debugging.",
  ],
};

export type VoiceParamSpec = DebateLLMDefaults["voice_params"][number];
export type VoiceParamName = VoiceParamSpec["name"];
export type VoiceParamValues = Record<VoiceParamName, number | string | null>;

const VOICE_HELP: Record<VoiceParamName, [string, string, string]> = {
  rate: [
    "Speaking rate of the generated voice; 1.0 is normal.",
    "Range: 0.5 to 2.0. 0.5 is half the normal rate and very slow; 2.0 is double speed, very fast and may be hard to follow.",
    "Suggested: 1.1–1.3.",
  ],
  instruction: [
    'One sentence on tone, emotion or role, for example "firm, like a debate contestant"; empty uses the default tone.',
    "Range: at most 500 characters. The more specific, the stronger the effect; a request that conflicts with the speech may be ignored.",
    "Suggested: one sentence is enough.",
  ],
  seed: [
    "When set, the same text produces the same voice, which helps reproduce it; empty is random each time.",
    "Range: a whole number from 0 to 65535.",
    "Suggested: set it only when you need to reproduce a voice.",
  ],
};

export function defaultVoiceValues(specs: VoiceParamSpec[]): VoiceParamValues {
  return Object.fromEntries(
    specs.map((spec) => [spec.name, spec.default ?? null]),
  ) as VoiceParamValues;
}

/** The request body: blank text and empty numbers are not sent (null). */
export function voicePayload(
  values: VoiceParamValues,
): NonNullable<DebateDraftRequest["voice_params"]> {
  const text = (value: number | string | null) =>
    typeof value === "string" && value.trim() ? value.trim() : null;
  const number = (value: number | string | null) =>
    typeof value === "number" && Number.isFinite(value) ? value : null;
  return {
    rate: number(values.rate),
    instruction: text(values.instruction),
    seed: number(values.seed),
  };
}

// A value to show for a parameter whose default is "not sent".
const RESTING: Record<LLMParamName, number | boolean | null> = {
  temperature: 0.7,
  top_p: 0.8,
  presence_penalty: 0,
  frequency_penalty: 0,
  repetition_penalty: 1,
  max_tokens: null,
  enable_thinking: false,
  seed: null,
};

export function defaultParamValues(specs: LLMParamSpec[]): LLMParamValues {
  return Object.fromEntries(
    specs.map((spec) => [
      spec.name,
      {
        value: spec.default ?? RESTING[spec.name],
        send: spec.default !== null && spec.default !== undefined,
      },
    ]),
  ) as LLMParamValues;
}

/** The request body: a value per parameter, null when it is not sent. */
export function paramsPayload(
  values: LLMParamValues,
): NonNullable<DebateDraftRequest["llm_params"]> {
  return Object.fromEntries(
    Object.entries(values).map(([name, state]) => [
      name,
      state.send && state.value !== null ? state.value : null,
    ]),
  ) as NonNullable<DebateDraftRequest["llm_params"]>;
}

function sliderBounds(spec: LLMParamSpec): { min: number; max: number } {
  const step = spec.step ?? 1;
  const min = (spec.minimum ?? 0) + (spec.exclusive_minimum ? step : 0);
  const max = (spec.maximum ?? 1) - (spec.exclusive_maximum ? step : 0);
  return { min: Number(min.toFixed(4)), max: Number(max.toFixed(4)) };
}

export function LlmParamsCard({
  specs,
  values,
  voiceSpecs = [],
  voiceValues,
  disabled = false,
  onChange,
  onVoiceChange,
  onReset,
}: {
  specs: LLMParamSpec[];
  values: LLMParamValues;
  voiceSpecs?: VoiceParamSpec[];
  voiceValues?: VoiceParamValues;
  disabled?: boolean;
  onChange: (name: LLMParamName, next: LLMParamState) => void;
  onVoiceChange?: (name: VoiceParamName, next: number | string | null) => void;
  onReset: () => void;
}) {
  const t = useT();
  return (
    <SectionCard
      title={t("debateParamsTitle")}
      className={`${rulesetStyles.card} ${sectionStyles.section}`}
      guide="debate.llmParams"
      action={
        <div className={rulesetStyles.actions}>
          <button
            type="button"
            className={`${rulesetStyles.action} ${rulesetStyles.iconAction}`}
            disabled={disabled}
            aria-label={t("debateParamsReset")}
            data-ui-guide="debate.llmParamsReset"
            onClick={onReset}
          >
            <IconRefresh />
          </button>
        </div>
      }
    >
      <div id={LLM_PARAMS_ANCHOR} className={styles.rows}>
        {specs.map((spec) => {
          const state = values[spec.name];
          if (!state) return null;
          const off = disabled || !state.send;
          const help = HELP[spec.name].join("\n");
          return (
            <div key={spec.name} className={styles.row} data-param={spec.name}>
              <div className={styles.label}>
                <span className={styles.name}>{spec.name}</span>
                <button
                  type="button"
                  className={styles.help}
                  aria-label={`${spec.name}: ${help}`}
                  data-ui-guide="debate.llmParam"
                  data-ui-guide-text={help}
                >
                  ?
                </button>
                {!spec.sent ? (
                  <span className={styles.note}>
                    {t("debateParamsNeverSent")}
                  </span>
                ) : null}
              </div>
              <div className={styles.control}>
                {spec.kind === "bool" ? (
                  <label className={styles.switch}>
                    <input
                      type="checkbox"
                      role="switch"
                      aria-label={spec.name}
                      checked={Boolean(state.value)}
                      disabled={off}
                      onChange={(event) =>
                        onChange(spec.name, {
                          ...state,
                          value: event.target.checked,
                        })
                      }
                    />
                    <span>
                      {state.value ? t("debateParamsOn") : t("debateParamsOff")}
                    </span>
                  </label>
                ) : spec.kind === "int" ? (
                  <input
                    type="number"
                    className={`${styles.number} ${styles.integer}`}
                    aria-label={spec.name}
                    min={spec.minimum ?? undefined}
                    max={spec.maximum ?? undefined}
                    step={1}
                    placeholder={t("debateParamsEmpty")}
                    value={state.value === null ? "" : String(state.value)}
                    disabled={disabled}
                    onChange={(event) => {
                      const raw = event.target.value.trim();
                      // Empty means not sent.
                      onChange(
                        spec.name,
                        raw === ""
                          ? { value: null, send: false }
                          : { value: Math.trunc(Number(raw)), send: true },
                      );
                    }}
                  />
                ) : (
                  <>
                    <input
                      type="range"
                      className={styles.slider}
                      aria-label={`${spec.name} slider`}
                      {...sliderBounds(spec)}
                      step={spec.step ?? 0.01}
                      value={Number(state.value ?? 0)}
                      disabled={off}
                      onChange={(event) =>
                        onChange(spec.name, {
                          ...state,
                          value: Number(event.target.value),
                        })
                      }
                    />
                    <input
                      type="number"
                      className={styles.number}
                      aria-label={spec.name}
                      {...sliderBounds(spec)}
                      step={spec.step ?? 0.01}
                      value={state.value === null ? "" : String(state.value)}
                      disabled={off}
                      onChange={(event) =>
                        onChange(spec.name, {
                          ...state,
                          value:
                            event.target.value === ""
                              ? null
                              : Number(event.target.value),
                        })
                      }
                    />
                  </>
                )}
                {spec.kind !== "int" ? (
                  <label className={styles.omit}>
                    <input
                      type="checkbox"
                      checked={!state.send}
                      disabled={disabled}
                      onChange={(event) =>
                        onChange(spec.name, {
                          ...state,
                          send: !event.target.checked,
                        })
                      }
                    />
                    <span>{t("debateParamsOmit")}</span>
                  </label>
                ) : null}
              </div>
            </div>
          );
        })}
      </div>
      {voiceValues && voiceSpecs.length > 0 ? (
        <>
          <h3 className={styles.group}>{t("debateParamsVoice")}</h3>
          <div className={styles.rows} data-param-group="voice">
            {voiceSpecs.map((spec) => (
              <VoiceRow
                key={spec.name}
                spec={spec}
                value={voiceValues[spec.name] ?? null}
                disabled={disabled}
                onChange={(next) => onVoiceChange?.(spec.name, next)}
              />
            ))}
          </div>
        </>
      ) : null}
    </SectionCard>
  );
}

function VoiceRow({
  spec,
  value,
  disabled,
  onChange,
}: {
  spec: VoiceParamSpec;
  value: number | string | null;
  disabled: boolean;
  onChange: (next: number | string | null) => void;
}) {
  const t = useT();
  const help = VOICE_HELP[spec.name].join("\n");
  const numeric = (raw: string, integer: boolean) => {
    const trimmed = raw.trim();
    if (trimmed === "") return null;
    const parsed = Number(trimmed);
    return integer ? Math.trunc(parsed) : parsed;
  };
  return (
    <div className={styles.row} data-param={`voice.${spec.name}`}>
      <div className={styles.label}>
        <span className={styles.name}>{spec.name}</span>
        <button
          type="button"
          className={styles.help}
          aria-label={`${spec.name}: ${help}`}
          data-ui-guide="debate.llmParam"
          data-ui-guide-text={help}
        >
          ?
        </button>
      </div>
      <div className={styles.control}>
        {spec.kind === "text" ? (
          <textarea
            className={styles.text}
            aria-label={spec.name}
            rows={2}
            maxLength={spec.max_length ?? undefined}
            placeholder={t("debateParamsEmpty")}
            value={typeof value === "string" ? value : ""}
            disabled={disabled}
            onChange={(event) => onChange(event.target.value)}
          />
        ) : spec.kind === "int" ? (
          <input
            type="number"
            className={`${styles.number} ${styles.integer}`}
            aria-label={spec.name}
            min={spec.minimum ?? undefined}
            max={spec.maximum ?? undefined}
            step={1}
            placeholder={t("debateParamsEmpty")}
            value={value === null ? "" : String(value)}
            disabled={disabled}
            onChange={(event) => onChange(numeric(event.target.value, true))}
          />
        ) : (
          <>
            <input
              type="range"
              className={styles.slider}
              aria-label={`${spec.name} slider`}
              min={spec.minimum ?? 0}
              max={spec.maximum ?? 1}
              step={spec.step ?? 0.05}
              value={Number(value ?? 1)}
              disabled={disabled}
              onChange={(event) => onChange(Number(event.target.value))}
            />
            <input
              type="number"
              className={styles.number}
              aria-label={spec.name}
              min={spec.minimum ?? undefined}
              max={spec.maximum ?? undefined}
              step={spec.step ?? 0.05}
              placeholder={t("debateParamsEmpty")}
              value={value === null ? "" : String(value)}
              disabled={disabled}
              onChange={(event) => onChange(numeric(event.target.value, false))}
            />
          </>
        )}
      </div>
    </div>
  );
}
