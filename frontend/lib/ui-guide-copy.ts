import type { Locale } from "./i18n";

export const uiGuideCopy = {
  "workspace.new": {
    en: "Create a new item in this workspace.",
    zh: "在当前工作区新建内容。",
  },
  "workspace.back": {
    en: "Return to the previous workspace page.",
    zh: "返回上一个工作区页面。",
  },
  "workspace.done": {
    en: "Complete the current workspace step.",
    zh: "完成当前工作区步骤。",
  },
  "workspace.logout": {
    en: "Sign out of this account.",
    zh: "退出当前账号。",
  },
  "knowledge.files": {
    en: "Files in this list are available to the group's knowledge search.",
    zh: "此列表中的文件可用于小组知识检索。",
  },
  "knowledge.edit": {
    en: "Open the Markdown editor for this source.",
    zh: "打开此知识源的 Markdown 编辑器。",
  },
  "knowledge.download": {
    en: "Download this source as a Markdown file.",
    zh: "将此知识源下载为 Markdown 文件。",
  },
  "knowledge.reindex": {
    en: "Rebuild the search index for this source.",
    zh: "为此知识源重新建立检索索引。",
  },
  "knowledge.hide": {
    en: "Hide this source from the active group library.",
    zh: "从当前小组知识库中隐藏此知识源。",
  },
  "knowledge.importFile": {
    en: "Import Markdown, PDF, or Word files. PDF and Word uploads are converted to Markdown for this library.",
    zh: "导入 Markdown、PDF 或 Word 文件；PDF 和 Word 会转换为 Markdown 后加入此知识库。",
  },
  "agent.markdown": {
    en: "Write the Agent's identity, teaching style, and response guidance here.",
    zh: "在此编写 Agent 的身份、教学风格和回答指引。",
  },
  "agent.evidence": {
    en: "Choose knowledge files this Agent can use as evidence.",
    zh: "选择此 Agent 可用于回答的证据文件。",
  },
  "agent.voice": {
    en: "Choose the saved voice profile used when this Agent speaks.",
    zh: "选择此 Agent 朗读时使用的语音配置。",
  },
  "agent.publish": {
    en: "Review the checks that must pass before publishing this version.",
    zh: "查看此版本发布前必须通过的检查。",
  },
  "agent.ragPreview": {
    en: "Preview the evidence this Agent can retrieve from its selected files.",
    zh: "预览此 Agent 能从所选文件中检索到的证据。",
  },
  "agent.snapshot": {
    en: "View the immutable knowledge snapshot used by this published version.",
    zh: "查看此已发布版本使用的固定知识快照。",
  },
  "agent.download": {
    en: "Download the file shown in this section.",
    zh: "下载此区域显示的文件。",
  },
  "agent.uploadMarkdown": {
    en: "Upload a Markdown file for the next Agent draft revision.",
    zh: "上传 Markdown 文件，作为 Agent 的下一版草稿。",
  },
  "agent.uploadEvidence": {
    en: "Add Markdown, PDF, or Word files as Agent evidence. PDF and Word uploads are converted to Markdown.",
    zh: "添加 Markdown、PDF 或 Word 文件作为 Agent 证据；PDF 和 Word 会转换为 Markdown。",
  },
  "roster.openGroup": {
    en: "Open this group's workspace and its shared resources.",
    zh: "打开此小组的工作区和共享资源。",
  },
  "roster.deleteAgent": {
    en: "Remove this Agent from the workspace. A confirmation will appear first.",
    zh: "从工作区移除此 Agent；操作前会先要求确认。",
  },
  "chat.delete": {
    en: "Delete this conversation from your chat history.",
    zh: "从聊天记录中删除此对话。",
  },
  "chat.send": {
    en: "Send this message to the selected Agent.",
    zh: "将此消息发送给当前选择的 Agent。",
  },
  "chat.readOnly": {
    en: "This Agent is unavailable for new messages.",
    zh: "此 Agent 暂不可接收新消息。",
  },
  "debate.topic": {
    en: "Set the question the Agents will discuss. Keep it focused and answerable.",
    zh: "设置 Agent 要讨论的问题；尽量具体、可回答。",
  },
  "debate.background": {
    en: "Add optional context for the debate. It is context, not verified evidence.",
    zh: "补充可选背景；背景只提供情境，不代表已验证的证据。",
  },
  "debate.agentOrder": {
    en: "Arrange the Agents in the order they will speak.",
    zh: "调整 Agent 的发言顺序。",
  },
  "debate.ruleset": {
    en: "These teaching instructions are frozen into debates when they are created.",
    zh: "这些教学规则会在创建辩论时固定保存。",
  },
  "debate.rulesetEdit": {
    en: "Edit the teaching instructions for future debates.",
    zh: "编辑之后新建辩论使用的教学规则。",
  },
  "debate.rulesetSave": {
    en: "Save these teaching instructions for future debates.",
    zh: "保存这些教学规则，供之后创建的辩论使用。",
  },
  "voice.consent": {
    en: "Confirm that you have permission to upload and clone this speaker's voice.",
    zh: "确认你已获准上传并克隆此说话者的声音。",
  },
  "voice.uploadSample": {
    en: "Choose the audio sample for this voice profile.",
    zh: "选择此语音配置要使用的音频样本。",
  },
  "camera.scene": {
    en: "Choose a classroom scene.",
    zh: "选择课堂场景。",
  },
  "camera.forward": {
    en: "Move the camera forward.",
    zh: "镜头向前移动。",
  },
  "camera.left": {
    en: "Move the camera left.",
    zh: "镜头向左移动。",
  },
  "camera.right": {
    en: "Move the camera right.",
    zh: "镜头向右移动。",
  },
  "camera.backward": {
    en: "Move the camera backward.",
    zh: "镜头向后移动。",
  },
  "camera.turnLeft": {
    en: "Turn the camera left.",
    zh: "镜头向左转。",
  },
  "camera.turnRight": {
    en: "Turn the camera right.",
    zh: "镜头向右转。",
  },
  "camera.aerial": {
    en: "Switch to the overhead camera view.",
    zh: "切换到俯视镜头。",
  },
} as const satisfies Record<string, Record<Locale, string>>;

export type UiGuideKey = keyof typeof uiGuideCopy;

export function uiGuideText(key: string, locale: Locale): string | null {
  return Object.prototype.hasOwnProperty.call(uiGuideCopy, key)
    ? uiGuideCopy[key as UiGuideKey][locale]
    : null;
}
