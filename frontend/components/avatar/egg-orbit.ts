/** Radians of yaw per CSS pixel of horizontal drag. */
export const EGG_ORBIT_YAW_PER_PX = 0.01;

/**
 * Preview-only body yaw from a horizontal drag. Dragging right spins the egg
 * so the front moves with the pointer (negative Three.js Y rotation).
 * Ephemeral — never written to drawing / avatar_config.
 */
export function eggOrbitYawAfterDrag(
  yaw: number,
  deltaX: number,
  radiansPerPx = EGG_ORBIT_YAW_PER_PX,
): number {
  if (!Number.isFinite(deltaX) || deltaX === 0) return yaw;
  return yaw - deltaX * radiansPerPx;
}

/**
 * Release inertia. Reduced-motion callers pass velocity 0 so the egg stops
 * where the pointer left it (no auto-spin).
 */
export function eggOrbitYawAfterInertia(
  yaw: number,
  velocity: number,
  dt: number,
  reducedMotion: boolean,
): { yaw: number; velocity: number } {
  if (
    reducedMotion ||
    !Number.isFinite(velocity) ||
    Math.abs(velocity) < 1e-4
  ) {
    return { yaw, velocity: 0 };
  }
  const nextYaw = yaw + velocity * dt;
  const nextVelocity = velocity * Math.exp(-4.5 * dt);
  if (Math.abs(nextVelocity) < 1e-3) return { yaw: nextYaw, velocity: 0 };
  return { yaw: nextYaw, velocity: nextVelocity };
}
