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
  barragePause: string;
  barrageResume: string;
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
  barragePause: "Pause messages",
  barrageResume: "Resume messages",
  barrageCount: (count) => `${count} message${count === 1 ? "" : "s"}`,
  openInteraction: "Interact",
  hideInteraction: "Hide",
  transcriptToggle: "Transcript",
  interactionOpening: "Opening…",
  interactionClosedHint:
    "Open classroom messages to show a join code on the stage.",
};

export const betaStageLabelsZh: BetaStageLabels = {
  sceneLoading: "正在布席…",
  sceneUnavailable: "3D 讲席无法显示，辩论以文字继续。",
  barrageLane: "课堂弹幕",
  joinLabel: "扫码参与",
  barragePause: "暂停弹幕",
  barrageResume: "恢复弹幕",
  barrageCount: (count) => `${count} 条弹幕`,
  openInteraction: "开启课堂弹幕",
  hideInteraction: "隐藏",
  transcriptToggle: "发言记录",
  interactionOpening: "正在开启…",
  interactionClosedHint: "开启课堂弹幕后，讲席上会出现扫码入口。",
};

export function resolveBetaStageLabels(locale: string): BetaStageLabels {
  return locale === "zh" ? betaStageLabelsZh : defaultBetaStageLabels;
}
