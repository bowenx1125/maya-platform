"use client";

import type { CSSProperties } from "react";
import { IconLock, IconRefresh, IconSend } from "../../quiet-icons";
import { useT } from "../../../lib/i18n";
import { cn } from "../../../lib/utils";
import type { DebateDraftRequest, DebateLLMDefaults } from "../../../lib/api";
import {
  CREATE_SUB_DEBATE,
  CREATE_SUB_VOICE,
  CREATE_TEXTAREA,
  DEBATE_BUTTON,
} from "../debate-chrome";
import { CreateCard } from "./create-card";

export type LLMParamSpec = DebateLLMDefaults["params"][number];
export type LLMParamName = LLMParamSpec["name"];
/** One row: the value shown and whether it is sent at all. */
export type LLMParamState = { value: number | boolean | null; send: boolean };
export type LLMParamValues = Record<LLMParamName, LLMParamState>;

export const LLM_PARAMS_ANCHOR = "debate-llm-params";

// What the "?" says: meaning, range with what its ends do, suggestion
// (owner copy, 2026-10-24; ranges and extremes added 2026-10-25;
// kept in Chinese by owner decision while the rest of the UI is English).
const HELP: Record<LLMParamName, [string, string, string]> = {
  temperature: [
    "随机性：越高越活越随意，越低越稳越保守。",
    "范围：0 到 2（不含 2）。接近 0 几乎每次说同样的话；接近 2 用词跳跃、容易跑题。",
    "建议：0.6–0.8。",
  ],
  top_p: [
    "只从累计概率前 p 的词里挑，p 越小选词越保守。",
    "范围：大于 0，最大 1。接近 0 只挑最可能的词，近乎固定；1 表示不限制。",
    "建议：0.8–0.9；和 temperature 二选一调。",
  ],
  presence_penalty: [
    "减少重复已经说过的话题，越高越倾向换新话题。",
    "范围：-2 到 2。-2 反复围绕同一话题；2 不断换新话题，容易发散。",
    "建议：0.3–0.6。",
  ],
  frequency_penalty: [
    "减少重复同一个词。DashScope 的接口没有写明支持这个参数，所以只保存、不会发给模型。",
    "范围：-2 到 2。-2 鼓励重复用词；2 刻意避开用过的词。",
    "建议：先不传。",
  ],
  repetition_penalty: [
    "DashScope 的防重复参数，越大越不容易重复。",
    "范围：大于 0，最大 2；1.0 表示不惩罚。小于 1 更容易重复；接近 2 极力避免重复，用词可能生硬。",
    "建议：1.0–1.1。",
  ],
  max_tokens: [
    "一次回答的输出硬上限（token 数）。",
    "范围：正整数，1 到 32768。很小会把回答截断；很大只是上限，不会让回答变长。",
    "建议：不设；设了可能截断 JSON，导致生成失败。",
  ],
  enable_thinking: [
    "让模型先思考再回答。",
    "取值：开或关。开：先推理再回答，明显更慢、更贵；关：直接回答。",
    "建议：关。",
  ],
  seed: [
    "固定随机种子，让输出尽量稳定，但不保证每次完全一致。",
    "范围：0 到 2147483647 的整数。留空每次随机；同一个值配同样的输入只是尽量接近，不保证相同。",
    "建议：不设，调试时才用。",
  ],
};

export type VoiceParamSpec = DebateLLMDefaults["voice_params"][number];
export type VoiceParamName = VoiceParamSpec["name"];
export type VoiceParamValues = Record<VoiceParamName, number | string | null>;

