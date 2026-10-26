"use client";

import { useMemo, useState } from "react";

import { DismissibleAlert } from "../dismissible-alert";
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
    <section className="grid min-w-0 gap-5" aria-label={t("avatarEditor")}>
      <AvatarCanvas
        config={value}
        state={localState}
        framing="full-body"
        fallbackLabel={displayFallbackLabel}
      />
      <div className="grid min-w-0 grid-cols-2 gap-[0.85rem] max-[620px]:grid-cols-1">
        <div className="grid min-w-0 gap-[0.42rem] col-span-full max-[620px]:col-auto">
          <span className="text-[0.78rem] font-bold tracking-[0.02em] text-(--workspace-label,#38505d)">{t("avatarTemplate")}</span>
          <div
            className="grid min-w-0 grid-cols-3 gap-[0.55rem] max-[620px]:grid-cols-1"
            role="radiogroup"
            aria-label={t("avatarTemplate")}
          >
            {availableTemplates.map((template) => (
              <button
                key={template.id}
                className={`min-h-11 min-w-0 cursor-pointer rounded-[0.7rem] border px-3 py-[0.55rem] text-left font-[inherit] text-(--workspace-label,#213a47) transition-[border-color,background-color] duration-150 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-[0.56] min-h-[4.1rem] [overflow-wrap:anywhere] ${template.id === value.template_id ? "border-(--workspace-selected,#2f7c78) bg-(--workspace-content,#eaf5f1) outline-none" : "border-[rgba(35,57,72,0.18)] bg-(--surface,#fff) hover:border-(--workspace-selected,#2f7c78) hover:bg-(--workspace-content,#eaf5f1) focus-visible:border-(--workspace-selected,#2f7c78) focus-visible:bg-(--workspace-content,#eaf5f1)"}`}
                type="button"
                role="radio"
                aria-checked={template.id === value.template_id}
                disabled={disabled}
                onClick={() => {
                  const nextConfig = avatarDefaultConfigForTemplate(template);
                  if (nextConfig) onChange(nextConfig);
                }}
              >
                <span className="block text-[0.82rem] leading-[1.2] font-bold">
                  {avatarTemplateLabel(template.id, template.name)}
                </span>
              </button>
            ))}
          </div>
        </div>
        <label className="grid min-w-0 gap-[0.42rem]">
          <span className="text-[0.78rem] font-bold tracking-[0.02em] text-(--workspace-label,#38505d)">{t("avatarMaterialTheme")}</span>
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
          <span className="text-[0.78rem] font-bold tracking-[0.02em] text-(--workspace-label,#38505d)">{t("avatarEyeColor")}</span>
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
          <span className="text-[0.78rem] font-bold tracking-[0.02em] text-(--workspace-label,#38505d)">{t("avatarDefaultExpression")}</span>
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
          <span className="text-[0.78rem] font-bold tracking-[0.02em] text-(--workspace-label,#38505d)">{t("avatarExpressionStrength")}</span>
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
          <span className="text-[0.78rem] font-bold tracking-[0.02em] text-(--workspace-label,#38505d)">{t("avatarHeadMotion")}</span>
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
          <span className="text-[0.78rem] font-bold tracking-[0.02em] text-(--workspace-label,#38505d)">{t("avatarPreviewState")}</span>
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
