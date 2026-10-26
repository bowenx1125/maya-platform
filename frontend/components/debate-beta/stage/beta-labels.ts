/**
 * Copy that only Debates (beta) uses.
 *
 * The classic stage's label table is shared and complete; adding beta-only
 * strings to it would make every caller of that surface carry them. This keeps
 * the new copy beside the new stage instead.
 */
export type BetaStageLabels = {
  sceneLoading: string;
  sceneUnavailable: string;
  barrageLane: string;
  joinLabel: string;
  barrageCount: (count: number) => string;
  openInteraction: string;
  hideInteraction: string;
  transcriptToggle: string;
  interactionOpening: string;
  interactionClosedHint: string;
};

export const defaultBetaStageLabels: BetaStageLabels = {
  sceneLoading: "Setting out the bench…",
  sceneUnavailable: "3D bench unavailable — the debate continues in text.",
  barrageLane: "Classroom messages",
  joinLabel: "Scan to join",
  barrageCount: (count) => `${count} message${count === 1 ? "" : "s"}`,
  openInteraction: "Interact",
  hideInteraction: "Hide",
  transcriptToggle: "Transcript",
  interactionOpening: "Opening…",
  interactionClosedHint:
    "Open classroom messages to show a join code on the stage.",
};
