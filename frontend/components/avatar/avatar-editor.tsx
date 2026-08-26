"use client";

import { useMemo, useState } from "react";

import { avatarOptionLabel, avatarTemplateLabel } from "../../lib/i18n";
import { useLocale, useT } from "../locale";
import styles from "./avatar.module.css";
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
  const { locale } = useLocale();
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
    <section className={styles.editor} aria-label={t("avatarEditor")}>
      <AvatarCanvas
        config={value}
        state={localState}
        fallbackLabel={displayFallbackLabel}
      />
      <div className={styles.controlGrid}>
        <div className={`${styles.control} ${styles.controlFull}`}>
          <span className={styles.label}>{t("avatarTemplate")}</span>
          <div
            className={styles.templateGrid}
            role="radiogroup"
            aria-label={t("avatarTemplate")}
          >
            {availableTemplates.map((template) => (
              <button
                key={template.id}
                className={`${styles.button} ${styles.templateButton} ${
                  template.id === value.template_id ? styles.selected : ""
                }`}
                type="button"
                role="radio"
                aria-checked={template.id === value.template_id}
                disabled={disabled}
                onClick={() => {
                  const nextConfig = avatarDefaultConfigForTemplate(template);
                  if (nextConfig) onChange(nextConfig);
                }}
              >
                <span className={styles.templateName}>
                  {avatarTemplateLabel(template.id, template.name, locale)}
                </span>
                <span className={styles.templateMeta}>
                  {t("avatarTemplateControls", {
                    count: template.supported_parameters.length,
                  })}
                </span>
              </button>
            ))}
          </div>
        </div>
        <label className={styles.control}>
          <span className={styles.label}>{t("avatarMaterialTheme")}</span>
          <select
            className={styles.select}
            value={value.material_theme}
            disabled={disabled}
            onChange={(event) => update("material_theme", event.target.value)}
          >
            {AVATAR_MATERIAL_THEMES.map((theme) => (
              <option key={theme} value={theme}>
                {avatarOptionLabel(theme, locale)}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.control}>
          <span className={styles.label}>{t("avatarEyeColor")}</span>
          <select
            className={styles.select}
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
                  : avatarOptionLabel(color, locale)}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.control}>
          <span className={styles.label}>{t("avatarDefaultExpression")}</span>
          <select
            className={styles.select}
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
                {avatarOptionLabel(expression, locale)}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.control}>
          <span className={styles.label}>{t("avatarExpressionStrength")}</span>
          <select
            className={styles.select}
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
                {avatarOptionLabel(strength, locale)}
              </option>
            ))}
          </select>
        </label>
        <label className={styles.control}>
          <span className={styles.label}>{t("avatarHeadMotion")}</span>
          <select
            className={styles.select}
            value={value.motion_style}
            disabled={disabled}
            onChange={(event) =>
              update("motion_style", event.target.value as AvatarMotionStyle)
            }
          >
            {AVATAR_MOTION_STYLES.map((motion) => (
              <option key={motion} value={motion}>
                {avatarOptionLabel(motion, locale)}
              </option>
            ))}
          </select>
        </label>
        <div className={`${styles.control} ${styles.controlFull}`}>
          <span className={styles.label}>{t("avatarPreviewState")}</span>
          <div
            className={styles.buttonRow}
            role="group"
            aria-label={t("avatarPreviewState")}
          >
            {AVATAR_STATES.map((state) => (
              <button
                key={state}
                className={`${styles.button} ${styles.stateButton} ${
                  localState === state ? styles.selected : ""
                }`}
                type="button"
                disabled={disabled}
                aria-pressed={localState === state}
                onClick={() => changeState(state)}
              >
                {avatarOptionLabel(state, locale)}
              </button>
            ))}
          </div>
        </div>
      </div>
      <p
        className={`${styles.message}${errorMessage ? ` ${styles.error}` : ""}`}
        role={errorMessage ? "alert" : undefined}
      >
        {errorMessage ?? t("avatarGuidance")}
      </p>
    </section>
  );
}

export { AvatarCanvas };
