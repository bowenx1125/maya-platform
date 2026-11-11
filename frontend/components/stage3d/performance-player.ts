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

export type PerformanceSample = {
  /** 0..1 mouth openness; null tells the stage to keep its procedural mouth. */
  mouth: number | null;
  /** Euler offsets (radians) layered on top of the procedural motion frame. */
  head: BoneOffset | null;
  neck: BoneOffset | null;
  torso: BoneOffset | null;
};

const NO_SAMPLE: PerformanceSample = {
  mouth: null,
  head: null,
  neck: null,
  torso: null,
};

/**
 * Gestures the two purchased figures can actually perform: their rigs expose
 * head, neck and torso bones but no fingers, so clips are choreographed on
 * those bones only. Amplitudes stay small; each returns null outside its
 * envelope so layers never fight the rest pose.
 */
type ClipFrame = {
  head?: BoneOffset;
  neck?: BoneOffset;
  torso?: BoneOffset;
};

const CLIPS: Record<string, (phase: number) => ClipFrame> = {
  emphasis: (p) => {
    const n = Math.sin(p * Math.PI);
    return { head: [0.16 * n, 0, 0], neck: [0.06 * n, 0, 0] };
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
    return { head: [0.05 * n, 0, 0], torso: [0.05 * n, 0, 0] };
  },
  doubt_shrug: (p) => {
    const n = Math.sin(p * Math.PI);
    return {
      head: [0, 0, 0.14 * n],
      neck: [0, 0, 0.08 * n],
      torso: [0, 0, 0.05 * n],
    };
  },
  invite_present: (p) => {
    const n = Math.sin(p * Math.PI);
    return {
      head: [0.02 * n, 0.24 * n, 0.08 * n],
      neck: [0, 0.1 * n, 0],
      torso: [0, 0.1 * n, 0],
    };
  },
  chin_stroke: (p) => {
    const n = Math.sin(p * Math.PI);
    return { head: [0.12 * n, 0, 0.1 * n], neck: [0.05 * n, 0, 0] };
  },
  turn_ack: (p) => {
    const n = Math.sin(p * Math.PI);
    return { head: [0.2 * n, 0, 0], neck: [0.08 * n, 0, 0] };
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
        const scale = (offset: BoneOffset): BoneOffset => [
          offset[0] * env,
          offset[1] * env,
          offset[2] * env,
        ];
        return {
          mouth,
          head: frame.head ? scale(frame.head) : null,
          neck: frame.neck ? scale(frame.neck) : null,
          torso: frame.torso ? scale(frame.torso) : null,
        };
      }
      return { ...NO_SAMPLE, mouth };
    },
  };
}
