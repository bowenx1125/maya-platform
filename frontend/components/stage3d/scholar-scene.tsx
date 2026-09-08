"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import type { AvatarState } from "../avatar";
import { STAGE_BACKDROP_ASSET } from "./assets";
import type { StageAnchor, StageCharacter } from "./scholar-stage";
import styles from "./stage3d.module.css";

export type ScholarSceneProps = {
  characters: StageCharacter[];
  /** Motion state per participant id; anything missing renders as idle. */
  visuals: Record<string, AvatarState>;
  /** True before the first turn and once the debate is over. */
  resting: boolean;
  /** Whose head carries the bubble, if anyone is speaking. */
  speakingId?: string | null;
  /** The spoken line, already trimmed for the bubble. */
  bubbleText?: string;
  loadingLabel: string;
  unavailableLabel: string;
  /** Barrage lanes, the join card and the teacher's pause control. */
  overlay?: ReactNode;
};

type SceneStatus = "loading" | "ready" | "failed";

/**
 * The 3D bench: one canvas, name plates and a head-following bubble in DOM.
 *
 * Text stays in DOM rather than in the scene so it inherits the page's fonts,
 * wraps properly in both languages and is readable by a screen reader. The
 * renderer only reports where each head is on screen.
 */
export function ScholarScene({
  characters,
  visuals,
  resting,
  speakingId,
  bubbleText,
  loadingLabel,
  unavailableLabel,
  overlay,
}: ScholarSceneProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stageRef = useRef<import("./scholar-stage").ScholarStage | null>(null);
  const latestCharactersRef = useRef(characters);
  const latestVisualsRef = useRef(visuals);
  const latestRestingRef = useRef(resting);
  const [status, setStatus] = useState<SceneStatus>("loading");
  const [anchors, setAnchors] = useState<StageAnchor[]>([]);

  // This effect runs before the stage-import effect below. Keeping the latest
  // values outside the async callback prevents a roster change during GLB
  // loading from being lost when the callback eventually resolves.
  useEffect(() => {
    latestCharactersRef.current = characters;
    latestVisualsRef.current = visuals;
    latestRestingRef.current = resting;
  }, [characters, resting, visuals]);

  const handleAnchors = useCallback((next: StageAnchor[]) => {
    setAnchors(next);
  }, []);
  const anchorsRef = useRef(handleAnchors);
  useEffect(() => {
    anchorsRef.current = handleAnchors;
  }, [handleAnchors]);

  const applyStageVisuals = useCallback(
    (stage: import("./scholar-stage").ScholarStage) => {
      for (const character of latestCharactersRef.current) {
        stage.setVisual(
          character.id,
          latestVisualsRef.current[character.id] ?? "idle",
        );
      }
    },
    [],
  );

  const syncStageRoster = useCallback(
    (stage: import("./scholar-stage").ScholarStage) => {
      stage.setCharacters(latestCharactersRef.current);
      applyStageVisuals(stage);
      stage.setResting(latestRestingRef.current);
    },
    [applyStageVisuals],
  );

  useEffect(() => {
    let active = true;
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    setStatus("loading");
    void import("./scholar-stage")
      .then(({ ScholarStage }) => {
        if (!active) return;
        try {
          const stage = new ScholarStage({
            canvas,
            onReady: () => {
              if (!active) return;
              const readyStage = stageRef.current;
              if (readyStage) syncStageRoster(readyStage);
              setStatus("ready");
            },
            onError: () => active && setStatus("failed"),
            onAnchors: (next) => {
              if (active) anchorsRef.current(next);
            },
          });
          if (!active) {
            stage.dispose();
            return;
          }
          stageRef.current = stage;
          // setCharacters stores the roster while the GLB is loading. The
          // onReady callback syncs it again so prop changes during that load
          // cannot leave the renderer with an empty or stale bench.
          syncStageRoster(stage);
        } catch {
          if (active) setStatus("failed");
        }
      })
      .catch(() => {
        if (active) setStatus("failed");
      });
    return () => {
      active = false;
      stageRef.current?.dispose();
      stageRef.current = null;
    };
  }, [syncStageRoster]);

  // Rebuilding the bench is keyed on identity, not on the array reference the
  // parent happens to hand over each render.
  const rosterKey = characters
    .map((item) => `${item.id}:${item.config.material_theme}`)
    .join("|");
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    syncStageRoster(stage);
  }, [rosterKey, syncStageRoster]);

  useEffect(() => {
    stageRef.current?.setResting(latestRestingRef.current);
  }, [resting]);

  const visualKey = characters
    .map((item) => `${item.id}:${visuals[item.id] ?? "idle"}`)
    .join("|");
  useEffect(() => {
    const stage = stageRef.current;
    if (!stage) return;
    applyStageVisuals(stage);
  }, [applyStageVisuals, visualKey]);

  const anchorById = new Map(anchors.map((anchor) => [anchor.id, anchor]));
  const speaking = speakingId ? anchorById.get(speakingId) : undefined;
  const speakingCharacter = characters.find((item) => item.id === speakingId);
  // A speaker standing in slot E would otherwise push its own bubble off the
  // right edge, so the bubble changes side once the head passes mid-stage.
  const bubbleSide = speaking && speaking.nx > 0.56 ? "left" : "right";

  return (
    <div className={styles.scene} data-scene-status={status}>
      <div
        aria-hidden="true"
        className={styles.backdrop}
        style={{ backgroundImage: `url(${STAGE_BACKDROP_ASSET})` }}
      />
      <div className={styles.canvasViewport}>
        <canvas
          className={styles.canvas}
          ref={canvasRef}
          hidden={status === "failed"}
        />

        {status === "loading" ? (
          <p className={styles.sceneNotice}>{loadingLabel}</p>
        ) : null}

        {status === "failed" ? (
          <div className={styles.sceneFallback}>
            <p>{unavailableLabel}</p>
            <ul>
              {characters.map((character) => (
                <li
                  key={character.id}
                  data-state={visuals[character.id] ?? "idle"}
                >
                  <span>{character.slot}</span>
                  {character.name}
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {status === "ready"
          ? characters.map((character) => {
              const anchor = anchorById.get(character.id);
              if (!anchor?.visible) return null;
              return (
                <span
                  className={styles.namePlate}
                  data-current={character.id === speakingId ? "true" : "false"}
                  key={character.id}
                  style={{ left: `${anchor.x}px`, top: `${anchor.y}px` }}
                >
                  {character.name}
                </span>
              );
            })
          : null}

        {status === "ready" && speaking?.visible && bubbleText ? (
          <div
            aria-live="polite"
            className={styles.bubble}
            data-side={bubbleSide}
            style={{ left: `${speaking.x}px`, top: `${speaking.y}px` }}
          >
            <span className={styles.bubbleWho}>{speakingCharacter?.name}</span>
            {bubbleText}
          </div>
        ) : null}
      </div>

      {overlay}
    </div>
  );
}
