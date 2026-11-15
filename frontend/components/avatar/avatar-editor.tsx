"use client";

import { WorkspaceIcon } from "../workspace-icon";
import { useMemo, useState } from "react";

import { DismissibleAlert } from "../dismissible-alert";
import { PRESS_MOTION } from "../ui/button";
import { avatarOptionLabel, avatarTemplateLabel } from "../../lib/i18n";
import { useT } from "../../lib/i18n";
import { AvatarCanvas } from "./avatar-canvas";
import {
  AVATAR_EYE_COLORS,
  AVATAR_EXPRESSIONS,
  AVATAR_EXPRESSION_STRENGTHS,
  AVATAR_MATERIAL_THEMES,
  AVATAR_MOTION_STYLES,
  AVATAR_STATES,
  avatarDefaultConfigForTemplate,
  type AvatarConfig,
  type AvatarExpression,
  type AvatarExpressionStrength,
  type AvatarMotionStyle,
  type AvatarState,
  type AvatarTemplate,
} from "./types";

export type AvatarEditorProps = {
  templates: readonly AvatarTemplate[];
  value: AvatarConfig;
  onChange: (config: AvatarConfig) => void;
  onPreviewStateChange?: (state: AvatarState) => void;
  previewState?: AvatarState;
  fallbackLabel?: string;
  disabled?: boolean;
  errorMessage?: string;
  onPreview?: () => void;
};

function setField<K extends keyof AvatarConfig>(
  value: AvatarConfig,
  key: K,
  next: AvatarConfig[K],
): AvatarConfig {
  return { ...value, [key]: next };
}

const eyeValue = (value: AvatarConfig["eye_color"]): string =>
  value ?? "default";

