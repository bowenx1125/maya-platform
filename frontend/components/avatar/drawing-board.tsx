"use client";

import { useEffect, useRef, useState, type PointerEvent } from "react";
import { createPortal } from "react-dom";
import { PlatformApiError } from "../../lib/api";
import { Button } from "../ui/button";
import { ErrorNotice } from "../ui";
import { WorkspaceIcon } from "../workspace-icon";
import { EggCanvas } from "./egg-canvas";
import { EGG_PROFILE as P, eggRadius } from "../stage3d/egg-profile";
import {
  BLANK_DRAWING,
  EGG_VIEW,
  boardPoint,
  boardPosition,
  clampMouth,
  eraseStrokes,
  sameDrawing,
  strokeHits,
  type Drawing,
  type Point,
  type Tool,
} from "./drawing";
import styles from "./drawing-board.module.css";

type Props = {
  open: boolean;
  drawing?: Drawing | null;
  onClose: () => void;
  onSave: (drawing: Drawing, idempotencyKey: string) => Promise<void>;
  onPreview: (drawing: Drawing) => void;
};
type Gesture = {
  id: number;
  strokeId: string;
  before: Drawing;
  points: Point[];
  tool: Tool;
  touched: Set<string>;
  start: Point;
  mouth: Point;
};

export function DrawingBoard(props: Props) {
  return props.open ? <DrawingSession {...props} /> : null;
}
function DrawingSession({
  drawing: initial,
  onClose,
  onSave,
  onPreview,
}: Props) {
  const [drawing, setDrawingState] = useState(initial ?? BLANK_DRAWING);
  const [history, setHistory] = useState<Drawing[]>([]);
  const [tool, setTool] = useState<Tool>("pen");
  const [options, setOptions] = useState(false);
  const [color, setColor] = useState("#111111");
  const [width, setWidth] = useState(8);
  const [faded, setFaded] = useState<ReadonlySet<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [size, setSize] = useState({ width: 1, height: 1 });
  const [cursor, setCursor] = useState<Point | null>(null);
  const stage = useRef<HTMLDivElement>(null);
  const dialog = useRef<HTMLDivElement>(null);
  const gesture = useRef<Gesture | null>(null);
  const current = useRef(drawing);
  function setDrawing(next: Drawing) {
    current.current = next;
    setDrawingState(next);
  }
  const saveAttempt = useRef<{ body: string; key: string } | null>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const overflow = document.body.style.overflow;
    const rootOverflow = document.documentElement.style.overflow;
    const gutter = document.documentElement.style.scrollbarGutter;
    document.documentElement.style.overflow = "hidden";
    document.documentElement.style.scrollbarGutter = "auto";
    document.body.style.overflow = "hidden";
    dialog.current?.focus();
    const element = stage.current!;
    const observer = new ResizeObserver(() =>
      setSize({ width: element.clientWidth, height: element.clientHeight }),
    );
    observer.observe(element);
    window.addEventListener("blur", cancel);
    return () => {
      observer.disconnect();
      window.removeEventListener("blur", cancel);
      document.body.style.overflow = overflow;
      document.documentElement.style.overflow = rootOverflow;
      document.documentElement.style.scrollbarGutter = gutter;
      previous?.focus();
    };
  }, []);
  function point(event: PointerEvent): Point {
    const r = stage.current!.getBoundingClientRect();
    return boardPoint(
      event.clientX - r.left,
      event.clientY - r.top,
      r.width,
      r.height,
    );
  }
  function cancel() {
    if (gesture.current) setDrawing(gesture.current.before);
    gesture.current = null;
    setFaded(new Set());
  }
  function move(event: PointerEvent) {
    const p = point(event);
    setCursor({ x: event.clientX, y: event.clientY });
    const g = gesture.current;
    if (!g) {
      if (tool === "stroke")
        setFaded(
          new Set(
            drawing.strokes.filter((s) => strokeHits(s, [p])).map((s) => s.id),
          ),
        );
      return;
    }
    if (g.id !== event.pointerId) return;
    const bounded = {
      x: Math.max(0, Math.min(1, p.x)),
      y: Math.max(0, Math.min(1, p.y)),
    };
    if (g.points.length >= 4096) return;
    g.points.push(bounded);
    if (g.tool === "mouth") {
      setDrawing({
        ...g.before,
        mouth: clampMouth({
          x: g.mouth.x + p.x - g.start.x,
          y: g.mouth.y + p.y - g.start.y,
        }),
      });
    } else if (g.tool === "pen") {
      const stroke = {
        id: g.strokeId,
        color,
        width: width / 1024,
        opacity: 1,
        erasures: [],
        points: [...g.points],
      };
      setDrawing({ ...g.before, strokes: [...g.before.strokes, stroke] });
    } else if (g.tool === "stroke") {
      for (const s of g.before.strokes)
        if (strokeHits(s, g.points.slice(-2))) g.touched.add(s.id);
      setFaded(new Set(g.touched));
    } else {
      const eraseWidth = Math.max(16, width) / 1024;
      for (const s of g.before.strokes) {
        if (
          !g.touched.has(s.id) &&
          strokeHits(s, g.points.slice(-2), eraseWidth)
        )
          g.touched.add(s.id);
      }
      setDrawing(
        g.touched.size
          ? {
              ...g.before,
              strokes: g.before.strokes.map((s) =>
                g.touched.has(s.id)
                  ? {
                      ...s,
                      erasures: [
                        ...(s.erasures ?? []),
                        { width: eraseWidth, points: [...g.points] },
                      ],
                    }
                  : s,
              ),
            }
          : g.before,
      );
    }
  }
  const mouth = boardPosition(drawing.mouth, size.width, size.height);
  const mouthWidth =
    (2 *
      eggRadius(P.mouthHeight) *
      P.mouthWidthRatio *
      Math.min(size.width, size.height)) /
    EGG_VIEW.height;
  async function save() {
    if (gesture.current || saving) return;
    const body = JSON.stringify(drawing);
    if (saveAttempt.current?.body !== body)
      saveAttempt.current = { body, key: crypto.randomUUID() };
    setSaving(true);
    setError(null);
    try {
      await onSave(drawing, saveAttempt.current.key);
      onClose();
    } catch (cause) {
      // These Save-specific messages share codes with unrelated catalog copy.
      const saveMessage =
        cause instanceof PlatformApiError &&
        ((cause.code === "avatar_missing" &&
          cause.message ===
            "Your drawing couldn't be saved because it is too large or damaged. Undo some strokes or redraw it, then save again.") ||
          (cause.code === "invalid_state" &&
            cause.message ===
              "This Agent was deleted or deactivated, so it can't be saved. Go back to Agents and open an active one."));
      setError(saveMessage ? new Error(cause.message) : cause);
    } finally {
      setSaving(false);
    }
  }
  return createPortal(
    <div className={styles.backdrop}>
      <div
        ref={dialog}
        tabIndex={-1}
        className={styles.page}
        role="dialog"
        aria-modal="true"
        aria-label="Avatar"
        onKeyDown={(e) => {
          if (e.key === "Escape" && !saving) {
            e.preventDefault();
            cancel();
            onClose();
          }
          if (e.key === "Tab") {
            const items = dialog.current?.querySelectorAll<HTMLElement>(
              "button:not(:disabled), input",
            );
            if (!items?.length) return;
            const first = items[0],
              last = items[items.length - 1];
            if (
              e.shiftKey &&
              (document.activeElement === first ||
                document.activeElement === dialog.current)
            ) {
              e.preventDefault();
              last.focus();
            } else if (!e.shiftKey && document.activeElement === last) {
              e.preventDefault();
              first.focus();
            }
          }
        }}
      >
        <header className={styles.header}>
          <h1>Avatar</h1>
          <Button
            variant="neutral"
            className={styles.preview}
            disabled={saving}
            onClick={() => {
              cancel();
              onPreview(current.current);
            }}
          >
            <WorkspaceIcon name="play" />
            Preview
          </Button>
        </header>
        <div
          ref={stage}
          className={styles.stage}
          aria-label="Avatar drawing canvas"
          onPointerDown={(e) => {
            if (
              saving ||
              gesture.current ||
              !e.isPrimary ||
              (e.pointerType === "mouse" && e.button !== 0)
            )
              return;
            const p = point(e);
            const m = boardPosition(drawing.mouth, size.width, size.height);
            const r = stage.current!.getBoundingClientRect();
            const mouthTarget =
              e.target instanceof Element &&
              e.target.closest("button")?.getAttribute("aria-label") ===
                "Mouth";
            const hit =
              mouthTarget ||
              (Math.abs(e.clientX - r.left - m.x) <= mouthWidth / 2 + 16 &&
                Math.abs(e.clientY - r.top - m.y) <= 22);
            const active = hit ? "mouth" : tool;
            if (active === "mouth" && !hit) return;
            if (active === "pen" && drawing.strokes.length >= 256) return;
            if (hit) {
              setTool("mouth");
              setOptions(false);
            }
            gesture.current = {
              id: e.pointerId,
              strokeId: crypto.randomUUID(),
              before: drawing,
              points: [],
              tool: active,
              touched: new Set(),
              start: p,
              mouth: drawing.mouth,
            };
            e.currentTarget.setPointerCapture(e.pointerId);
            move(e);
          }}
          onPointerMove={move}
          onPointerUp={(e) => {
            const g = gesture.current;
            if (!g || g.id !== e.pointerId) return;
            move(e);
            const next =
              g.tool === "stroke"
                ? eraseStrokes(g.before, g.touched)
                : current.current;
            if (!sameDrawing(g.before, next)) {
              setHistory((h) => [...h.slice(-49), g.before]);
              setDrawing(next);
            }
            gesture.current = null;
            setFaded(new Set());
          }}
          onPointerCancel={cancel}
          onLostPointerCapture={() => {
            if (gesture.current) cancel();
          }}
          onPointerLeave={() => {
            if (!gesture.current) {
              setCursor(null);
              setFaded(new Set());
            }
          }}
        >
          <div
            className={styles.character}
            style={{
              width: Math.min(size.width, size.height),
              height: Math.min(size.width, size.height),
            }}
          >
            <EggCanvas drawing={drawing} faded={faded} />
          </div>
          <button
            type="button"
            aria-label="Mouth"
            aria-pressed={tool === "mouth"}
            className={`${styles.mouth} ${tool === "mouth" ? styles.selected : ""}`}
            style={{ left: mouth.x, top: mouth.y, width: mouthWidth + 22 }}
            onClick={() => {
              setTool("mouth");
              setOptions(false);
            }}
            disabled={saving}
          >
            {tool === "mouth" ? (
              <span>
                <WorkspaceIcon name="move" size={22} />
              </span>
            ) : null}
          </button>
        </div>
        {error ? <ErrorNotice inline error={error} /> : null}
        <section className={styles.toolbar} aria-label="Drawing tools">
          {options ? (
            <div className={styles.options}>
              <div className={styles.swatches}>
                {["#111111", "#8C4B9E", "#177E83", "#FF4D8D", "#F59E0B"].map(
                  (c) => (
                    <button
                      type="button"
                      key={c}
                      aria-label={c}
                      aria-pressed={color === c}
                      style={{ background: c }}
                      onClick={() => setColor(c)}
                    />
                  ),
                )}
                <label className={styles.custom}>
                  <WorkspaceIcon name="palette" />
                  <input
                    type="color"
                    aria-label="Custom color"
                    value={color}
                    onChange={(e) => setColor(e.target.value)}
                  />
                </label>
              </div>
              <div className={styles.width}>
                <i />
                <input
                  aria-label="Pen width"
                  type="range"
                  min="1"
                  max="28"
                  step="0.1"
                  value={width}
                  onChange={(e) => setWidth(+e.target.value)}
                />
                <i />
              </div>
            </div>
          ) : null}
          <div className={styles.tools}>
            {(
              [
                ["pen", "Pen"],
                ["stroke", "Stroke"],
                ["pixel", "Pixel"],
                ["mouth", "Mouth"],
              ] as const
            ).map(([t, label]) => (
              <Button
                key={t}
                variant="neutral"
                className={`${styles.tool} ${tool === t ? styles.active : ""}`}
                aria-pressed={tool === t}
                disabled={saving}
                onClick={() => {
                  cancel();
                  setOptions(
                    t === "pen" ? (tool === "pen" ? !options : true) : false,
                  );
                  setTool(t);
                }}
              >
                <WorkspaceIcon name={t} />
                {label}
              </Button>
            ))}
            <Button
              variant="neutral"
              className={styles.tool}
              disabled={saving || !history.length}
              onClick={() => {
                cancel();
                setDrawing(history[history.length - 1]);
                setHistory((h) => h.slice(0, -1));
              }}
            >
              <WorkspaceIcon name="undo" />
              Undo
            </Button>
          </div>
          <div className={styles.actions}>
            <Button
              variant="neutral"
              disabled={saving}
              onClick={() => {
                cancel();
                onClose();
              }}
            >
              <WorkspaceIcon name="back" />
              Back
            </Button>
            <Button
              className={styles.save}
              busy={saving}
              onClick={() => void save()}
            >
              <WorkspaceIcon name="save" />
              Save
            </Button>
          </div>
        </section>
        {cursor && (tool === "pixel" || tool === "stroke") ? (
          <span
            aria-hidden="true"
            className={styles.cursor}
            style={{
              left: cursor.x,
              top: cursor.y,
              width:
                tool === "pixel"
                  ? (((Math.max(16, width) *
                      Math.min(size.width, size.height)) /
                      EGG_VIEW.height) *
                      P.height) /
                    1024
                  : 20,
              height:
                tool === "pixel"
                  ? (((Math.max(16, width) *
                      Math.min(size.width, size.height)) /
                      EGG_VIEW.height) *
                      P.height) /
                    1024
                  : 20,
            }}
          >
            {tool === "stroke" ? (
              <WorkspaceIcon name="stroke" size={16} />
            ) : null}
          </span>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}
