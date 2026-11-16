import { EGG_PROFILE as P, eggRadius } from "../stage3d/egg-profile";
import type { components } from "../../lib/api/generated/schema";

export type Drawing = components["schemas"]["AvatarDrawing"];
export type Point = { x: number; y: number };
export type Stroke = Drawing["strokes"][number];
export type Tool = "pen" | "stroke" | "pixel" | "mouth";
export const BLANK_DRAWING: Drawing = {
  version: 1,
  strokes: [],
  mouth: { x: 0.5, y: 0.435 },
};
export const DRAWING_WIDTH = P.height * P.widthRatio;
export const EGG_VIEW = { height: 3.12, centerY: 1.35 };

export function shellPoint(point: Point): Point {
  return {
    x: (point.x - 0.5) * DRAWING_WIDTH,
    y: P.bottom + (1 - point.y) * P.height,
  };
}
export function insideShell(point: Point): boolean {
  const local = shellPoint(point);
  return (
    point.y > 0 && point.y < 1 && Math.abs(local.x) < eggRadius(1 - point.y)
  );
}
export function boardPoint(
  x: number,
  y: number,
  width: number,
  height: number,
): Point {
  return {
    x:
      ((x - width / 2) * EGG_VIEW.height) /
        Math.min(width, height) /
        DRAWING_WIDTH +
      0.5,
    y:
      1 -
      (EGG_VIEW.centerY +
        ((height / 2 - y) * EGG_VIEW.height) / Math.min(width, height) -
        P.bottom) /
        P.height,
  };
}
export function boardPosition(
  point: Point,
  width: number,
  height: number,
): Point {
  const local = shellPoint(point);
  return {
    x: width / 2 + (local.x * Math.min(width, height)) / EGG_VIEW.height,
    y:
      height / 2 -
      ((local.y - EGG_VIEW.centerY) * Math.min(width, height)) /
        EGG_VIEW.height,
  };
}
export function clampMouth(point: Point): Point {
  return {
    x: Math.max(0.4, Math.min(0.6, point.x)),
    y: Math.max(0.3, Math.min(0.65, point.y)),
  };
}
// Hit tests and rasterization use shell-height units, so a round brush stays
// round even though the normalized drawing rectangle has a 0.76 aspect ratio.
const metric = (p: Point) => ({ x: p.x * P.widthRatio, y: p.y });
function distance(p: Point, a: Point, b: Point): number {
  p = metric(p);
  a = metric(a);
  b = metric(b);
  const dx = b.x - a.x,
    dy = b.y - a.y;
  const t = Math.max(
    0,
    Math.min(
      1,
      ((p.x - a.x) * dx + (p.y - a.y) * dy) / (dx * dx + dy * dy || 1),
    ),
  );
  return Math.hypot(p.x - a.x - t * dx, p.y - a.y - t * dy);
}
export function pathHit(
  point: Point,
  points: Point[],
  radius: number,
): boolean {
  return points.some(
    (p, i) => distance(point, points[Math.max(0, i - 1)], p) <= radius,
  );
}
export function visibleStrokeAt(stroke: Stroke, point: Point): boolean {
  return (
    insideShell(point) &&
    (stroke.opacity ?? 1) > 0 &&
    pathHit(point, stroke.points, stroke.width / 2) &&
    !(stroke.erasures ?? []).some((e) => pathHit(point, e.points, e.width / 2))
  );
}
export function strokeHits(
  stroke: Stroke,
  points: Point[],
  width = 0,
): boolean {
  // Sample the swept circle rather than hitting an erased parent centerline.
  for (let i = 0; i < points.length; i++) {
    const a = points[Math.max(0, i - 1)],
      b = points[i];
    const steps = Math.max(
      1,
      Math.ceil(Math.hypot((b.x - a.x) * P.widthRatio, b.y - a.y) / 0.001),
    );
    for (let j = 0; j <= steps; j++) {
      const p = {
        x: a.x + ((b.x - a.x) * j) / steps,
        y: a.y + ((b.y - a.y) * j) / steps,
      };
      if (visibleStrokeAt(stroke, p)) return true;
      if (width)
        for (let k = 0; k < 12; k++) {
          const angle = (k * Math.PI) / 6;
          if (
            visibleStrokeAt(stroke, {
              x: p.x + (Math.cos(angle) * width) / 2 / P.widthRatio,
              y: p.y + (Math.sin(angle) * width) / 2,
            })
          )
            return true;
        }
    }
  }
  return false;
}
export function erasePixels(
  drawing: Drawing,
  points: Point[],
  width: number,
): Drawing {
  let changed = false;
  const strokes = drawing.strokes.map((s) => {
    if (!strokeHits(s, points, width)) return s;
    changed = true;
    return { ...s, erasures: [...(s.erasures ?? []), { width, points }] };
  });
  return changed ? { ...drawing, strokes } : drawing;
}
export function eraseStrokes(
  drawing: Drawing,
  ids: ReadonlySet<string>,
): Drawing {
  return ids.size
    ? { ...drawing, strokes: drawing.strokes.filter((s) => !ids.has(s.id)) }
    : drawing;
}
export function sameDrawing(a: Drawing, b: Drawing): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

function paintPath(
  ctx: CanvasRenderingContext2D,
  points: Point[],
  width: number,
  color: string,
  size: number,
) {
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.lineWidth = width * size;
  ctx.strokeStyle = color;
  ctx.fillStyle = color;
  ctx.beginPath();
  points.forEach((p, i) => {
    if (i) ctx.lineTo(p.x * size * P.widthRatio, p.y * size);
    else ctx.moveTo(p.x * size * P.widthRatio, p.y * size);
  });
  if (points.length === 1) {
    ctx.arc(
      points[0].x * size * P.widthRatio,
      points[0].y * size,
      (width * size) / 2,
      0,
      Math.PI * 2,
    );
    ctx.fill();
  } else ctx.stroke();
}
export function renderDrawing(
  canvas: HTMLCanvasElement,
  drawing: Drawing,
  faded: ReadonlySet<string> = new Set(),
) {
  const size = 1024;
  canvas.width = Math.round(size * P.widthRatio);
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  const layer = document.createElement("canvas");
  layer.width = canvas.width;
  layer.height = size;
  const ink = layer.getContext("2d");
  if (!ink) return;
  for (const s of drawing.strokes) {
    ink.clearRect(0, 0, layer.width, size);
    ink.globalCompositeOperation = "source-over";
    paintPath(ink, s.points, s.width, s.color, size);
    ink.globalCompositeOperation = "destination-out";
    for (const e of s.erasures ?? [])
      paintPath(ink, e.points, e.width, "#000000", size);
    ctx.globalAlpha = (s.opacity ?? 1) * (faded.has(s.id) ? 0.25 : 1);
    ctx.drawImage(layer, 0, 0);
  }
  ctx.globalAlpha = 1;
}
