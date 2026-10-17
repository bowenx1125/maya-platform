"use client";

import type { CSSProperties, ReactNode } from "react";

import type { AvatarState } from "../avatar";
import type { StageCharacter } from "../stage3d/scholar-stage";
import styles from "./avatar-bar.module.css";
import {
  resolveArenaIntensity,
  type ArenaIntensity,
} from "./avatar-bar-flag";
import { normalizeAvatarState } from "./normalize-avatar-state";
import { avatarBarAccent, avatarBarSkin } from "./theme";

export type AvatarBarProps = {
  characters: StageCharacter[];
  /** Motion state per participant id; unknown / missing → idle. */
  visuals: Record<string, AvatarState | string | undefined>;
  speakingId?: string | null;
  bubbleText?: string;
  /** Optional central arena caption (topic); visual-only. */
  topic?: string;
  unavailableLabel?: string;
  /** When shown as WebGL fallback, surface the notice above the bar. */
  showUnavailableNotice?: boolean;
  /**
   * Atmosphere intensity (low|med|high). Prop wins; else URL
   * `?arenaIntensity=…`; default med. Visual-only — no audio.
   */
  intensity?: ArenaIntensity | string | null;
  className?: string;
  children?: ReactNode;
};

function initials(name: string, slot: string): string {
  const trimmed = name.trim();
  if (!trimmed) return (slot.slice(0, 1) || "?").toUpperCase();
  const chars = Array.from(trimmed);
  const first = chars[0] ?? "?";
  if (/[\u3400-\u9fff]/.test(first)) return first;
  return chars.slice(0, 2).join("").toUpperCase();
}

/**
 * Grok-Bar-style 2D multi-avatar arena for debate beta.
 * Bomberman-cover atmosphere (cyber grid + sticker outlines) — not gameplay.
 * Consumes the same five-state visuals map as ScholarScene — never drives
 * Next / audio. Unknown motion tokens collapse to idle.
 */
export function AvatarBar({
  characters,
  visuals,
  speakingId,
  bubbleText,
  topic,
  unavailableLabel,
  showUnavailableNotice = false,
  intensity: intensityProp,
  className,
  children,
}: AvatarBarProps) {
  const intensity = resolveArenaIntensity(undefined, intensityProp);
  const bubbleWindow = Array.from(bubbleText ?? "")
    .slice(-72)
    .join("");
  const speaking = characters.find((item) => item.id === speakingId);
  const speakingState = speaking
    ? normalizeAvatarState(visuals[speaking.id])
    : "idle";
  const vsLabel =
    characters.length >= 2
      ? `${characters[0]?.slot ?? "A"} vs ${characters[characters.length - 1]?.slot ?? "B"}`
      : "VS";

  return (
    <div
      className={`${styles.arena}${className ? ` ${className}` : ""}`}
      data-avatar-bar=""
      data-intensity={intensity}
      data-motion="grok"
      data-stage-visual="avatar-bar"
    >
      <div aria-hidden="true" className={styles.grid} />
      <div aria-hidden="true" className={styles.floorGlow} />

      <header className={styles.hud} data-avatar-bar-hud="" aria-hidden="true">
        <span className={styles.brandChip}>
          <span className={styles.brandBolt} />
          AI DEBATE ARENA
        </span>
        <span className={styles.hudSpacer} />
        <span className={styles.vsBadge}>{vsLabel}</span>
        <span className={styles.liveBadge}>
          <span className={styles.liveDot} />
          LIVE
        </span>
      </header>

      {showUnavailableNotice && unavailableLabel ? (
        <p className={styles.notice} role="status">
          {unavailableLabel}
        </p>
      ) : null}

      <div className={styles.stage} data-avatar-bar-stage="">
        <div className={styles.stageGlow} aria-hidden="true" />
        <div className={styles.stageRing} aria-hidden="true" />
        {topic ? (
          <p className={styles.topic} title={topic}>
            {topic}
          </p>
        ) : (
          <p className={styles.topicHint}>Debate arena</p>
        )}
        {speaking && bubbleWindow && speakingState === "speaking" ? (
          <div
            aria-live="polite"
            className={styles.bubble}
            data-avatar-bar-bubble=""
            style={
              {
                "--avatar-accent": avatarBarAccent(
                  speaking.config.material_theme,
                ),
              } as CSSProperties
            }
          >
            <span className={styles.bubbleWho}>{speaking.name}</span>
            {bubbleWindow}
          </div>
        ) : null}
      </div>

      <ul className={styles.bar} data-avatar-bar-list="" role="list">
        {characters.map((character) => {
          const state = normalizeAvatarState(visuals[character.id]);
          const accent = avatarBarAccent(character.config.material_theme);
          const skin = avatarBarSkin(character.config.material_theme);
          const isSpeaking = character.id === speakingId && state === "speaking";
          return (
            <li
              key={character.id}
              className={styles.item}
              data-avatar-id={character.id}
              data-current={isSpeaking ? "true" : "false"}
              data-slot={character.slot}
              data-state={state}
              style={
                {
                  "--avatar-accent": accent,
                  "--avatar-skin": skin,
                } as CSSProperties
              }
            >
              <div className={styles.pin} aria-hidden="true">
                <span className={styles.halo} />
                <span className={styles.pulseRing} />
                <span className={styles.listenRing} />
                <span className={styles.head}>
                  <span className={styles.initials}>
                    {initials(character.name, character.slot)}
                  </span>
                </span>
                {state === "speaking" ? (
                  <span className={styles.waves} data-avatar-waves="">
                    <i />
                    <i />
                    <i />
                  </span>
                ) : null}
                {state === "thinking" ? (
                  <span className={styles.thinkBadge} data-avatar-think="">
                    …
                  </span>
                ) : null}
              </div>
              <span className={styles.name} title={character.name}>
                <span className={styles.slot}>{character.slot}</span>
                {character.name}
              </span>
            </li>
          );
        })}
      </ul>

      {children}
    </div>
  );
}
