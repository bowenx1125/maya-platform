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
  closeCollection: string;
  closeCollectionConfirm: string;
  closingCollection: string;
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
  closeCollection: "Close collection",
  closeCollectionConfirm:
    "Close collection? Students will no longer be able to submit, and the debate will keep running.",
  closingCollection: "Closing…",
};

export const betaStageLabelsZh: BetaStageLabels = {
  sceneLoading: "正在布席…",
  sceneUnavailable: "3D 讲席无法显示，辩论以文字继续。",
  barrageLane: "课堂弹幕",
  joinLabel: "扫码参与",
  barrageCount: (count) => `${count} 条弹幕`,
  openInteraction: "开启课堂弹幕",
  hideInteraction: "隐藏",
  transcriptToggle: "发言记录",
  interactionOpening: "正在开启…",
  interactionClosedHint: "开启课堂弹幕后，讲席上会出现扫码入口。",
  closeCollection: "关闭收集",
  closeCollectionConfirm: "关闭收集后，学生将无法继续提交，但辩论会继续进行。确定关闭吗？",
  closingCollection: "正在关闭…",
};

export function resolveBetaStageLabels(locale: string): BetaStageLabels {
  return locale === "zh" ? betaStageLabelsZh : defaultBetaStageLabels;
}
