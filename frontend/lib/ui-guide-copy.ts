export const uiGuideCopy = {
  "workspace.new": {
    en: "Create a new item in this workspace.",
  },
  "workspace.back": {
    en: "Return to the previous workspace page.",
  },
  "workspace.done": {
    en: "Complete the current workspace step.",
  },
  "workspace.logout": {
    en: "Sign out of this account.",
  },
  "knowledge.files": {
    en: "Files in this list are available to the group's knowledge search.",
  },
  "teacher.personalAgents": {
    en: "Personal Agents and private sources are visible only to you.",
  },
  "knowledge.edit": {
    en: "Open the Markdown editor for this source.",
  },
  "knowledge.view": {
    en: "Read the current source without changing it.",
  },
  "knowledge.download": {
    en: "Download this source as a Markdown file.",
  },
  "knowledge.reindex": {
    en: "Rebuild the search index for this source.",
  },
  "knowledge.indexFailed": {
    en: "Markdown indexing failed. The source is retained.",
  },
  "knowledge.hide": {
    en: "Hide this source from the active Brainform library. Existing snapshots stay available.",
  },
  "knowledge.filename": {
    en: "Full source filename.",
  },
  "knowledge.regenerate": {
    en: "Generate a new Knowledge version from the current Agent sources.",
  },
  "agent.markdown": {
    en: "Write the Agent's identity, teaching style, and response guidance here.",
  },
  "agent.evidence": {
    en: "Choose knowledge files this Agent can use as evidence.",
  },
  "chat.teamMembers": {
    en: "Choose at least two available Agents and set exactly one Leader.",
  },
  "chat.teamSharedKnowledge": {
    en: "Only selected Knowledge Sets will be shared with this Team.",
  },
  "agent.brainform": {
    en: "Choose RAG source files this Agent can use.",
  },
  "agent.lastEdited": {
    en: "Last editor.",
  },
  "agent.visibility": {
    en: "A Public personal Agent is shareable, but course students do not get access automatically. They need a separate invocation grant to use it; its prompt and sources remain visible only to its owner.",
  },
  "agent.knowledgeSets": {
    en: "Selected Knowledge stays linked to its canonical set and uses its current version.",
  },
  "agent.voice": {
    en: "Choose the saved voice profile used when this Agent speaks.",
  },
  "agent.publish": {
    en: "Review the checks that must pass before publishing this version.",
  },
  "agent.ragPreview": {
    en: "Preview the evidence this Agent can retrieve from its selected files.",
  },
  "agent.snapshot": {
    en: "View the immutable knowledge snapshot used by this published version.",
  },
  "agent.download": {
    en: "Download the file shown in this section.",
  },
  "roster.openGroup": {
    en: "Open this group's workspace and its shared resources.",
  },
  "roster.deleteAgent": {
    en: "Remove this Agent from the workspace. A confirmation will appear first.",
  },
  "chat.delete": {
    en: "Delete this conversation from your chat history.",
  },
  "chat.pin": {
    en: "Pin or unpin this conversation at the top of your history.",
  },
  "chat.history": {
    en: "Conversation name.",
  },
  "chat.send": {
    en: "Send this message to the selected Agent.",
  },
  "brainform.memory": {
    en: "Open the saved Memory context in Chatform.",
  },
  "brainform.record": {
    en: "Formal assessment results, grouped by the Team that ran the assessment.",
  },
  "chat.readOnly": {
    en: "This Agent is unavailable for new messages.",
  },
  "debate.topic": {
    en: "Set the question the Agents will discuss. Keep it focused and answerable.",
  },
  "debate.stalled": {
    en: "See the safe failure reason for this stalled debate.",
  },
  "debate.background": {
    en: "Add optional context for the debate. It is context, not verified evidence.",
  },
  "debate.agentOrder": {
    en: "Arrange the Agents in the order they will speak.",
  },
  "debate.targetLength": {
    en: "The spoken length the whole debate aims for, from 3 to 10 minutes.",
  },
  "debate.ruleset": {
    en: "These teaching instructions are frozen into debates when they are created.",
  },
  "debate.rulesetEdit": {
    en: "Edit the teaching instructions for future debates.",
  },
  "debate.llmParams": {
    en: "Sampling settings frozen into the debate with its rules. Unchecked values are not sent to the model.",
  },
  "debate.llmParamsReset": {
    en: "Restore the server defaults for every parameter.",
  },
  "debate.rulesetSave": {
    en: "Save these teaching instructions for future debates.",
  },
  "voice.consent": {
    en: "Confirm that you have permission to upload and clone this speaker's voice.",
  },
  "voice.preview": {
    en: "Play a test sample to hear how the voice sounds.",
  },
  "voice.delete": {
    en: "Delete this voice profile.",
  },
  "voice.cancelCreate": {
    en: "Cancel this new voice and return to the voice list.",
  },
  "camera.scene": {
    en: "Choose a classroom scene.",
  },
  "camera.forward": {
    en: "Move the camera forward.",
  },
  "camera.left": {
    en: "Move the camera left.",
  },
  "camera.right": {
    en: "Move the camera right.",
  },
  "camera.backward": {
    en: "Move the camera backward.",
  },
  "camera.turnLeft": {
    en: "Turn the camera left.",
  },
  "camera.turnRight": {
    en: "Turn the camera right.",
  },
  "camera.aerial": {
    en: "Switch to the overhead camera view.",
  },
  "knowledge.importFile": {
    en: "Import Markdown, PDF, or Word files. PDF and Word uploads are converted to Markdown for this library.",
  },
  "agent.uploadRag": {
    en: "Upload a Markdown, PDF or Word file as this Agent's RAG. It is Private or Public like the Agent.",
  },
  "agent.uploadMarkdown": {
    en: "Upload a Markdown file for the next Agent draft revision.",
  },
  "agent.uploadEvidence": {
    en: "Add Markdown, PDF, or Word files as Agent evidence. PDF and Word uploads are converted to Markdown.",
  },
  "voice.uploadSample": {
    en: "Upload a 10–20 second clip of yourself reading aloud (16-bit WAV, MP3, or M4A; max 10 MB).",
  },
} as const satisfies Record<string, { en: string }>;

export type UiGuideKey = keyof typeof uiGuideCopy;

export function uiGuideText(key: string): string | null {
  return Object.prototype.hasOwnProperty.call(uiGuideCopy, key)
    ? uiGuideCopy[key as UiGuideKey].en
    : null;
}