const VOICE_HELP: Record<VoiceParamName, [string, string, string]> = {
  rate: [
    "生成语音时的说话速度，1.0 为正常。",
    "范围：0.5 到 2.0。0.5 是正常语速的一半，很慢；2.0 是两倍速，很快，可能听不清。",
    "建议：1.1–1.3。",
  ],
  instruction: [
    "用一句话描述语气、情绪、角色，例如“语气坚定，像辩论赛选手”；留空则用默认语气。",
    "范围：最多 500 字。描述越具体效果越明显；和发言内容冲突的要求可能被忽略。",
    "建议：一句话即可。",
  ],
  seed: [
    "固定后，同样的文字生成的声音会尽量接近，但语音服务不保证每次完全一致；留空则每次随机。",
    "范围：0 到 65535 的整数。",
    "建议：希望声音更稳定时再设。",
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

/* F `.create .prow` and its controls. */
const ROW =
  "grid grid-cols-[170px_1fr_36px] items-center gap-3 border-0 border-t-2 border-dashed border-[#11111122] px-1 py-[9px] first:border-t-0 max-[600px]:grid-cols-[1fr_36px] max-[600px]:gap-2";
const VOICE_ROW = "grid-cols-[110px_1fr_0]";
const LABEL = "flex min-w-0 items-center gap-1.5";
const NAME = "font-body text-[13px] leading-[normal] font-bold";
const HELP_BUTTON =
  "m-0 box-border grid size-[18px] flex-none cursor-help place-items-center rounded-full border-2 border-[#111] bg-[#FFE14D] p-0 font-body text-[10px] leading-none font-extrabold text-[#111] shadow-none";
const LOCK =
  "box-border inline-grid size-5 flex-none place-items-center rounded-full border-2 border-[#111] bg-[#EDE9FE] text-[#111]";
const CONTROL =
  "flex min-w-0 items-center gap-3 max-[600px]:col-span-full max-[600px]:row-start-2";
const OMIT_CELL = "max-[600px]:col-start-2 max-[600px]:row-start-1";
const NUMBER =
  "box-border h-auto min-h-0 w-[84px] min-w-0 flex-none rounded-full border-[2.5px] border-[#111] bg-white px-2 py-1.5 text-center font-body text-[13px] leading-[normal] font-semibold text-[#111] shadow-none [appearance:textfield] disabled:opacity-100 [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none";
const INTEGER = "w-[140px]";
const SLIDER =
  "relative m-0 box-border h-2.5 min-h-0 min-w-0 flex-1 cursor-pointer appearance-none rounded-full border-2 border-[#111] bg-[linear-gradient(90deg,#FF4D8D_var(--fill),#fff_0)] p-0 disabled:cursor-default [&::-moz-range-thumb]:box-border [&::-moz-range-thumb]:size-5 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border-[3px] [&::-moz-range-thumb]:border-[#111] [&::-moz-range-thumb]:bg-white [&::-webkit-slider-thumb]:box-border [&::-webkit-slider-thumb]:size-5 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border-[3px] [&::-webkit-slider-thumb]:border-[#111] [&::-webkit-slider-thumb]:bg-white [&::-webkit-slider-thumb]:shadow-[0_2px_0_#111]";
const SWITCH =
  "relative m-0 box-border h-6 w-11 flex-none cursor-pointer appearance-none rounded-full border-[2.5px] border-[#111] bg-white p-0 before:absolute before:top-0.5 before:left-0.5 before:size-4 before:rounded-full before:bg-[#111] before:content-[''] checked:bg-[#FF4D8D] checked:before:left-[19px] disabled:cursor-default";
const OMIT =
  "peer absolute inset-0 m-0 box-border cursor-pointer appearance-none rounded-full border-[2.5px] border-[#111] bg-white shadow-[0_2px_0_#111] checked:translate-y-[2px] checked:bg-[#FFE4E4] checked:shadow-none disabled:cursor-default";

function fillPercent(value: number, min: number, max: number): string {
  if (!(max > min)) return "0%";
  const pct = ((value - min) / (max - min)) * 100;
  return `${Math.min(100, Math.max(0, pct))}%`;
}

/** The "?" whose shared ui-guide tooltip carries the meaning and any note. */
function HelpButton({
  name,
  help,
  extra,
}: {
  name: string;
  help: string;
  extra: string[];
}) {
  const text = [help, ...extra].join("\n");
  return (
    <button
      type="button"
      className={HELP_BUTTON}
      aria-label={`${name}: ${help}`}
      data-ui-guide="debate.llmParam"
      data-ui-guide-text={text}
      data-ui-guide-hover="true"
    >
      ?
    </button>
  );
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
  const hasVoice = Boolean(voiceValues && voiceSpecs.length > 0);
  return (
    <section className="mb-[22px]" aria-labelledby="debate-params-title">
      <div className="mb-[18px] flex items-center gap-3">
        <h2
          id="debate-params-title"
          className="m-0 inline-block -rotate-[1.5deg] rounded-full border-[2.5px] border-[#111] bg-white px-[22px] py-1 font-display text-[26px] leading-[normal] font-extrabold tracking-normal text-[#111] shadow-[4px_5px_0_#A3E635] outline-none max-[600px]:text-[22px]"
          data-ui-guide="debate.llmParams"
          tabIndex={0}
        >
          {t("debateParamsTitle")}
        </h2>
        <span
          aria-hidden="true"
          className="min-w-0 flex-1 border-t-[3px] border-dotted border-[#111]"
        />
        <button
          type="button"
          className={DEBATE_BUTTON}
          disabled={disabled}
          aria-label={t("debateParamsReset")}
          data-ui-guide="debate.llmParamsReset"
          onClick={onReset}
        >
          <IconRefresh size={15} />
          <span aria-hidden="true">{t("debateParamsReset")}</span>
        </button>
      </div>
      <div
        className={cn(
          "grid items-start gap-5 max-[600px]:grid-cols-1 max-[600px]:gap-0",
          hasVoice ? "grid-cols-[1.35fr_1fr]" : "grid-cols-1",
        )}
      >
        <CreateCard
          title={t("debateParamsDebate")}
          headingLevel={3}
          className={CREATE_SUB_DEBATE}
        >
          <div id={LLM_PARAMS_ANCHOR} className="mt-2.5">
            {specs.map((spec) => {
              const state = values[spec.name];
              if (!state) return null;
              const off = disabled || !state.send;
              const help = HELP[spec.name].join("\n");
              const extra = [
                ...(!spec.sent ? [t("debateParamsNeverSent")] : []),
                ...(spec.kind === "int" ? [t("debateParamsEmpty")] : []),
              ];
              const bounds = sliderBounds(spec);
              return (
                <div key={spec.name} className={ROW} data-param={spec.name}>
                  <div className={LABEL}>
                    <span className={NAME}>{spec.name}</span>
                    <HelpButton name={spec.name} help={help} extra={extra} />
                    {!spec.sent ? (
                      <span
                        className={LOCK}
                        role="img"
                        aria-label={t("debateParamsNeverSent")}
                      >
                        <IconLock size={12} />
                      </span>
                    ) : null}
                  </div>
                  <div
                    className={cn(
                      CONTROL,
                      spec.kind !== "int" && !state.send && "opacity-40",
                    )}
                  >
                    {spec.kind === "bool" ? (
                      <label className="flex items-center">
                        <input
                          type="checkbox"
                          role="switch"
                          className={SWITCH}
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
                        <span className="sr-only">
                          {state.value
                            ? t("debateParamsOn")
                            : t("debateParamsOff")}
                        </span>
                      </label>
                    ) : spec.kind === "int" ? (
                      <input
                        type="number"
                        className={cn(NUMBER, INTEGER)}
                        aria-label={spec.name}
                        min={spec.minimum ?? undefined}
                        max={spec.maximum ?? undefined}
                        step={1}
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
                          className={SLIDER}
                          style={
                            {
                              "--fill": fillPercent(
                                Number(state.value ?? 0),
                                bounds.min,
                                bounds.max,
                              ),
                            } as CSSProperties
                          }
                          aria-label={`${spec.name} slider`}
                          {...bounds}
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
                          className={NUMBER}
                          aria-label={spec.name}
                          {...bounds}
                          step={spec.step ?? 0.01}
                          value={
                            state.value === null ? "" : String(state.value)
                          }
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
                  </div>
                  <div className={OMIT_CELL}>
                    {spec.kind !== "int" ? (
                      <label className="relative grid size-8 place-items-center">
                        <input
                          type="checkbox"
                          className={OMIT}
                          checked={!state.send}
                          disabled={disabled}
                          onChange={(event) =>
                            onChange(spec.name, {
                              ...state,
                              send: !event.target.checked,
                            })
                          }
                        />
                        <span className="pointer-events-none relative text-[#111] peer-checked:translate-y-[2px] peer-checked:text-[#B91C1C]">
                          <IconSend off={!state.send} />
                        </span>
                        <span className="sr-only">{t("debateParamsOmit")}</span>
                      </label>
                    ) : null}
                  </div>
                </div>
              );
            })}
          </div>
        </CreateCard>
        {hasVoice && voiceValues ? (
          <CreateCard
            title={t("debateParamsVoice")}
            headingLevel={3}
            className={CREATE_SUB_VOICE}
          >
            <div className="mt-2.5" data-param-group="voice">
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
          </CreateCard>
        ) : null}
      </div>
    </section>
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
  const min = spec.minimum ?? 0;
  const max = spec.maximum ?? 1;
  return (
    <div className={cn(ROW, VOICE_ROW)} data-param={`voice.${spec.name}`}>
      <div className={LABEL}>
        <span className={NAME}>{spec.name}</span>
        <HelpButton
          name={spec.name}
          help={help}
          extra={spec.kind === "float" ? [] : [t("debateParamsEmpty")]}
        />
      </div>
      <div className={CONTROL}>
        {spec.kind === "text" ? (
          <textarea
            className={cn(CREATE_TEXTAREA, "m-0 min-h-11 flex-1")}
            aria-label={spec.name}
            rows={2}
            maxLength={spec.max_length ?? undefined}
            value={typeof value === "string" ? value : ""}
            disabled={disabled}
            onChange={(event) => onChange(event.target.value)}
          />
        ) : spec.kind === "int" ? (
          <input
            type="number"
            className={cn(NUMBER, INTEGER)}
            aria-label={spec.name}
            min={spec.minimum ?? undefined}
            max={spec.maximum ?? undefined}
            step={1}
            value={value === null ? "" : String(value)}
            disabled={disabled}
            onChange={(event) => onChange(numeric(event.target.value, true))}
          />
        ) : (
          <>
            <input
              type="range"
              className={SLIDER}
              style={
                {
                  "--fill": fillPercent(Number(value ?? 1), min, max),
                } as CSSProperties
              }
              aria-label={`${spec.name} slider`}
              min={min}
              max={max}
              step={spec.step ?? 0.05}
              value={Number(value ?? 1)}
              disabled={disabled}
              onChange={(event) => onChange(Number(event.target.value))}
            />
            <input
              type="number"
              className={NUMBER}
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
      <div className={OMIT_CELL} />
    </div>
  );
}
