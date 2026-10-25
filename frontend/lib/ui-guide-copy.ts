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
  "teacher.personalAgents": {
    en: "Personal Agents and private sources are visible only to you.",
    zh: "个人 Agent 和私有来源仅你自己可见。",
  },
  "knowledge.edit": {
    en: "Open the Markdown editor for this source.",
    zh: "打开此知识源的 Markdown 编辑器。",
  },
  "knowledge.view": {
    en: "Read the current source without changing it.",
    zh: "查看当前来源，不会修改内容。",
  },
  "knowledge.download": {
    en: "Download this source as a Markdown file.",
    zh: "将此知识源下载为 Markdown 文件。",
  },
  "knowledge.reindex": {
    en: "Rebuild the search index for this source.",
    zh: "为此知识源重新建立检索索引。",
  },
  "knowledge.indexFailed": {
    en: "Markdown indexing failed. The source is retained.",
    zh: "Markdown 索引失败；来源文件仍保留。",
  },
  "knowledge.hide": {
    en: "Hide this source from the active Brainform library. Existing snapshots stay available.",
    zh: "从当前 Brainform 资源列表隐藏此来源；已有快照仍可使用。",
  },
  "knowledge.filename": {
    en: "Full source filename.",
    zh: "来源文件完整名称。",
  },
  "knowledge.regenerate": {
    en: "Generate a new Knowledge version from the current Agent sources.",
    zh: "根据当前 Agent 资料生成新版 Knowledge。",
  },
  "agent.markdown": {
    en: "Write the Agent's identity, teaching style, and response guidance here.",
    zh: "在此编写 Agent 的身份、教学风格和回答指引。",
  },
  "agent.evidence": {
    en: "Choose knowledge files this Agent can use as evidence.",
    zh: "选择此 Agent 可用于回答的证据文件。",
  },
  "chat.teamMembers": {
    en: "Choose at least two available Agents and set exactly one Leader.",
    zh: "至少选择两个可用 Agent，并指定唯一组长。",
  },
  "chat.teamSharedKnowledge": {
    en: "Only selected Knowledge Sets will be shared with this Team.",
    zh: "只有选中的知识集会在此 Team 内共享。",
  },
  "agent.brainform": {
    en: "Choose RAG source files and existing Knowledge that this Agent can use.",
    zh: "选择此 Agent 可使用的 RAG 来源和现有 Knowledge。",
  },
  "agent.lastEdited": {
    en: "Latest version and last editor.",
    zh: "最新版本和最新编辑者。",
  },
  "agent.visibility": {
    en: "A Public personal Agent is shareable, but course students do not get access automatically. They need a separate invocation grant to use it; its prompt and sources remain visible only to its owner.",
    zh: "个人 Agent 设为公开后可分享，但课程学生不会自动获得访问权限。学生需要单独的调用授权才能使用；提示词和来源仍只有所有者可见。",
  },
  "agent.knowledgeSets": {
    en: "Selected Knowledge stays linked to its canonical set and uses its current version.",
    zh: "所选 Knowledge 始终引用同一知识集，并使用其当前版本。",
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
  "chat.pin": {
    en: "Pin or unpin this conversation at the top of your history.",
    zh: "将此对话置顶或取消置顶。",
  },
  "chat.history": {
    en: "Conversation name.",
    zh: "会话名称。",
  },
  "chat.send": {
    en: "Send this message to the selected Agent.",
    zh: "将此消息发送给当前选择的 Agent。",
  },
  "brainform.memory": {
    en: "Open the saved Memory context in Chatform.",
    zh: "在 Chatform 中打开已保存的 Memory 上下文。",
  },
  "brainform.record": {
    en: "Formal assessment results, grouped by the Team that ran the assessment.",
    zh: "正式测评的结果，按发起测评的 Team 分组。",
  },
  "chat.readOnly": {
    en: "This Agent is unavailable for new messages.",
    zh: "此 Agent 暂不可接收新消息。",
  },
  "debate.topic": {
    en: "Set the question the Agents will discuss. Keep it focused and answerable.",
    zh: "设置 Agent 要讨论的问题；尽量具体、可回答。",
  },
  "debate.stalled": {
    en: "See the safe failure reason for this stalled debate.",
    zh: "查看此辩论停滞的安全错误原因。",
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
  "debate.llmParams": {
    en: "Sampling settings frozen into the debate with its rules. Unchecked values are not sent to the model.",
    zh: "随规则一起固定进辩论的生成参数；不传的参数不会发给模型。",
  },
  "debate.llmParamsReset": {
    en: "Restore the server defaults for every parameter.",
    zh: "把所有参数恢复为服务器默认值。",
  },
  "debate.rulesetSave": {
    en: "Save these teaching instructions for future debates.",
    zh: "保存这些教学规则，供之后创建的辩论使用。",
  },
  "voice.consent": {
    en: "Confirm that you have permission to upload and clone this speaker's voice.",
    zh: "确认你已获准上传并克隆此说话者的声音。",
  },
  "voice.preview": {
    en: "Play a test sample to hear how the voice sounds.",
    zh: "播放试听样本，听听这个音色的效果。",
  },
  "voice.delete": {
    en: "Delete this voice profile.",
    zh: "删除此音色档案。",
  },
  "voice.cancelCreate": {
    en: "Cancel this new voice and return to the voice list.",
    zh: "取消新建音色，返回音色列表。",
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
  "knowledge.importFile": {
    en: "Import Markdown, PDF, or Word files. PDF and Word uploads are converted to Markdown for this library.",
    zh: "导入 Markdown、PDF 或 Word 文件；PDF 和 Word 会转换为 Markdown 后加入此知识库。",
  },
  "agent.uploadRag": {
    en: "Upload a Markdown, PDF or Word file as this Agent's RAG. It is Private or Public like the Agent.",
    zh: "上传 Markdown、PDF 或 Word 文件作为此 Agent 的 RAG，与该 Agent 同为私有或公开。",
  },
  "agent.uploadMarkdown": {
    en: "Upload a Markdown file for the next Agent draft revision.",
    zh: "上传 Markdown 文件，作为 Agent 的下一版草稿。",
  },
  "agent.uploadEvidence": {
    en: "Add Markdown, PDF, or Word files as Agent evidence. PDF and Word uploads are converted to Markdown.",
    zh: "添加 Markdown、PDF 或 Word 文件作为 Agent 证据；PDF 和 Word 会转换为 Markdown。",
  },
  "voice.uploadSample": {
    en: "Upload a 10–20 second clip of yourself reading aloud (16-bit WAV, MP3, or M4A; max 10 MB).",
    zh: "请上传 10–20 秒的朗读音频（念一段话；16 位 WAV / MP3 / M4A；不超过 10 MB）。",
  },
} as const satisfies Record<string, Record<Locale, string>>;

export type UiGuideKey = keyof typeof uiGuideCopy;

export function uiGuideText(key: string, locale: Locale): string | null {
  return Object.prototype.hasOwnProperty.call(uiGuideCopy, key)
    ? uiGuideCopy[key as UiGuideKey][locale]
    : null;
}
