const STANDING_RADIUS = 1.6;

export function standingPlacement(index: number, count: number) {
  // The half step leaves the near edge of the table clear at every roster size.
  const angle =
    count === 1 ? 0 : -Math.PI + (2 * Math.PI * (index + 0.5)) / count;
  const x = Math.sin(angle) * STANDING_RADIUS;
  const z = -Math.cos(angle) * STANDING_RADIUS;
  const towardTable = Math.atan2(-x, -z);
  return { x, z, yaw: towardTable * (count === 2 ? 0.72 : 0.65) };
}