export function AvatarEditor({
  templates,
  value,
  onChange,
  onPreviewStateChange,
  previewState,
  fallbackLabel,
  disabled = false,
  errorMessage,
  onPreview,
}: AvatarEditorProps) {
  const t = useT();
  const displayFallbackLabel = fallbackLabel ?? t("avatar");
  const [uncontrolledState, setUncontrolledState] = useState<AvatarState>(
    () => previewState ?? "idle",
  );
  const localState = previewState ?? uncontrolledState;
  const controlledState = previewState !== undefined;
  const availableTemplates = useMemo(
    () => templates.filter((template) => template.available),
    [templates],
  );

  function changeState(next: AvatarState) {
    if (!controlledState) setUncontrolledState(next);
    onPreviewStateChange?.(next);
  }

  function update<K extends keyof AvatarConfig>(key: K, next: AvatarConfig[K]) {
    onChange(setField(value, key, next));
  }

  return (
    <section
      className={`grid min-w-0 ${value.template_id === "egg" ? "gap-0" : "gap-5"}`}
      aria-label={t("avatarEditor")}
    >
      <div
        className="flex gap-1.5"
        role="radiogroup"
        aria-label={t("avatarTemplate")}
      >
        {availableTemplates.map((template) => (
          <button
            key={template.id}
            type="button"
            role="radio"
            aria-checked={value.template_id === template.id}
            disabled={disabled}
            onClick={() => {
              const next = avatarDefaultConfigForTemplate(template);
              if (next) onChange(next);
            }}
            className={`flex h-11 min-w-0 flex-1 items-center justify-center gap-[3px] rounded-[9px] border-2 border-[#111] px-[5px] text-[11px] font-bold shadow-[0_3px_0_#111] ${PRESS_MOTION} ${value.template_id === template.id ? "bg-[#A3E635]" : "bg-white"}`}
          >
            {template.id === "egg" ? (
              <WorkspaceIcon name="diamond" size={13} />
            ) : null}
            {{
              "wave1-default-head": "Default",
              "maya-warm-scholar": "Scholar",
              "maya-civic-observer": "Observer",
              egg: "Egg",
            }[template.id] ?? avatarTemplateLabel(template.id, template.name)}
          </button>
        ))}
      </div>
      <AvatarCanvas
        className={
          value.template_id === "egg" ? "h-[322px] aspect-auto" : undefined
        }
        config={value}
        state={localState}
        framing="full-body"
        fallbackLabel={displayFallbackLabel}
      />
      {value.template_id === "egg" ? (
        <div className="rounded-xl border-[3px] border-[#111] bg-white p-2.5 shadow-[3px_3px_0_#111]">
          <button
            type="button"
            disabled={disabled}
            onClick={onPreview}
            className={`flex min-h-12 w-full items-center justify-center gap-2 rounded-[10px] border-[3px] border-[#111] bg-[#FFE14D] text-base font-bold shadow-[3px_3px_0_#111] ${PRESS_MOTION}`}
          >
            <WorkspaceIcon name="play" size={20} />
            Preview
          </button>
        </div>
      ) : (
        <div className="grid min-w-0 grid-cols-2 gap-[0.85rem] max-[620px]:grid-cols-1">
          <label className="grid min-w-0 gap-[0.42rem]">
            <span className="text-[0.78rem] font-bold tracking-[0.02em] text-(--workspace-label,#38505d)">
              {t("avatarMaterialTheme")}
            </span>
            <select
              className="min-h-11 w-full min-w-0 rounded-[0.7rem] border border-[rgba(35,57,72,0.18)] bg-(--surface,#fff) px-[0.7rem] font-[inherit] text-(--workspace-label,#213a47) disabled:cursor-not-allowed disabled:opacity-[0.56]"
              value={value.material_theme}
              disabled={disabled}
              onChange={(event) => update("material_theme", event.target.value)}
            >
              {AVATAR_MATERIAL_THEMES.map((theme) => (
                <option key={theme} value={theme}>
                  {avatarOptionLabel(theme)}
                </option>
              ))}
            </select>
          </label>
          <label className="grid min-w-0 gap-[0.42rem]">
            <span className="text-[0.78rem] font-bold tracking-[0.02em] text-(--workspace-label,#38505d)">
              {t("avatarEyeColor")}
            </span>
            <select
              className="min-h-11 w-full min-w-0 rounded-[0.7rem] border border-[rgba(35,57,72,0.18)] bg-(--surface,#fff) px-[0.7rem] font-[inherit] text-(--workspace-label,#213a47) disabled:cursor-not-allowed disabled:opacity-[0.56]"
              value={eyeValue(value.eye_color)}
              disabled={disabled}
              onChange={(event) =>
                update(
                  "eye_color",
                  event.target.value === "default" ? null : event.target.value,
                )
              }
            >
              {AVATAR_EYE_COLORS.map((color) => (
                <option key={color} value={color}>
                  {color === "default"
                    ? t("avatarAssetDefault")
                    : avatarOptionLabel(color)}
                </option>
              ))}
            </select>
          </label>
          <label className="grid min-w-0 gap-[0.42rem]">
            <span className="text-[0.78rem] font-bold tracking-[0.02em] text-(--workspace-label,#38505d)">
              {t("avatarDefaultExpression")}
            </span>
            <select
              className="min-h-11 w-full min-w-0 rounded-[0.7rem] border border-[rgba(35,57,72,0.18)] bg-(--surface,#fff) px-[0.7rem] font-[inherit] text-(--workspace-label,#213a47) disabled:cursor-not-allowed disabled:opacity-[0.56]"
              value={value.default_expression}
              disabled={disabled}
              onChange={(event) =>
                update(
                  "default_expression",
                  event.target.value as AvatarExpression,
                )
              }
            >
              {AVATAR_EXPRESSIONS.map((expression) => (
                <option key={expression} value={expression}>
                  {avatarOptionLabel(expression)}
                </option>
              ))}
            </select>
          </label>
          <label className="grid min-w-0 gap-[0.42rem]">
            <span className="text-[0.78rem] font-bold tracking-[0.02em] text-(--workspace-label,#38505d)">
              {t("avatarExpressionStrength")}
            </span>
            <select
              className="min-h-11 w-full min-w-0 rounded-[0.7rem] border border-[rgba(35,57,72,0.18)] bg-(--surface,#fff) px-[0.7rem] font-[inherit] text-(--workspace-label,#213a47) disabled:cursor-not-allowed disabled:opacity-[0.56]"
              value={value.expression_strength}
              disabled={disabled}
              onChange={(event) =>
                update(
                  "expression_strength",
                  event.target.value as AvatarExpressionStrength,
                )
              }
            >
              {AVATAR_EXPRESSION_STRENGTHS.map((strength) => (
                <option key={strength} value={strength}>
                  {avatarOptionLabel(strength)}
                </option>
              ))}
            </select>
          </label>
          <label className="grid min-w-0 gap-[0.42rem]">
            <span className="text-[0.78rem] font-bold tracking-[0.02em] text-(--workspace-label,#38505d)">
              {t("avatarHeadMotion")}
            </span>
            <select
              className="min-h-11 w-full min-w-0 rounded-[0.7rem] border border-[rgba(35,57,72,0.18)] bg-(--surface,#fff) px-[0.7rem] font-[inherit] text-(--workspace-label,#213a47) disabled:cursor-not-allowed disabled:opacity-[0.56]"
              value={value.motion_style}
              disabled={disabled}
              onChange={(event) =>
                update("motion_style", event.target.value as AvatarMotionStyle)
              }
            >
              {AVATAR_MOTION_STYLES.map((motion) => (
                <option key={motion} value={motion}>
                  {avatarOptionLabel(motion)}
                </option>
              ))}
            </select>
          </label>
          <div className="grid min-w-0 gap-[0.42rem] col-span-full max-[620px]:col-auto">
            <span className="text-[0.78rem] font-bold tracking-[0.02em] text-(--workspace-label,#38505d)">
              {t("avatarPreviewState")}
            </span>
            <div
              className="flex min-w-0 flex-wrap gap-2"
              role="group"
              aria-label={t("avatarPreviewState")}
            >
              {AVATAR_STATES.map((state) => (
                <button
                  key={state}
                  className={`min-h-11 min-w-0 cursor-pointer rounded-[0.7rem] border px-3 py-[0.55rem] text-left font-[inherit] text-(--workspace-label,#213a47) transition-[border-color,background-color] duration-150 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-[0.56] flex-[1_1_6.5rem] text-center ${localState === state ? "border-(--workspace-selected,#2f7c78) bg-(--workspace-content,#eaf5f1) outline-none" : "border-[rgba(35,57,72,0.18)] bg-(--surface,#fff) hover:border-(--workspace-selected,#2f7c78) hover:bg-(--workspace-content,#eaf5f1) focus-visible:border-(--workspace-selected,#2f7c78) focus-visible:bg-(--workspace-content,#eaf5f1)"}`}
                  type="button"
                  disabled={disabled}
                  aria-pressed={localState === state}
                  onClick={() => changeState(state)}
                >
                  {avatarOptionLabel(state)}
                </button>
              ))}
            </div>
          </div>
        </div>
      )}
      {errorMessage ? (
        <DismissibleAlert
          className="m-0 text-[0.82rem] leading-normal text-(--muted,#62626a) text-[#a54948]"
          resetKey={errorMessage}
        >
          {errorMessage}
        </DismissibleAlert>
      ) : null}
    </section>
  );
}

export { AvatarCanvas };
