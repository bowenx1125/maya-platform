import type {
  AvatarConfig,
  AvatarExpression,
  AvatarMotionStyle,
  AvatarState,
} from "./types";

export type AvatarMotionFrame = {
  rotationX: number;
  rotationY: number;
  rotationZ: number;
  mouthOpen: number;
  jawOpen: number;
};

const MOTION_FACTOR: Record<AvatarMotionStyle, number> = {
  calm: 0.65,
  active: 1,
};

/** Listening always uses the dedicated attentive expression. */
export function expressionForAvatarState(
  state: AvatarState,
  defaultExpression: AvatarExpression,
): AvatarExpression {
  return state === "listening" ? "attentive" : defaultExpression;
}

/**
 * Return deterministic presentation values for one animation frame. Keeping
 * this calculation pure makes state coverage testable without a WebGL context.
 */
export function avatarMotionFrame(
  state: AvatarState,
  elapsedSeconds: number,
  stateElapsedSeconds: number,
  motionStyle: AvatarMotionStyle,
): AvatarMotionFrame {
  const factor = MOTION_FACTOR[motionStyle];
  const pulse = Math.sin(elapsedSeconds * 1.7) * factor;
  let rotationX = 0;
  let rotationY = pulse * 0.035;
  let rotationZ = Math.sin(elapsedSeconds * 1.15) * 0.012 * factor;
  if (state === "thinking") {
    rotationZ = -0.055 + Math.sin(elapsedSeconds * 1.25) * 0.018;
    rotationY = -0.055;
  } else if (state === "nod_yes") {
    const envelope = Math.max(0, 1 - stateElapsedSeconds / 1.2);
    rotationX = Math.sin(stateElapsedSeconds * 11) * 0.075 * envelope;
  }
  if (state !== "speaking") {
    return { rotationX, rotationY, rotationZ, mouthOpen: 0, jawOpen: 0 };
  }
  const wave =
    (Math.sin(elapsedSeconds * 10) + Math.sin(elapsedSeconds * 17) * 0.35 + 1) /
    2;
  return {
    rotationX,
    rotationY,
    rotationZ,
    mouthOpen: 0.12 + wave * 0.42,
    jawOpen: wave * 0.22,
  };
}

export type AvatarMotionConfig = Pick<
  AvatarConfig,
  "default_expression" | "motion_style"
>;
