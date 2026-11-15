/**
 * Client player for compiled debate performance timelines.
 *
 * The backend compiles one timeline per turn (gesture events anchored to word
 * timestamps, plus viseme windows) and the stage samples it against the audio
 * clock. Everything here is pure math on plain JSON, so a malformed timeline
 * degrades to the stage's procedural motion instead of breaking the scene.
 */

export type PerformanceTimelineEvent = {
  /** Start time in seconds on the turn's audio. */
  t: number;
  type: "gesture";
  clip: string;
  dur: number;
  fade_ms: number;
};

export type PerformanceVisemeWindow = {
  t0: number;
  t1: number;
  viseme: string;
  /** Backend-resolved mouth openness (0..1) for this window. */
  jaw: number;
};

export type PerformanceTimeline = {
  version: number;
  duration: number;
  emotion: string;
  posture: string;
  /** "timed" when viseme windows exist, "energy" for procedural fallback. */
  viseme: string;
  events?: PerformanceTimelineEvent[];
  visemes?: PerformanceVisemeWindow[];
};

export type BoneOffset = readonly [number, number, number];

/**
 * One rotation step for an arm channel: an axis in figure space (the rig's
 * root-local frame — +Y up, +Z facing forward, +X the figure's left; it need
 * not be normalized) plus an angle in radians. Steps compose in list order,
 * each rotating about figure-fixed axes, so "swing back, then lower" reads as
 * [[1,0,0,a],[0,0,1,b]] regardless of how the rig's bone-local axes are
 * oriented.
 */
export type ArmStep = readonly [number, number, number, number];

export type PerformanceSample = {
  /** 0..1 mouth openness; null tells the stage to keep its procedural mouth. */
  mouth: number | null;
  /** Euler offsets (radians) layered on top of the procedural motion frame. */
  head: BoneOffset | null;
  neck: BoneOffset | null;
  torso: BoneOffset | null;
  upperArmL: readonly ArmStep[] | null;
  upperArmR: readonly ArmStep[] | null;
  forearmL: readonly ArmStep[] | null;
  forearmR: readonly ArmStep[] | null;
  handL: readonly ArmStep[] | null;
  handR: readonly ArmStep[] | null;
};

const NO_SAMPLE: PerformanceSample = {
  mouth: null,
  head: null,
  neck: null,
  torso: null,
  upperArmL: null,
  upperArmR: null,
  forearmL: null,
  forearmR: null,
  handL: null,
  handR: null,
};

/**
 * The rigged figures expose arm chains (mixamorig LeftArm/RightArm and their
 * forearms and hands), so clips choreograph head, torso and arms. Amplitudes
 * stay small; each returns null outside its envelope so layers never fight
 * the rest pose. Arm channels are figure-space rotation steps (see ArmStep)
 * the stage converts per rig, so the same clip works across skeleton families;
 * figures without arm bones skip every channel.
 */
type ClipFrame = {
  head?: BoneOffset;
  neck?: BoneOffset;
  torso?: BoneOffset;
  upperArmL?: readonly ArmStep[];
  upperArmR?: readonly ArmStep[];
  forearmL?: readonly ArmStep[];
  forearmR?: readonly ArmStep[];
  handL?: readonly ArmStep[];
  handR?: readonly ArmStep[];
};

const ARM_CHANNELS = [
  "upperArmL",
  "upperArmR",
  "forearmL",
  "forearmR",
  "handL",
  "handR",
] as const;

/**
 * Turn-long base poses the compiler selects per emotion. Arm channels are
 * figure-space steps applied on top of the stage's relaxed hanging pose
 * (arms down and slightly out): [1,0,0,a] swings an arm back (negative
 * forward), [0,0,1,a] adducts the right arm toward the midline (negative
 * the left, positive raises it outward). They hold for the whole timeline
 * underneath transient clips, so they stay well inside the joints'
 * comfortable range — a held pose near the limit reads as stiffness within
 * seconds.
 */
const POSTURES: Record<string, ClipFrame> = {
  // Right hand rests behind the back while the left sits at the chest — the
  // classic composed debate stance, free arm ready to gesture.
  hand_behind_back: {
    upperArmR: [[1, 0, 0, 0.25]],
    forearmR: [[1, 0, 0, 0.7]],
    upperArmL: [[0, 0, 1, -0.35]],
    forearmL: [
      [0, 0, 1, -0.2],
      [1, 0, 0, -0.9],
    ],
  },
  open_palm_listening: {
    upperArmL: [
      [0, 0, 1, -0.3],
      [1, 0, 0, -0.25],
    ],
    forearmL: [[1, 0, 0, -1.1]],
    upperArmR: [[1, 0, 0, 0.15]],
    forearmR: [[1, 0, 0, -0.15]],
  },
  hand_on_chest: {
    upperArmR: [[0, 0, 1, 0.3]],
    forearmR: [
      [0, 0, 1, 0.2],
      [1, 0, 0, -0.95],
    ],
  },
};

