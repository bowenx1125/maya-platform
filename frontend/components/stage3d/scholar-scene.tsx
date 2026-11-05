"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from "react";

import type { AvatarState } from "../avatar";
import type {
  StageAnchor,
  StageCameraCommand,
  StageCharacter,
} from "./scholar-stage";
import { StageCurtain } from "../loading/agent-loader";
import styles from "./stage3d.module.css";
import { requestedStageScenePack, STAGE_SCENE_PACKS } from "./scene-packs";

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
  /** Mount the bubble shell while audio is starting, even before text arrives. */
  bubbleOpen?: boolean;
  loadingLabel: string;
  unavailableLabel: string;
  layout?: "classroom" | "preview";
  /** Barrage lanes, the join card and the teacher's pause control. */
  overlay?: ReactNode;
  /** Called once the scene has loaded or failed: heavy downloads may start. */
  onSceneSettled?: () => void;
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
  bubbleOpen = false,
  loadingLabel,
  unavailableLabel,
  layout = "classroom",
  overlay,
  onSceneSettled,
}: ScholarSceneProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const stageRef = useRef<import("./scholar-stage").ScholarStage | null>(null);
  const latestCharactersRef = useRef(characters);
  const latestVisualsRef = useRef(visuals);
  const latestRestingRef = useRef(resting);
  const [status, setStatus] = useState<SceneStatus>("loading");
  const onSceneSettledRef = useRef(onSceneSettled);
  useEffect(() => {
    onSceneSettledRef.current = onSceneSettled;
  }, [onSceneSettled]);
  useEffect(() => {
    if (status !== "loading") onSceneSettledRef.current?.();
  }, [status]);
  const [anchors, setAnchors] = useState<StageAnchor[]>([]);
  const [viewportWidth, setViewportWidth] = useState(0);
  const [scenePackId, setScenePackId] = useState(
    () => requestedStageScenePack().id,
  );
  const [stageCameraControls] = useState(() => {
    if (typeof window === "undefined") return false;
    const search = new URLSearchParams(window.location.search);
    // Mirror stageBackdropMode's precedence: depth wins over splat, so a
    // splat-render that will never happen must not show dead camera buttons.
    // Kept inline because the stage class itself is imported dynamically.
    if (search.get("depth") === "1") return false;
    return search.get("splat") === "1";
  });

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
    setViewportWidth(canvasRef.current?.clientWidth ?? 0);
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

  const moveStageCamera = useCallback((command: StageCameraCommand) => {
    stageRef.current?.moveStageCamera(command);
  }, []);

  const resetStageCamera = useCallback(() => {
    stageRef.current?.resetStageCamera();
  }, []);

  const toggleStageOverview = useCallback(() => {
    stageRef.current?.toggleStageOverview();
  }, []);

  const changeScenePack = useCallback((id: string) => {
    setScenePackId(id);
    stageRef.current?.setScenePack(id);
    const url = new URL(window.location.href);
    url.searchParams.set("scene", id);
    window.history.replaceState(null, "", url);
  }, []);

  useEffect(() => {
    if (!stageCameraControls) return undefined;
    const commands: Record<string, StageCameraCommand> = {
      ArrowUp: "forward",
      w: "forward",
      W: "forward",
      ArrowDown: "backward",
      s: "backward",
      S: "backward",
      a: "left",
      A: "left",
      d: "right",
      D: "right",
      ArrowLeft: "turn-left",
      q: "turn-left",
      Q: "turn-left",
      ArrowRight: "turn-right",
      e: "turn-right",
      E: "turn-right",
    };
    const editableTarget = (target: EventTarget | null) =>
      target instanceof HTMLInputElement ||
      target instanceof HTMLTextAreaElement ||
      target instanceof HTMLSelectElement ||
      (target instanceof HTMLElement && target.isContentEditable);
    const handleKeyDown = (event: KeyboardEvent) => {
      const target = event.target;
      if (editableTarget(target)) return;
      if (["Home", "r", "R"].includes(event.key)) {
        event.preventDefault();
        resetStageCamera();
        return;
      }
      const command = commands[event.key];
      if (!command) return;
      event.preventDefault();
      stageRef.current?.setStageCameraInput(command, true);
    };
    const handleKeyUp = (event: KeyboardEvent) => {
      if (editableTarget(event.target)) return;
      const command = commands[event.key];
      if (!command) return;
      event.preventDefault();
      stageRef.current?.setStageCameraInput(command, false);
    };
    const handleBlur = () => stageRef.current?.clearStageCameraInput();
    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);
    window.addEventListener("blur", handleBlur);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
      window.removeEventListener("blur", handleBlur);
      handleBlur();
    };
  }, [resetStageCamera, stageCameraControls]);

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
  const bubbleWindow = Array.from(bubbleText ?? "")
    .slice(-52)
    .join("");
  const showBubble = Boolean(bubbleWindow) || bubbleOpen;
  const bubbleHalfWidth = Math.min(145, viewportWidth * 0.31);
  const bubbleX = speaking
    ? Math.max(
        bubbleHalfWidth + 8,
        Math.min(viewportWidth - bubbleHalfWidth - 8, speaking.x),
      )
    : 0;

  const nameAnchors = new Map<string, StageAnchor>();
  for (const source of [...anchors].sort((left, right) =>
    left.id.localeCompare(right.id),
  )) {
    if (!source.visible || (source.id === speakingId && showBubble)) continue;
    const anchor = { ...source };
    // Coincident or cramped heads need separate rows; only move a label
    // whose minimum readable box would collide with one already placed.
    for (let attempt = 0; attempt < anchors.length; attempt += 1) {
      const collision = [...nameAnchors.values()].find(
        (other) =>
          Math.abs(other.x - anchor.x) < 40 &&
          Math.abs(other.y - anchor.y) < 48,
      );
      if (!collision) break;
      anchor.y = collision.y + 48;
    }
    nameAnchors.set(anchor.id, anchor);
  }

  return (
    <div
      className={styles.scene}
      data-layout={layout}
      data-scene-status={status}
    >
      <div aria-hidden="true" className={styles.backdrop} />
      <div className={styles.canvasViewport}>
        <canvas
          className={styles.canvas}
          ref={canvasRef}
          hidden={status === "failed"}
        />

        {status !== "failed" ? (
          <StageCurtain loading={status === "loading"} label={loadingLabel} />
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
              const anchor = nameAnchors.get(character.id);
              if (!anchor) return null;
              if (character.id === speakingId && showBubble) return null;
              // Neighbouring labels own separate horizontal space; the CSS
              // clamp keeps short names over their heads within those bounds.
              const neighbours = [...nameAnchors.values()].filter(
                (other) =>
                  other.visible &&
                  other.id !== anchor.id &&
                  Math.abs(other.y - anchor.y) < 48,
              );
              const left = Math.max(
                8,
                ...neighbours
                  .filter((other) => other.x < anchor.x)
                  .map((other) => (other.x + anchor.x) / 2 + 4),
              );
              const right = Math.min(
                viewportWidth - 8,
                ...neighbours
                  .filter((other) => other.x > anchor.x)
                  .map((other) => (other.x + anchor.x) / 2 - 4),
              );
              const maxWidth = Math.min(160, right - left);
              if (maxWidth < 2)
                return (
                  <span className="sr-only" key={character.id}>
                    {character.name}
                  </span>
                );
              return (
                <span
                  className={styles.namePlate}
                  data-current={character.id === speakingId ? "true" : "false"}
                  aria-label={character.name}
                  key={character.id}
                  style={
                    {
                      left: `${anchor.x}px`,
                      top: `${anchor.y}px`,
                      maxWidth: `${maxWidth}px`,
                      "--name-plate-width": `${maxWidth}px`,
                      "--name-plate-left": `${left - anchor.x}px`,
                      "--name-plate-right": `${right - anchor.x}px`,
                    } as CSSProperties
                  }
                >
                  <span className={styles.namePlateText}>{character.name}</span>
                </span>
              );
            })
          : null}

        {status === "ready" && speaking?.visible && showBubble ? (
          <div
            aria-live="polite"
            className={styles.bubble}
            style={
              {
                left: `${bubbleX}px`,
                top: `${speaking.y}px`,
                "--bubble-pointer-offset": `${speaking.x - bubbleX}px`,
              } as CSSProperties
            }
          >
            <span className={styles.bubbleWho}>{speakingCharacter?.name}</span>
            {bubbleWindow}
          </div>
        ) : null}

        {status === "ready" && stageCameraControls ? (
          <>
            <label className={styles.scenePackPicker}>
              <span>Courtyard</span>
              <select
                aria-label="Switch courtyard scene"
                data-ui-guide="camera.scene"
                onChange={(event) => changeScenePack(event.target.value)}
                value={scenePackId}
              >
                {STAGE_SCENE_PACKS.map((pack) => (
                  <option key={pack.id} value={pack.id}>
                    {pack.label}
                  </option>
                ))}
              </select>
            </label>
            <div
              aria-label="Scene camera"
              className={styles.cameraControls}
              role="group"
            >
              <button
                aria-label="Move camera forward"
                className={styles.cameraForward}
                onClick={() => moveStageCamera("forward")}
                data-ui-guide="camera.forward"
                type="button"
              >
                ↑
              </button>
              <button
                aria-label="Turn camera left"
                className={styles.cameraTurnLeft}
                onClick={() => moveStageCamera("turn-left")}
                data-ui-guide="camera.turnLeft"
                type="button"
              >
                ↶
              </button>
              <button
                aria-label="Move camera left"
                className={styles.cameraLeft}
                onClick={() => moveStageCamera("left")}
                data-ui-guide="camera.left"
                type="button"
              >
                ←
              </button>
              <button
                aria-label="Toggle bird's-eye view"
                className={styles.cameraOverview}
                onClick={toggleStageOverview}
                data-ui-guide="camera.aerial"
                type="button"
              >
                ◎
              </button>
              <button
                aria-label="Move camera right"
                className={styles.cameraRight}
                onClick={() => moveStageCamera("right")}
                data-ui-guide="camera.right"
                type="button"
              >
                →
              </button>
              <button
                aria-label="Turn camera right"
                className={styles.cameraTurnRight}
                onClick={() => moveStageCamera("turn-right")}
                data-ui-guide="camera.turnRight"
                type="button"
              >
                ↷
              </button>
              <button
                aria-label="Move camera back"
                className={styles.cameraBackward}
                onClick={() => moveStageCamera("backward")}
                data-ui-guide="camera.backward"
                type="button"
              >
                ↓
              </button>
            </div>
          </>
        ) : null}
      </div>

      {overlay}
    </div>
  );
}
