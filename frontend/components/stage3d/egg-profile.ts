/** C2 shell proportions and attachments, in the source GLB's world units. */
export const EGG_PROFILE = {
  height: 2.39,
  bottom: 0.31,
  widthRatio: 0.76,
  asymmetry: 0.22,
  handHeight: 0.4,
  footX: 0.3,
  mouthHeight: 0.565,
  mouthWidthRatio: 0.575,
} as const;

// An asymmetric ellipse has horizontal tangents at both poles. The lower
// half broadens without a pointed crown or a seam between separate curves.
const rawRadius = (h: number) =>
  2 *
  Math.sqrt(Math.max(0, h * (1 - h))) *
  (1 + EGG_PROFILE.asymmetry * (1 - 2 * h));
const widestHeight =
  (4 * EGG_PROFILE.asymmetry +
    1 -
    Math.sqrt(1 + 8 * EGG_PROFILE.asymmetry ** 2)) /
  (8 * EGG_PROFILE.asymmetry);
const maximum = rawRadius(widestHeight);

export function eggRadius(h: number): number {
  if (!Number.isFinite(h) || h < 0 || h > 1) return 0;
  return (
    (EGG_PROFILE.height * EGG_PROFILE.widthRatio * rawRadius(h)) / (2 * maximum)
  );
}

export function eggFrontZ(x: number, y: number): number {
  const r = eggRadius((y - EGG_PROFILE.bottom) / EGG_PROFILE.height);
  return Math.sqrt(Math.max(0, r * r - x * x));
}

export function eggMouthBeat(seconds: number): number {
  const t = ((seconds % 0.32) + 0.32) % 0.32;
  const smooth = (x: number) => x * x * (3 - 2 * x);
  if (t < 0.075) return smooth(t / 0.075);
  if (t < 0.17) return 1;
  if (t < 0.245) return 1 - smooth((t - 0.17) / 0.075);
  return 0;
}