const CLIPS: Record<string, (phase: number) => ClipFrame> = {
  emphasis: (p) => {
    const n = Math.sin(p * Math.PI);
    return {
      head: [0.16 * n, 0, 0],
      neck: [0.06 * n, 0, 0],
      forearmL: [[1, 0, 0, -0.45 * n]],
    };
  },
  nod: (p) => {
    const n = Math.sin(p * Math.PI);
    return { head: [0.1 * n, 0, 0], neck: [0.04 * n, 0, 0] };
  },
  headshake: (p) => {
    const n = Math.sin(p * Math.PI) * Math.sin(p * Math.PI * 2);
    return { head: [0, 0.34 * n, 0], neck: [0, 0.1 * n, 0] };
  },
  settle_calm: (p) => {
    const n = Math.sin(p * Math.PI);
    return {
      head: [0.05 * n, 0, 0],
      torso: [0.05 * n, 0, 0],
      upperArmL: [[0, 0, 1, 0.1 * n]],
      upperArmR: [[0, 0, 1, -0.1 * n]],
      forearmL: [[1, 0, 0, -0.12 * n]],
      forearmR: [[1, 0, 0, -0.12 * n]],
    };
  },
  doubt_shrug: (p) => {
    const n = Math.sin(p * Math.PI);
    return {
      head: [0, 0, 0.14 * n],
      neck: [0, 0, 0.08 * n],
      torso: [0, 0, 0.05 * n],
      upperArmL: [[0, 0, 1, 0.35 * n]],
      upperArmR: [[0, 0, 1, -0.35 * n]],
      forearmL: [[1, 0, 0, -0.4 * n]],
      forearmR: [[1, 0, 0, -0.4 * n]],
    };
  },
  invite_present: (p) => {
    const n = Math.sin(p * Math.PI);
    return {
      head: [0.02 * n, 0.24 * n, 0.08 * n],
      neck: [0, 0.1 * n, 0],
      torso: [0, 0.1 * n, 0],
      upperArmL: [
        [1, 0, 0, -0.5 * n],
        [0, 0, 1, 0.15 * n],
      ],
      forearmL: [[1, 0, 0, -0.25 * n]],
    };
  },
  chin_stroke: (p) => {
    const n = Math.sin(p * Math.PI);
    return {
      head: [0.12 * n, 0, 0.1 * n],
      neck: [0.05 * n, 0, 0],
      upperArmL: [[0, 0, 1, -0.4 * n]],
      forearmL: [[1, 0, 0, -1.35 * n]],
      handL: [[0, 1, 0, -0.2 * n]],
    };
  },
  turn_ack: (p) => {
    const n = Math.sin(p * Math.PI);
    return { head: [0.2 * n, 0, 0], neck: [0.08 * n, 0, 0] };
  },
  palm_open_sweep: (p) => {
    const n = Math.sin(p * Math.PI);
    const sweep = Math.sin(p * Math.PI * 2);
    return {
      head: [0.03 * n, 0.18 * sweep, 0],
      neck: [0, 0.06 * sweep, 0],
      torso: [0, 0.12 * sweep, 0],
      upperArmL: [
        [1, 0, 0, -0.45 * n],
        [0, 1, 0, -0.2 * sweep * n],
      ],
      forearmL: [[1, 0, 0, -0.3 * n]],
    };
  },
  lean_in: (p) => {
    const n = Math.sin(p * Math.PI);
    return {
      head: [0.12 * n, 0, 0],
      neck: [0.06 * n, 0, 0],
      torso: [0.22 * n, 0, 0],
      upperArmL: [[1, 0, 0, 0.15 * n]],
      upperArmR: [[1, 0, 0, 0.15 * n]],
    };
  },
  object_raise: (p) => {
    const n = Math.sin(p * Math.PI);
    return {
      head: [0.04 * n, -0.1 * n, 0],
      torso: [0, -0.08 * n, 0],
      upperArmL: [
        [0, 0, 1, -0.5 * n],
        [1, 0, 0, -0.3 * n],
      ],
      forearmL: [[1, 0, 0, -0.5 * n]],
    };
  },
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function asFiniteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/**
 * Closed parser for the compiled JSON. Anything unexpected returns null so
 * the caller keeps procedural animation; a timeline is an enhancement, never
 * a reason to fail a turn.
 */
export function parsePerformanceTimeline(
  value: unknown,
): PerformanceTimeline | null {
  if (!isRecord(value)) return null;
  const version = asFiniteNumber(value.version);
  const duration = asFiniteNumber(value.duration);
  if (version !== 2 || duration === null || duration <= 0) return null;
  const timeline: PerformanceTimeline = {
    version: 2,
    duration,
    emotion: typeof value.emotion === "string" ? value.emotion : "calm",
    posture: typeof value.posture === "string" ? value.posture : "",
    viseme: typeof value.viseme === "string" ? value.viseme : "energy",
  };
  if (Array.isArray(value.events)) {
    const events: PerformanceTimelineEvent[] = [];
    for (const raw of value.events) {
      if (!isRecord(raw)) continue;
      const t = asFiniteNumber(raw.t);
      const dur = asFiniteNumber(raw.dur);
      const fade = asFiniteNumber(raw.fade_ms);
      if (
        t === null ||
        dur === null ||
        dur <= 0 ||
        fade === null ||
        raw.type !== "gesture" ||
        typeof raw.clip !== "string" ||
        !CLIPS[raw.clip]
      ) {
        continue;
      }
      events.push({ t, type: "gesture", clip: raw.clip, dur, fade_ms: fade });
    }
    events.sort((a, b) => a.t - b.t);
    timeline.events = events;
  }
  if (Array.isArray(value.visemes)) {
    const windows: PerformanceVisemeWindow[] = [];
    for (const raw of value.visemes) {
      if (!isRecord(raw)) continue;
      const t0 = asFiniteNumber(raw.t0);
      const t1 = asFiniteNumber(raw.t1);
      const jaw = asFiniteNumber(raw.jaw);
      if (t0 === null || t1 === null || t1 <= t0 || jaw === null) continue;
      windows.push({
        t0,
        t1,
        viseme: typeof raw.viseme === "string" ? raw.viseme : "",
        jaw: Math.min(1, Math.max(0, jaw)),
      });
    }
    timeline.visemes = windows;
  }
  return timeline;
}

function smoothstep(edge0: number, edge1: number, x: number): number {
  const t = Math.min(1, Math.max(0, (x - edge0) / (edge1 - edge0)));
  return t * t * (3 - 2 * t);
}

export type PerformancePlayer = {
  readonly duration: number;
  sample: (audioTimeSec: number) => PerformanceSample;
};

export function createPerformancePlayer(
  timeline: PerformanceTimeline,
): PerformancePlayer {
  const events = timeline.events ?? [];
  const windows = timeline.visemes ?? [];
  const posture = POSTURES[timeline.posture] ?? null;
  return {
    duration: timeline.duration,
    sample(audioTimeSec: number): PerformanceSample {
      if (!(audioTimeSec >= 0)) return NO_SAMPLE;
      let mouth: number | null = null;
      if (windows.length > 0) {
        // Windows are time-ordered; scan from the end where the playhead
        // usually sits. Gaps between windows close the mouth.
        mouth = 0;
        for (let i = windows.length - 1; i >= 0; i -= 1) {
          const window = windows[i];
          if (audioTimeSec >= window.t0 && audioTimeSec < window.t1) {
            mouth = window.jaw;
            break;
          }
          if (window.t1 <= audioTimeSec) break;
        }
      }
      for (let i = events.length - 1; i >= 0; i -= 1) {
        const event = events[i];
        if (audioTimeSec < event.t) continue;
        const phase = (audioTimeSec - event.t) / event.dur;
        if (phase >= 1) break;
        const frame = CLIPS[event.clip](phase);
        const fadeSec = Math.min(event.fade_ms / 1000, event.dur / 2);
        const env =
          fadeSec > 0
            ? smoothstep(0, fadeSec, audioTimeSec - event.t) *
              smoothstep(event.dur, event.dur - fadeSec, audioTimeSec - event.t)
            : 1;
        const sample: PerformanceSample = { ...NO_SAMPLE, mouth };
        for (const channel of ["head", "neck", "torso"] as const) {
          const base = posture?.[channel];
          const gesture = frame[channel];
          if (!base && !gesture) continue;
          // Posture holds underneath; the transient clip layers on top, so a
          // free arm can still move while the other stays behind the back.
          sample[channel] = [
            (base?.[0] ?? 0) + (gesture?.[0] ?? 0) * env,
            (base?.[1] ?? 0) + (gesture?.[1] ?? 0) * env,
            (base?.[2] ?? 0) + (gesture?.[2] ?? 0) * env,
          ];
        }
        for (const channel of ARM_CHANNELS) {
          const base = posture?.[channel];
          const gesture = frame[channel];
          if (!base && !gesture) continue;
          // Posture steps apply first; the clip's steps layer on top with
          // their angles scaled by the gesture envelope.
          const steps: ArmStep[] = base ? [...base] : [];
          if (gesture) {
            for (const [x, y, z, a] of gesture) steps.push([x, y, z, a * env]);
          }
          sample[channel] = steps;
        }
        return sample;
      }
      if (!posture) return { ...NO_SAMPLE, mouth };
      const sample: PerformanceSample = { ...NO_SAMPLE, mouth };
      for (const channel of ARM_CHANNELS) {
        const base = posture[channel];
        if (base) sample[channel] = [...base];
      }
      return sample;
    },
  };
}
