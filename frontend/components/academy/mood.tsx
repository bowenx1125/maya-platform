"use client";

import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useState,
  type ReactNode,
} from "react";

/**
 * What the scholars in the illustration are doing.
 *
 * The form lives in one panel and the characters in the other, so the mood
 * travels through context rather than through props threaded across the
 * layout.
 *
 * - `idle` follows the cursor
 * - `attentive` looks at the field being filled in
 * - `discreet` turns away, used while a password is on screen
 * - `refused` shakes, used once when a sign-in was rejected
 */
export type AcademyMood = "idle" | "attentive" | "discreet" | "refused";

type MoodContextValue = {
  mood: AcademyMood;
  setMood: (mood: AcademyMood) => void;
};

const MoodContext = createContext<MoodContextValue | null>(null);

export function AcademyMoodProvider({ children }: { children: ReactNode }) {
  const [mood, setMoodState] = useState<AcademyMood>("idle");
  const setMood = useCallback((next: AcademyMood) => setMoodState(next), []);
  const value = useMemo(() => ({ mood, setMood }), [mood, setMood]);
  return <MoodContext.Provider value={value}>{children}</MoodContext.Provider>;
}

export function useAcademyMood(): AcademyMood {
  return useContext(MoodContext)?.mood ?? "idle";
}

/**
 * Return a setter that is safe to call from a form rendered outside the
 * provider, so the sign-in form keeps working on its own in tests.
 */
export function useSetAcademyMood(): (mood: AcademyMood) => void {
  const context = useContext(MoodContext);
  return useMemo(() => context?.setMood ?? (() => undefined), [context]);
}

/** Field-level handlers a form can spread onto an input. */
export function useMoodHandlers(mood: AcademyMood) {
  const setMood = useSetAcademyMood();
  return useMemo(
    () => ({
      onFocus: () => setMood(mood),
      onBlur: () => setMood("idle"),
    }),
    [mood, setMood],
  );
}
