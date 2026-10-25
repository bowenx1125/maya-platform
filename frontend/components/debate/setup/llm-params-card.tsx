"use client";

import { IconRefresh } from "../../quiet-icons";
import { SectionCard } from "../../ui";
import { useT } from "../../locale";
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

// What the "?" says: meaning, range, suggestion (owner copy, 2026-10-24).
const HELP: Record<LLMParamName, [string, string, string]> = {
  temperature: [
    "随机性：越高越活越随意，越低越稳越保守。",
    "范围：0 到 2（不含 2）。",
    "建议：0.6–0.8。",
  ],
  top_p: [
    "只从累计概率前 p 的词里挑，p 越小选词越保守。",
    "范围：大于 0，最大 1。",
    "建议：0.8–0.9；和 temperature 二选一调。",
  ],
  presence_penalty: [
    "减少重复已经说过的话题，越高越倾向换新话题。",
    "范围：-2 到 2。",
    "建议：0.3–0.6。",
  ],
  frequency_penalty: [
    "减少重复同一个词。DashScope 的接口没有写明支持这个参数，所以只保存、不会发给模型。",
    "范围：-2 到 2。",
    "建议：先不传。",
  ],
  repetition_penalty: [
    "DashScope 的防重复参数，越大越不容易重复。",
    "范围：大于 0，最大 2；1.0 表示不惩罚。",
    "建议：1.0–1.1。",
  ],
  max_tokens: [
    "一次回答的输出硬上限（token 数）。",
    "范围：正整数，1 到 32768。",
    "建议：不设；设了可能截断 JSON，导致生成失败。",
  ],
  enable_thinking: [
    "让模型先思考再回答。",
    "取值：开或关。",
    "建议：关；开了明显更慢、更贵。",
  ],
  seed: [
    "固定随机种子，便于复现同样的输出。",
    "范围：0 到 2147483647 的整数。",
    "建议：不设，调试时才用。",
  ],
};

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
  disabled = false,
  onChange,
  onReset,
}: {
  specs: LLMParamSpec[];
  values: LLMParamValues;
  disabled?: boolean;
  onChange: (name: LLMParamName, next: LLMParamState) => void;
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
    </SectionCard>
  );
}
