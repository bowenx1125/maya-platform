import errorCopy from "./error-copy.json";

/**
 * All platform-owned copy lives in one typed dictionary. The UI is English
 * only (owner decision 2026-10-25); business data (names, files, prompts and
 * model output) never goes through it, and a Debate's output language is a
 * separate setting.
 */
const enMessages = {
  appName: "Mayaform",
  studyform: "Studyform",
  workspace: "Teaching workspace",
  loading: "Loading…",
  retry: "Retry",
  back: "Back",
  save: "Save",
  saved: "Saved",
  publish: "Publish",
  published: "Published",
  draft: "Draft",
  history: "History",
  archive: "Archive",
  knowledge: "Knowledge",
  brainform: "Brainform",
  rag: "RAG",
  knowledgeSets: "Knowledge Sets",
  openKnowledge: "Open Knowledge",
  knowledgeAssets: "assets",
  noKnowledgeSets: "No Knowledge yet.",
  knowledgeBindingsUpdated: "Knowledge selection updated.",
  generatedSetAgentMismatch:
    "This Knowledge Set is not linked to a generation receipt for this Agent. Return to the Set and use its Update AI Knowledge action.",
  aiKnowledgeFlowIntro:
    "Choose the source files for this Agent. Done will publish the Agent and start Knowledge generation from those selected sources.",
  aiKnowledgeSourcesRequired: "Choose at least one Source to continue.",
  aiKnowledgeSourcesRequiredHelp:
    "No Agent will be published and no generation request will be sent until a Source is selected.",
  generationReceiptMissing:
    "The Agent was published, but no Knowledge generation receipt was returned. Open its Knowledge Sets to check the current state.",
  setName: "Set name",
  selectCourse: "Course",
  chooseGroup: "Choose a group you joined",
  sources: "Sources",
  questions: "Questions",
  notes: "Notes",
  graph: "Graph",
  prompt: "Question prompt",
  body: "Content",
  points: "Points",
  setSaved: "Set details saved.",
  agentKnowledgeSets: "Knowledge Sets for this Agent",
  agents: "Agents",
  group: "Group",
  selectGroup: "Choose",
  teacher: "Teacher view",
  student: "Student view",
  logout: "Logout",
  signIn: "Sign in",
  username: "Username",
  password: "Password",
  createAgent: "New",
  name: "Name",
  description: "Description",
  agentVisibility: "Visibility",
  privateOption: "Private",
  publicOption: "Public",
  makeAgentPublic: "Make Agent public",
  makeAgentPrivate: "Make Agent private",
  privateVisibilityLede:
    "Private Agents and sources stay with their owner, though a course teacher who enters the group can read them. Public group Agents are available to group students and course teachers after publication; only Public sources are shared.",
  personalVisibilityLede:
    "A Public personal Agent is shareable, but course students do not get access automatically. They need a separate invocation grant to use it; its prompt and sources remain visible only to its owner.",
  deleteAgent: "Delete",
  deleteAgentConfirm:
    "Delete this Agent for teachers and students? Existing chats become read-only. Shared knowledge files stay.",
  deleteTeamConfirm: "Delete this Maya Team? Existing chats stay read-only.",
  deletePrivateTeamConfirm: "Delete this Team? Existing chats stay read-only.",
  deleteChat: "Delete chat",
  pinChat: "Pin chat",
  unpinChat: "Unpin chat",
  renameChat: "Chat name",
  deleteChatConfirm: "Delete this entire conversation? This cannot be undone.",
  delete: "Delete",
  readOnly: "Read-only published snapshot",
  retryConflict:
    "Someone else changed this content. Please refresh. Copy any unsaved text first.",
  refreshPage: "Refresh",
  signInContinue: "Sign in to continue.",
  sessionRequired:
    "Your session is required before Mayaform can reveal course or group content.",
  viewUnavailable: "That view is not available for this account.",
  roleBoundary: "Mayaform keeps student drafts and teacher snapshots separate.",
  returnWorkspace: "Back",
  demoIdentity: "Demo identity",
  or: "or",
  signingIn: "Signing in…",
  loginFailed: "Login failed. Check the username and password.",
  demoSwitchUnavailable: "Demo identity switching is unavailable.",
  home: "Home",
  groupWorkspace: "Workspace",
  course: "Course",
  publishedAgents: "Published Agents",
  debates: "Classroom",
  debateList: "Debates",
  newDebate: "New",
  newDebateTitle: "Debates",
  debateTopic: "Topic",
  debateTopicPlaceholder:
    "e.g. Should the United States ban TikTok's recommendation algorithm?",
  debateRoundCount: "Rounds",
  debatePhaseOpening: "Opening",
  debatePhaseExchange: "Exchange",
  debatePhaseFinalIntegration: "Final integration",
  debateStance: "Stance mode",
  debateAssigned: "Assigned stance",
  debateOpen: "Open explanation",
  debateSupport: "Support",
  debateOppose: "Oppose",
  debateNeutral: "Neutral",
  debateNote: "Teacher note (optional)",
  debateSelectCount: "{count} selected",
  debateBack: "Back",
  debateNoDebates: "No debates yet.",
  debateNoCandidates: "No Agents yet.",
  debateNoCourse:
    "No course you teach is selected, so Debates cannot be listed or created. Open one of your courses first.",
  debateCreateUnconfirmed:
    "The server did not confirm the new Debate. Refresh the Debate list to see whether it was created.",
  debateTopicRequired: "Enter a topic.",
  debateSelectAtLeast: "Select at least two Agents.",
  debateSelectAtMost: "A Demo debate supports at most five Agents.",
  debateCurrent: "current",
  debateRounds: "{count} Rounds",
  debateStageTitle: "Classroom debate",
  debateStageDescription: "A teacher-controlled, server-timed classroom stage.",
  debateStart: "Start",
  debateConnectionSignIn: "Sign in",
  debateConnectionReload: "Reload",
  debateRegenerate: "Regenerate",
  debatePreviewTitle: "Debates",
  debatePrewarmReady: "Ready",
  debateStalled: "Stalled",
  debateStalledReason: "Warming stopped at round {round}: {code}",
  debateReplayTurn: "Replay this speech",
  debateReplayAll: "Replay whole debate",
  debatePartial: "The debate stopped early. Published speeches remain below.",
  debateTranscript: "Public Debate",
  liveInteractionUnavailable:
    "Interaction is available only while the teacher has opened it and responses are being collected.",
  debateSources: "Sources",
  debateNoSources: "No matched knowledge sources.",
  debateRound: "Round",
  debatePrepared: "Preparing the next classroom turn…",
  debateComplete: "Finish",
  debateStopped: "Stopped",
  debateFailed: "Failed",
  debateWaitingForAudio: "Waiting for the server to prepare audio…",
  debateWaitingNext: "Waiting",
  debateConnectionReady: "Connected",
  debateConnectionReconnecting: "Reconnecting…",
  debateConnectionDisconnected: "unconnected",
  debateConnectionSequenceGap: "Classroom state needs to be resynchronized.",
  debateConnectionSessionExpired:
    "Your login has expired. Please sign in again.",
  debateConnectionOriginMismatch:
    "The classroom address does not match the server configuration.",
  debateConnectionSuperseded: "Another teacher page has taken control.",
  debateConnectionError: "The classroom connection needs attention.",
  wave3ConnectionNetwork: "unconnected",
  wave3Reconnect: "Reconnect",
  wave3Reconnecting: "Reconnecting…",
  wave3DownstreamUnavailable:
    "Partial or unfinished debates keep generated turns for audit, but classroom interaction, reports, history and replay are unavailable.",
  debateControllerWaiting: "",
  debateControlBusy: "Updating classroom playback…",
  debateRetryReason: "Playback did not start. You can retry this turn.",
  debateProviderSetupIncomplete:
    "A real provider is selected but its reviewed policy is not installed. Retrying cannot help; an operator has to import it.",
  debatePreviewNotReady:
    "Preview is not ready yet. Open Preview to check the saved speeches before trying again.",
  debatePreviewAudioFailed:
    "Audio failed for {count} turn(s) ({code}). Those turns will play as text only. Retry to try again.",
  debateCleanupDeferred:
    "A classroom operation is still running. Wait for it to finish, then try again.",
  debateRebirthRefreshFailed:
    "The classroom was reset, but the list could not be refreshed. Retry only reloads the list.",
  debateProviderGateTitle: "External query confirmation is required.",
  debateProviderGateLoading: "Loading the exact disclosure…",
  debateProviderGateEmpty: "No pending queries yet.",
  debateProviderGateReview: "Review exact disclosure",
  debateProviderGateReviewAll: "Review all turn approvals",
  debateProviderGateConfirmed: "Disclosure confirmed",
  debateProviderGateRetry: "Retry this turn",
  debateApprovalTitle: "Debate turn approvals",
  debateApprovalLoading: "Loading debate turn approvals…",
  debateApprovalError: "Debate turn approvals could not be loaded.",
  debateApprovalEmpty: "No disclosures yet.",
  debateApprovalTurn: "Turn",
  debateApprovalNeedsConfirmation: "Needs confirmation",
  debateApprovalConfirmed: "Confirmed",
  debateApprovalReview: "Review exact disclosure",
  debateNoPublishedSpeech:
    "The server has not published a speech for this turn yet.",
  debateSelectedTurn: "Selected turn",
  debateReplaceAudioConfirm:
    "Starting this debate will replace the previous retained audio. Its text remains available.",
  debateAudioLabel: "Classroom audio",
  debateMissingId: "The debate identifier is missing.",
  requestFailed: "Request failed",
  noticeDismiss: "Dismiss",
  noticeReopen: "Show the message",
  requestFallback: "The platform request could not be completed.",
  httpError: "Platform API returned HTTP {status}.",
  revisionConflict: "Revision conflict",
  statusActive: "active",
  statusInactive: "removed",
  statusArchived: "archived",
  statusDraft: "draft",
  statusPublished: "published",
  statusSuperseded: "superseded",
  statusReady: "ready",
  statusFailed: "failed",
  statusPending: "pending",
  statusIndexing: "indexing",
  statusMatched: "matched",
  statusNoMatch: "no match",
  statusNotStarted: "not started",
  statusGenerating: "generating",
  statusOpen: "open",
  statusClosed: "closed",
  statusFinalized: "finalized",
  statusRunning: "Running",
  statusCompleted: "Completed",
  statusStopped: "Stopped",
  statusDebateFinished: "Completed",
  statusPreparing: "preparing",
  statusPlaying: "playing",
  statusPaused: "paused",
  statusOutcomeUnknown: "outcome unknown",
  statusDeleted: "deleted",
  statusDeleting: "deleting",
  statusValidating: "validating",
  statusEnrolling: "enrolling",
  statusPreviewReady: "preview ready",
  statusPartial: "partial",
  statusInterrupted: "interrupted",
  studentHome: "Home",
  noGroup: "No groups yet.",
  noAgents: "No Agents yet.",
  members: "Members",
  newAgent: "New",
  agentIdentity: "Agent",
  agentName: "Name",
  agentNameRequired: "Enter an Agent name.",
  agentMdRequired: "Enter AGENT.md content before publishing.",
  optional: "optional",
  shortDescription: "Note",
  cancel: "Cancel",
  creating: "Creating…",
  groupNotFound: "This group no longer exists, or you are no longer in it.",
  courseNotFound: "This course no longer exists, or you are no longer in it.",
  agentNotFound: "This Agent was deleted or is no longer shared with you.",
  draftNotFound: "This draft was deleted or has already been published.",
  publishedVersionNotFound:
    "This published version was deleted or is no longer shared with you.",
  publishedAgentNotFound:
    "This published Agent was deleted or is no longer shared with you.",
  debateNotFound: "This Debate was deleted or is no longer available to you.",
  current: "current",
  revision: "revision",
  order: "order",
  snapshot: "Snapshot",
  content: "Content",
  working: "Working…",
  done: "Done",
  publishedNotice: "Published",
  createNextVersion: "New",
  noVersions: "No versions yet.",
  immutable: "Immutable",
  discardDraftConfirm: "Discard unsaved changes?",
  conflictDetail:
    "Someone else saved or published this Agent first. Refresh to load the latest version; your edits are kept in this browser and restored after refreshing.",
  localDraftRestoredNotice:
    "Your unpublished edits were restored on top of the latest version. Review them and click Done to publish.",
  agentMd: "AGENT.md",
  insertOutline: "Template",
  uploadMd: "Upload",
  uploadRag: "Upload RAG",
  characters: "characters",
  saving: "Saving…",
  uploadMarkdown: "Upload",
  knowledgeImportFormats:
    "Upload Markdown, PDF, or Word (.docx). PDF and Word imports are limited to 10 MiB per file; PDFs can have up to 200 pages, with local OCR on up to 50 scanned pages. Maya converts text to Markdown locally and keeps only the Markdown. OCR-extracted text is marked as “OCR-generated text”; images embedded in DOCX are not OCR-processed. Markdown content has no manually imposed total-length limit.",
  knowledgeImportPending:
    "Uploading, converting to Markdown (including local OCR for scanned PDF pages), and indexing…",
  knowledgeUploadPending: "Uploading and indexing the Markdown file…",
  knowledgeImportInvalid:
    "Use a readable PDF, Word (.docx), or UTF-8 Markdown. Scanned PDF pages use local OCR, and extracted text is marked as “OCR-generated text.” Images embedded in DOCX are not OCR-processed.",
  knowledgeMarkdownInvalid:
    "Use readable UTF-8 Markdown without invalid control characters.",
  knowledgeImportTooLarge:
    "This PDF/DOCX exceeds an import resource limit: 10 MiB per file, 200 pages per PDF, 50 scanned pages for OCR, or a PDF/DOCX parser safety limit. If the text is readable, extract it and import it as UTF-8 Markdown.",
  knowledgeImportNoText:
    "No readable text was found, even after local OCR. Check the file or provide a text-based copy.",
  knowledgeImportUnsupported:
    "This file type is not supported. Upload Markdown, PDF, or Word (.docx).",
  knowledgeImportProcessingFailed:
    "Maya could not safely process this document. Try a smaller or less complex file.",
  knowledgeImportOcrUnavailable:
    "Local OCR is temporarily unavailable. You can retry, or convert the PDF to Markdown and upload that.",
  knowledgeImportOcrFailed:
    "Local OCR could not read this scanned PDF. Retry, or upload a text-based PDF / Markdown instead.",
  knowledgeImportOcrTimeout:
    "Local OCR timed out on this scanned PDF. Retry, or upload a smaller scan / Markdown instead.",
  noGroupMarkdown: "No RAG yet.",
  testChat: "Test chat",
  noSources:
    "No source files returned. General reasoning is not presented as evidence.",
  publishChecklist: "Checklist",
  readyPublish: "Ready",
  blockAgentMdMissing: "Write an AGENT.md before publishing.",
  blockRagMissing: "Enable at least one ready Markdown file.",
  blockRagPending: "Wait for enabled files to finish indexing.",
  blockRagFailed: "Retry or remove failed enabled files.",
  blockAvatarMissing: "Choose an available 3D template before publishing.",
  ragPreview: "RAG",
  files: "files",
  preparingPreview: "Preparing preview…",
  previewAfterIndex: "No preview yet.",
  noPrompt: "No prompt yet.",
  enabledEvidence: "Enabled evidence",
  noEvidence: "No evidence yet.",
  releaseState: "Release state",
  knowledgeSnapshot: "Knowledge snapshot",
  loadingSnapshot: "Loading snapshot…",
  downloadRag: "Download",
  personalAgents: "My personal Agents",
  noPersonalAgents: "No Agents yet.",
  noPublishedAgents: "No Agents yet.",
  customVoiceReady: "Custom voice ready",
  archivedAgent: "Archived Agent",
  inspect: "Inspect →",
  download: "Download",
  edit: "Edit",
  reindex: "Reindex",
  hide: "Hide",
  knowledgeEditLede:
    "Editing creates a new immutable source and updates current drafts that reference the old source.",
  knowledgeFilename: "Filename",
  knowledgeContent: "Content",
  knowledgeHidden: "The source is hidden from the active Brainform library.",
  brainformUnavailable: "Brainform is not available for this course.",
  brainformRagIntro: "Markdown sources used for retrieval.",
  brainformKnowledgeHeading: "Knowledge",
  brainformKnowledgeIntro: "Current canonical Markdown for each Agent.",
  brainformGraphAccessibleLabel: "Knowledge relationship graph",
  brainformMemoryIntro:
    "Open a personal Chat context and ask what it remembers.",
  brainformRagEmpty: "No RAG yet.",
  brainformRagHideConfirm:
    "Delete {filename}? Debates already created keep their own copy.",
  deleteAffectsAgents:
    "This will affect these Agents: {names}. Each gets a new version without it and stays usable.",
  brainformRagFileStaged:
    "{filename} is selected. It will be imported when you save.",
  brainformAgentsUsingKnowledge: "Agents using this Knowledge",
  brainformKnowledgeFirstVersionEmpty:
    "No Knowledge version is published yet. This is an empty Markdown draft.",
  brainformNoKnowledgeUsers: "No Agents yet.",
  brainformNotMarkdownEditor:
    "This source is an imported file. Replace it with Markdown text or choose another file.",
  brainformKnowledgeEmpty: "No Knowledge yet.",
  brainformMemoryEmpty: "No Memory yet.",
  brainformMemoryOpen: "Open Memory in Chatform",
  brainformMemoryOpenNamed: "Open {name} memory in Chatform",
  brainformMemoryRetry: "Continue this Memory query",
  brainformMemoryAgent: "Agent",
  brainformMemoryTeam: "Team",
  brainformMemoryMayaTeam: "Maya Team",
  brainformMemoryInvalid:
    "This Memory link is incomplete or no longer matches the selected course.",
  brainformMemoryLoading:
    "Opening your own Chat and checking its current Memory context…",
  assessmentControlFailed:
    "The assessment state could not be changed. Refresh Chat status before trying again.",
  knowledgeCheckClose: "Close",
  brainformViewRag: "View Markdown source",
  brainformViewRagNamed: "View {name}",
  brainformEditRagNamed: "Edit {name}",
  brainformRagName: "RAG file name",
  brainformEditKnowledgeNamed: "Edit Knowledge {name}",
  brainformViewKnowledgeNamed: "View Knowledge {name}",
  brainformDownloadRagNamed: "Download {name}",
  brainformHideRagNamed: "Hide {name}",
  brainformDeleteKnowledgeNamed: "Delete {name}",
  brainformDeleteKnowledgeConfirm:
    "Delete the Knowledge {name}? Agents and Teams that use it stop seeing it.",
  brainformKnowledgeDeleted: "Knowledge deleted.",
  brainformNewKnowledge: "New Knowledge",
  brainformNewRag: "New RAG",
  brainformUploadKnowledgeFile: "Upload a Markdown file as Knowledge",
  brainformReindexRagNamed: "Reindex {name}",
  brainformViewKnowledge: "View Knowledge",
  brainformOpenKnowledgeNamed: "Open {name}",
  brainformGeneratingNamed: "Generating {name}",
  brainformRenameSetNamed: "Rename {name}",
  brainformSetName: "Knowledge title",
  brainformSetNameUnavailable: "The Knowledge title could not be updated.",
  brainformRegenerate: "Regenerate and replace Knowledge",
  brainformRegenerateNamed: "Regenerate {name}",
  brainformGenerating: "Generating AI Knowledge",
  brainformGenerationFailed: "Generation did not complete.",
  brainformGenerationFailedReason: "Generation did not complete: {reason}.",
  brainformNoKnowledgeDocument: "No Knowledge yet.",
  brainformProjectionUnavailable:
    "This Knowledge projection is not available to this account.",
  brainformRagIndexing: "Markdown indexing is still running.",
  brainformRagIndexFailed: "Markdown indexing failed. The source is retained.",
  brainformRagIndexFailedReason:
    "Markdown indexing failed ({reason}). The source is retained.",
  brainformDownloadKnowledgeNamed: "Download {name}",
  brainformMarkdownRequired:
    "Choose a .md, .pdf, or .docx file, or enter non-empty Markdown.",
  brainformChooseGroup: "Choose a Group",
  brainformRagSaved: "Markdown source saved.",
  brainformRagUpdatingAgents: "Saved. Updating the Agents that use it…",
  brainformRagAgentsUpdated: "Updated {names} and their Teams.",
  brainformRagAgentsNotUpdated:
    "Could not update {names}; open it and press Done.",
  brainformRetrySameSave:
    "The save result is unknown. Retry to check the same save.",
  brainformRagConflictDraftKept:
    "The source changed elsewhere. Your draft is kept; reload before saving again.",
  brainformKnowledgeSaved: "Knowledge published as a new version.",
  brainformKnowledgeConflictDraftKept:
    "Knowledge changed elsewhere. Your draft is kept; reload before saving again.",
  brainformRetrySameGeneration:
    "The generation result is unknown. Retry to check the same action.",
  brainformRagRenameNote:
    "Changing only the filename updates source metadata without reindexing.",
  brainformRagRenamed: "Markdown filename updated.",
  knowledgeFilenamePlaceholder: "evidence.md",
  active: "active",
  hidden: "hidden",
  homeWelcomeTitle: "Welcome {name}",
  tourWelcomeTitle: "Welcome to Mayaform",
  tourWelcomeBody:
    "A one-minute walk round the academy, so you know where everything is. Skip it whenever you like.",
  tourStudyformTitle: "Studyform",
  tourStudyformBody:
    "Build your Agents here: who they are and how they speak. Teams and voices live here too.",
  tourBrainformTitle: "Brainform",
  tourBrainformBody:
    "Add the readings your Agents should know. They draw on them when they answer.",
  tourChatformTitle: "Chatform",
  tourChatformBody:
    "Talk with an Agent or a Team, on your own or with your group.",
  tourLiveTitle: "Live",
  tourLiveBody:
    "When your teacher starts a class debate, this lights up and takes you there.",
  tourNewTitle: "The New button",
  tourNewBody:
    "Each page keeps its New button up here, next to the page title.",
  tourNewEmptyTitle: "New",
  tourNewEmptyBody: "Press New to make your first Agent.",
  tourGuideTitle: "Your next steps",
  tourGuideBody:
    "Work down this list. The step in dark ink is the one to do next.",
  tourGroupTitle: "Your group",
  tourGroupBody: "Your classmates, and your group's leader.",
  tourProfileTitle: "Profile",
  tourProfileBody: "Pick your scholar, and change your name or password.",
  tourNext: "Next",
  tourBack: "Back",
  tourSkip: "Skip",
  tourFinish: "Start",
  tourProgress: "{step} of {total}",
  guide: "Guide",
  guideDone: "Done",
  guideNext: "Next",
  guideOptional: "Optional",
  studentGuideGroup: "Meet your group",
  studentGuideAgent: "Build an Agent",
  studentGuideKnowledge: "Add references",
  studentGuideVoice: "Create a voice",
  teacherGuideCourse: "Open your course",
  teacherGuideGroups: "Create groups",
  teacherGuideAgents: "Publish an Agent",
  teacherGuideDebate: "Open a debate",
  profile: "Profile",
  userAvatar: "Avatar",
  changePassword: "Password",
  currentPassword: "Current password",
  newPassword: "New password",
  draftSavedNotice: "Draft saved. Revision advanced safely.",
  agentMdUploadedNotice:
    "AGENT.md uploaded and saved as the next draft revision.",
  evidenceUpdatedNotice: "Enabled evidence set updated.",
  markdownUploadedNotice: "Markdown uploaded and enabled for this draft.",
  knowledgeEvidenceImported:
    "File converted to Markdown and enabled for this draft.",
  knowledgePreviewRefreshFailed:
    "The file was uploaded successfully, but the evidence preview could not be refreshed.",
  knowledgePreviewRefreshing: "Refreshing the Markdown preview…",
  knowledgeImportFile: "Import a file",
  knowledgeImportAction: "Import",
  knowledgeImportLink: "Courseware",
  editor: "editor",
  navigation: "navigation",
  runtimeEnvironment: "Maya · Environment",
  runtimeHealth: "Runtime health",
  runtimeHealthLede: "A small, honest view of the local platform boundary.",
  checkingApiBoundary: "Checking the same-origin API boundary…",
  backToHome: "Back to home",
  serviceStatus: "Service status",
  gateway: "Gateway",
  frontend: "Frontend",
  backendApi: "Backend API",
  gatewayDetail: "Single origin is configured on port 8080.",
  frontendDetail: "Next.js shell is serving this page.",
  backendReachable: "Platform API is reachable.",
  backendUnreachable: "The platform API could not be reached.",
  nonSecretBuildContext: "Non-secret build context",
  environment: "Environment",
  checkAgain: "Check again",
  runtimeMode: "Runtime mode",
  buildMarker: "Build marker",
  browserApiBoundary: "Browser API boundary",
  sameOriginApi: "/api/v1 · same origin",
  readinessRule: "Readiness rule",
  readinessRuleDetail: "HTTP 200, 2xx, 401, or 403 from the platform API",
  ready: "Ready",
  checking: "Checking",
  unavailable: "Unavailable",
  errorUnauthenticated: "Please sign in before continuing.",
  errorForbidden: "This account is not allowed to perform that action.",
  errorNotFound: "This item was deleted or is no longer available to you.",
  errorNetwork:
    "Maya could not be reached. Check your connection and try again.",
  errorAgentVisibilityLocked:
    "Private or Public is chosen when the Agent is created and does not change.",
  errorRagFollowsAgent:
    "RAG added to an Agent is Private or Public like the Agent.",
  errorTeamMemberSourceUnavailable:
    "This Agent's RAG was removed from the library. Open the Agent, choose active RAG, and publish again before adding it to a Team.",
  errorCsrfFailed: "This form has expired. Please try again.",
  errorInvalidState: "That action is not available in the current state.",
  errorVersionImmutable: "Published versions are immutable.",
  errorStaleRevision: "Someone else changed this content. Please refresh.",
  agentLastEditedTooltip: "Last edited by: {name}",
  agentLastEditedBy: "Last edited by: {name}",
  errorStaleControlVersion:
    "The classroom state changed. Refresh and try again.",
  errorIdempotencyConflict:
    "This request was already used with different data.",
  errorDemoRoundCountFixed: "The demo uses exactly two rounds.",
  errorParticipantCountInvalid: "Choose between two and five participants.",
  errorParticipantDuplicate: "Each participant can be selected only once.",
  errorAgentNotCurrent: "Only the current published Agent can be selected.",
  errorAgentNameConflict:
    'This name is already in use. Please choose another name, for example add your name or a number (such as "Zhu Xi 2").',
  errorAgentArchived:
    "Archived Agents are not available for new classroom work.",
  errorCrossGroupReference: "That resource belongs to another group.",
  errorVoiceFallback:
    "The custom voice is unavailable; the platform fallback is being used.",
  errorAudioInvalid:
    "The audio file could not be used. Upload a 10–20 second WAV, MP3 or M4A recording, then choose the file again.",
  errorVoiceEnrollmentFailed: "Voice creation could not be completed.",
  errorDebateAlreadyRunning:
    "Another debate is already running for this course.",
  errorPreviousAudioCleanup:
    "Confirm cleanup of the previous debate audio before starting.",
  errorTurnGenerationFailed: "This debate could not finish generating a turn.",
  errorInteractionNotReady: "Classroom interaction is not ready yet.",
  errorInteractionClosed: "Classroom interaction has ended.",
  errorParticipantNotInDebate: "That participant is not part of this debate.",
  errorTopicLanguageInvalid: "Enter a non-empty topic.",
  errorAudioNotRetained: "This audio is no longer retained.",
  errorBarrageInsightFailed: "Classroom insight could not be prepared.",
  errorReportFailed: "The Maya report could not be generated.",
  errorTranslationNotConfigured:
    "The test translation service is not configured.",
  errorProviderUnavailable: "A platform capability is temporarily unavailable.",
  errorRagIndexFailed:
    "This file could not be indexed, so it was not saved. Upload it again in a minute.",
  debateAgentsNotReady: "Fix these Agents before the Debate can be created:",
  agentIssuesTitle: "This Agent is not ready for a Debate:",
  agentIssueArchived: "Agent “{name}” was deleted or archived.",
  agentIssueNotPublished:
    "Agent “{name}” has no published version. Open it and press Done to publish it.",
  agentIssueRagMissing: "Agent “{name}” needs at least one RAG file.",
  agentIssueAgentMdInvalid:
    "Agent “{name}” has a non-standard AGENT.md: it needs a heading line starting with # and some text under it.",
  agentIssueAvatarMissing: "Agent “{name}” has no usable Avatar.",
  agentIssueVoiceMissing:
    "Agent “{name}” has no Voice (Voice is None). The Debate will use the platform voice or show text only.",
  agentIssueEdit: "Edit Agent “{name}”",
  agentIssueNotCurrent:
    "Agent “{name}” changed while the Debate was being created. Check it, then create again.",
  agentIssueNotFound: "Agent “{name}” is no longer available in this course.",
  agentIssueCheck: "Done: save, publish and check this again",
  debateFixBeforeCreate: "Fix these before creating the Debate:",
  debateAgentsHints: "About the selected Agents:",
  debateFieldTopicBlank: "Enter a topic.",
  debateFieldTooFewAgents: "Choose at least 2 Agents.",
  debateFieldTooManyAgents: "Choose at most 5 Agents.",
  debateFieldDuplicateAgent: "The same Agent is selected twice.",
  debateFieldStanceMissing:
    "Agent “{name}” is set to an assigned stance, but no stance is chosen. Choose support, oppose or neutral.",
  debateFieldStanceUnexpected:
    "Agent “{name}” has an open stance, so it cannot also have an assigned one.",
  debateFieldAgent:
    "Agent “{name}” could not be read from the form. Select it again.",
  debateFieldBackground:
    "The Background text could not be read. Edit it and try again.",
  debateFieldTeachingPrompts:
    "The teaching rules could not be read. Open them, save, and try again.",
  debateFieldOutputLanguage: "The output language must be Chinese or English.",
  debateFieldLlmParam:
    "Generation parameters: {field} is out of range. Correct it, then create again.",
  debateFieldEdit: "Edit this setting",
  debateShowMe: "Show me",
  debateParamsTitle: "Generation Parameters",
  debateParamsReset: "Restore defaults",
  debateParamsNeverSent: "Saved, never sent to the model",
  debateParamsOn: "On",
  debateParamsOff: "Off",
  debateParamsEmpty: "Empty = not sent",
  debateParamsOmit: "Do not send to the model",
  debateParamsVoice: "Voice",
  debateFieldOther: "The field “{field}” is not valid.",
  errorEditTeam: "Edit Team “{name}”",
  errorChatFailed:
    "This reply could not be generated. Send your message again.",
  errorAgentHistoryRetained:
    "This Agent is being published right now and cannot be deleted. Try again in a moment.",
  errorAgentInTeam:
    "This Agent is still in a Team. Remove it from the Team first.",
  errorDuplicateTeamAgent: "Agent “{name}” can appear only once in a Team.",
  errorTeamMemberPrivate:
    "Agent “{name}” is Private, and a Public Team can only contain Public Agents. Make it Public or remove it.",
  errorInvalidTeamName: "Give the Team a name.",
  errorTeamVisibilityLocked:
    "Private or Public is chosen when the Team is created and cannot be changed.",
  errorTeamMemberNotPublished:
    "Team members must use a published Agent version. Publish the Agent first.",
  errorPrivateSourceForPublicAgent:
    "This Agent uses a Private RAG file. Make that file Public before making the Agent Public.",
  errorPrivateSourceForPublicSet:
    "A Public Knowledge set can only use Public sources in its group.",
  errorStaleBaseVersion:
    "Someone else published a newer version of this Agent. Your edits are kept; reload to see their version.",
  errorChatBusy:
    "The last message is still being answered. Wait for it, or refresh the chat.",
  errorChatMessageEmpty: "Type a message first.",
  errorChatInterrupted: "This Team reply was stopped. Send the message again.",
  errorChatAttachmentsUnavailable: "This chat does not accept attachments.",
  errorNextNotReady:
    "The next speech is still being prepared. Next becomes available as soon as it is ready.",
  errorNoNextTurn: "This was the last speech.",
  errorActiveDebateExists:
    "Another Debate in this course is playing. Stop it first.",
  errorOutputLanguageLocked:
    "The Debate language was set in Preview and cannot be changed now.",
  errorFinalInputRequired: "Press Final to prepare the last round.",
  errorFinalInputNotReady: "Finish the prepared rounds before pressing Final.",
  errorKnowledgeSourcesMissing:
    "This Agent has no RAG file to generate Knowledge from. Add a RAG file first.",
  errorInvalidKnowledgeName: "Give the Knowledge a name.",
  errorDuplicateKnowledgeBinding: "This Knowledge is already linked.",
  errorDuplicateKnowledgeSource: "This source is already selected.",
  errorPersonalSetOwnerOnly:
    "Only the owner can use this personal Knowledge until it is shared.",
  errorRegistrationUnavailable:
    "No course is open for registration yet. Ask your teacher.",
  errorGroupNotFound: "Choose one of this course's groups.",
  errorGroupChangeForbidden: "Only students choose their own group.",
  errorAccountReadOnly:
    "This account is managed by the platform and cannot be edited here.",
  errorIdempotencyInProgress:
    "The same request is still running. Wait for it to finish.",
  errorAssessmentRulesetIncomplete:
    "Formal assessment needs a complete “# Team Ruleset” section that names the roster. Fix the Team Ruleset first.",
  errorBarrageTooLong: "Use at most 300 characters.",
  errorBarrageBlank: "Nickname and message cannot be blank.",
  errorBarrageCollectionClosed: "Barrage collection has ended.",
  errorTeachingProtocolInvalid: "A Debate has exactly four rounds.",
  errorCleanupBusy: "Debate cleanup is busy. Try again in a moment.",
  errorAgentInTeamNamed:
    "This Agent is still in Team {teams}. Remove it from that Team first.",
  errorAgentInTeamOthers:
    "This Agent is also in {count} Team(s) owned by other people; their owners must remove it.",
  errorRequestFallbackCode:
    "The request could not be completed (error code {code}).",
  errorInternal: "Something went wrong on the server. Please try again.",
  errorHostMemoryPressure:
    "The server is busy right now. Your message was kept; please try again shortly.",
  errorServerBusy:
    "Too many people are using Maya right now. Your message was kept; please try again shortly.",
  chatSendBusyRetry:
    "Many people are using Maya right now. Press Send again in a moment.",
  chatSendPreviousRunning:
    "The previous message is still being answered. Send again in a moment.",
  chatSendScoringBusy: "Scoring in progress, please try again shortly",
  chatScoringNotice: "Scoring…",
  errorVoiceProviderUnavailable:
    "Voice provider is temporarily unavailable. Use the platform fallback voice; this is not a successful custom voice.",
  errorVoiceCloneRefused:
    "This voice path does not support cloning. The sample was not saved as a custom voice.",
  errorChatAcceptanceUnknown:
    "This request's outcome is unknown. Maya will not resend it automatically. The message remains in this conversation; you can continue with a new message.",
  errorChatTransportUncertain:
    "Maya couldn't confirm whether this request finished. It won't resend automatically. Check its status or retry this same request to recover.",
  errorChatHistoryRefreshFailed:
    "Maya couldn't refresh this saved conversation. Retry the refresh before sending here.",
  chatCheckStatus: "Check status",
  errorFileOperationFailed: "The file operation could not be completed.",
  errorMalformedRequest:
    "Please check the submitted information and try again.",
  errorRequestFallback: "The platform request could not be completed.",
  errorAuthRateLimited:
    "Too many sign-in or registration attempts. Try again in {seconds} seconds.",
  loginQueueWaiting: "Waiting to enter. {position} people are ahead of you.",
  loginQueueNext: "Waiting to enter. You are next.",
  loginQueueEta: "About {seconds} s left · {total} waiting",
  loginQueueProgressLabel: "Sign-in queue progress",
  loginQueueReconnecting:
    "Connection lost. Reconnecting — your place in line is kept.",
  loginQueueResume:
    "Your place in line is kept ({position} ahead). Enter your password again to continue.",
  wave3Title: "Interaction",
  interactionTitleClosed: "Classroom interaction",
  interactionTitleOpen: "Live classroom interaction",
  interactionTitleFinalized: "Interaction finalized",
  interactionOpening: "Opening…",
  interactionOpen: "Interaction",
  interactionScan: "Scan to join",
  interactionClosing: "Closing…",
  interactionClose: "Conclude",
  interactionLiveVote: "Live vote",
  interactionRawBarrages: "Raw barrages",
  interactionNoMessages: "No messages yet.",
  audienceLoading: "Loading classroom…",
  audienceUnavailable: "Collection unavailable",
  audienceUnavailableHint: "This classroom link is invalid or has ended.",
  audienceEyebrow: "Maya classroom · anonymous audience",
  audienceNickname: "Nickname",
  audienceNicknamePlaceholder: "Your display name",
  audienceVote: "Vote",
  audienceVoteSubmitted: "Submitted",
  audienceVoteSubmit: "Vote",
  audienceSubmitting: "Submitting…",
  audienceBarrage: "Barrage",
  audienceBarrageSubmitted: "Submitted",
  audienceBarragePlaceholder: "Share a thought or question",
  audienceBarrageSend: "Send",
  audienceSending: "Sending…",
  audienceRound: "Round",
  audienceCollectionClosed: "Collection closed",
  audienceReconnecting: "Connection interrupted. Reconnecting…",
  audienceBusyRetrying: "It's busy right now, retrying…",
  audienceTooFast: "Sending too fast. Wait {seconds} s and send again.",
  voices: "Voices",
  avatarDesign: "Avatar",
  voiceBinding: "Voice binding",
  manageVoices: "Voices",
  useFallbackVoice: "Use platform fallback voice",
  currentVoiceBinding: "Current voice",
  voiceNoneOption: "None",
  avatar: "Avatar",
  avatarPreview: "avatar preview",
  avatarPreviewUnavailable: "Avatar preview unavailable.",
  avatarStaticPreview: "static preview",
  avatarEditor: "Avatar editor",
  avatarTemplate: "Avatar template",
  avatarMaterialTheme: "Material theme",
  avatarEyeColor: "Eye color",
  avatarAssetDefault: "Asset default",
  avatarDefaultExpression: "Default expression",
  avatarExpressionStrength: "Expression strength",
  avatarHeadMotion: "Head motion",
  avatarPreviewState: "Preview state",
  avatarPreviewLoading: "Loading avatar preview…",
  avatarTemplateDefault: "Default",
  avatarTemplateWarmScholar: "Scholar",
  avatarTemplateCivicObserver: "Observer",
  avatarTemplateUnavailable: "Unavailable",
  avatarThemeDemo: "demo",
  avatarThemeWarmSand: "warm sand",
  avatarThemeCoolSlate: "cool slate",
  avatarThemeCivicOlive: "civic olive",
  avatarEyeDefault: "default",
  avatarEyeBrown: "brown",
  avatarEyeHazel: "hazel",
  avatarEyeBlue: "blue",
  avatarEyeGreen: "green",
  avatarEyeGray: "gray",
  avatarExpressionNeutral: "neutral",
  avatarExpressionAttentive: "attentive",
  avatarExpressionHappy: "happy",
  avatarExpressionSeriousAngry: "serious angry",
  avatarExpressionSad: "sad",
  avatarStrengthLow: "low",
  avatarStrengthMedium: "medium",
  avatarStrengthHigh: "high",
  avatarMotionCalm: "calm",
  avatarMotionActive: "active",
  avatarStateIdle: "idle",
  avatarStateListening: "listening",
  avatarStateSpeaking: "speaking",
  avatarStateThinking: "thinking",
  avatarStateNodYes: "Nod",
  voiceCreateTitle: "New",
  voiceNone: "No voices yet.",
  voiceSampleFile:
    "Upload a 10–20 second clip of yourself reading aloud (16-bit WAV, MP3, or M4A; max 10 MB).",
  voiceSelectFileFirst: "Select an audio file (.wav, .mp3 or .m4a) first.",
  voiceConsent:
    "I confirm this is my voice and authorize this course to create a reusable profile.",
  voiceProfileCreatedNotice: "Created",
  voiceCustom: "Custom voice",
  voiceName: "Voice name",
  voicePreview: "Preview",
  voicePreviewExpired:
    "This preview has expired. Play the voice again to listen.",
  voicePreviewFailed:
    "The preview could not be played. Play the voice again to listen.",
  voiceDeleteNamed: "Delete {name}",
  voiceDelete: "Delete",
  voiceDeleteConfirm:
    "Delete this custom voice? Debates already created keep their voice.",
  leader: "leader",
  admin: "admin",
  member: "member",
  accounts: "Accounts",
  groups: "Groups",
  enter: "Enter",
  leave: "Leave",
  rosterNoGroup: "No group",
  rosterEmpty: "No members yet.",
  rosterNoGroups: "No groups yet.",
  editMember: "Edit",
  displayNameLabel: "Display name",
  groupNameLabel: "Group",
  overviewMembers: "Members",
  recordIntro:
    "Formal assessment results, grouped by the Team that ran the assessment.",
  recordOpenNamed: "Open the Record for {name}",
  recordTeamMeta: "Students {students} · Attempts {attempts}",
  recordStudents: "Students",
  recordCompleted: "Completed",
  recordAverage: "Average score",
  recordReportFor: "Download the report for {name}",
  recordOwnIntro:
    "Your own formal assessment answers, grouped by the Team that ran the assessment.",
  recordOwnOpenNamed: "Open your answers for {name}",
  recordOwnMeta: "Attempts {attempts}",
  recordAttempts: "Attempts",
  recordRevokedVersion: "Revoked version",
  recordUnfinished: "Unfinished",
  recordDeleteNamed: "Delete {name}'s attempt",
  recordDeleteConfirm:
    "Permanently delete this attempt? Its answers and scores are removed for the student too, and it cannot be restored. The chat is not affected.",
  overviewActivity: "Recent activity",
  overviewNoMembers: "No students in this group yet.",
  overviewNoResults: "No Record yet.",
  overviewNoActivity: "Nothing yet.",
  overviewNoWork: "No Agents or Teams yet.",
  overviewWorkCounts:
    "Agents {agents} · Teams {teams} · RAG {rag} · Voices {voices}",
  overviewInProgress: "In progress",
  overviewSummaryNotSaved: "Summary not saved",
  overviewScoringNotSaved: "Scores not saved",
  overviewPaused: "Paused",
  overviewConversation: "Conversation",
  overviewNoScore: "Not scored",
  overviewReport: "Report",
  overviewQuestion: "Question",
  overviewAnswer: "Answer",
  overviewPoints: "Points",
  overviewFeedback: "Feedback",
  overviewSkipped: "(skipped)",
  overviewNotAnswered: "(not answered)",
  overviewAgentCreated: "created the Agent {title}",
  overviewAgentPublished: "published {title}",
  overviewTeamCreated: "created the Team {title}",
  overviewRagAdded: "added the RAG {title}",
  overviewVoiceAdded: "added the voice {title}",
  overviewTestCompleted: "finished the {title} test",
  groupMoveConfirm:
    "Move from {from} to {to}? Your Agents, Teams, RAG and voices stay in {from}, and you will no longer see them.",
  removeAccount: "Remove",
  reactivateAccount: "Restore",
  removeConfirm:
    "Remove this account? The student is signed out at once and cannot sign in. Their work is kept, and you can restore the account under Removed.",
  removedMembers: "Removed",
  resetPassword: "Reset",
  resetPasswordIssued: "New password for {username}",
  registerTitle: "Create an account",
  registerGroupLabel: "Group name",
  registerSuggestions: "Groups you can join",
  registerWillJoin: "You will join {name}, which has {count} member(s).",
  registerWillCreate: "No group is called that yet, so you will create it.",
  registerStepOf: "Step {current} of {total}",
  registerStepAccount: "Your sign-in",
  registerStepGroup: "Your group",
  registerNext: "Next",
  registerBack: "Back",
  registerSubmit: "Create account",
  registering: "Creating account…",
  registerFailed: "The account could not be created.",
  needAccount: "Need an account?",
  haveAccount: "Already have an account?",
  memberCountShort: "{count} member(s)",
  academyWelcome: "Welcome back",
  academyEyebrow: "CULTURAL EXCHANGE CLASSROOM",
  errorAccountNotFound: "No account uses that username yet.",
  errorUsernameTaken:
    "That username is already taken. Choose another username.",
  errorRegistrationBusy: "Registration is busy. Please try again.",
  errorPasswordIncorrect: "That password does not match this account.",
  errorAccountInactive: "This account has been deactivated by a teacher.",
  loginNeedUsername: "Enter your username.",
  loginNeedPassword: "Enter your password.",
  loginNeedBoth: "Enter your username and password.",
  needAccountLink: "Create an account",
  passwordRule: "At least 5 characters.",
  passwordTooShort: "That password is too short. Use at least 5 characters.",
  registerConfirmPassword: "Confirm password",
  registerPasswordMismatch: "The two passwords do not match.",
  academyMascotsLabel:
    "Four scholars of the academy, whose eyes follow the cursor and look away while a password is typed.",
  academyStageLabel: "The academy courtyard",
  chatHistory: "History",
  chatHistoryEmpty: "No chats yet.",
  chatPickOrNew: "Choose a chat from History, or press New to start one.",
  chatNewTitle: "New chat",
  chatMessagePlaceholder: "Message",
  chatAttach: "Attach a file",
  chatAttachHelp:
    "Attach a chat log to this chat only. Only you can see it. .txt, .md, .json, .csv or .html, up to 2 MB.",
  chatAttachmentRemove: "Remove {name}",
  chatAttachmentUploading: "Attaching…",
  errorChatAttachmentType: "Attach a .txt, .md, .json, .csv or .html file.",
  errorChatAttachmentTooLarge: "Attach a file of at most 2 MB.",
  errorChatAttachmentLimit:
    "This chat already has 5 attachments. Remove one first.",
  errorChatAttachmentTextTooLong:
    "These files together are too long for one chat. Attach a shorter export.",
  errorChatAttachmentEncoding:
    "Save the file as UTF-8 text and attach it again.",
  errorChatAttachmentInvalid:
    "This file cannot be read. Check that it is a valid text or JSON export.",
  chatTargetTeams: "Teams",
  mayaTeam: "Maya Team",
  mayaTeams: "Maya Teams",
  mayaTeamPublishHelp:
    "Choose Agents, a Leader and shared Knowledge, then press Done to publish. Students find it under New in Chatform.",
  mayaTeamPublished:
    "Maya Team published. Students can choose it from New in Chatform.",
  mayaTeamNoneYet: "No Maya Teams yet.",
  teamNoneYet: "No Teams yet.",
  studyformOpenMayaTeams: "Open Maya Team",
  chatCreateTeam: "Create Team",
  chatEditTeam: "Edit Team",
  teamName: "Name",
  teamIdentity: "Team",
  teamNameRequired: "Enter a Team name.",
  teamMembers: "Members",
  teamMembersHelp:
    "Choose at least two available Agents and set exactly one Leader.",
  teamSetLeader: "Set {name} as Leader",
  teamNeedsTwoMembers: "Choose at least two members.",
  teamChooseLeader: "Choose one Leader from the selected members.",
  teamSharedKnowledge: "Knowledge",
  teamSharedKnowledgeHelp:
    "Only selected Knowledge Sets will be shared with this Team.",
  teamNoSharedKnowledge: "No Knowledge yet.",
  teamSaveFailed: "The Team could not be saved. Review access and try again.",
  teamSaveUnknown:
    "The save result is uncertain. Retry the same Team change to check safely; the form is locked meanwhile.",
  teamLoadFailed: "Team information could not be loaded.",
  teamListRefreshFailed: "Team was saved, but the list could not be refreshed.",
  retryTeamList: "Refresh Team list",
  teamApiNotConnected:
    "Team services are not connected yet. No Chat was created.",
  teamNotEditable: "You no longer have permission to edit this Team.",
  teamSavedWaitingForChat: "Team saved. You can now start a Team Chat.",
  teamChatUnavailable:
    "Team Chat sending is unavailable in the current runtime.",
  teamChatMembersUnavailable:
    "This Team Chat can't continue: its members are no longer available to you. Start a new Chat with the Team.",
  teamRequestFailure: "The Team Chat request could not be completed.",
  teamMemberFailure: "This Team member could not reply.",
  teamSummaryNotSaved:
    "This Team member could not save the summary. Send a new message to try again.",
  teamReplyCutOff:
    "The reply was cut off before it finished, so nothing was saved. Please send your message again.",
  teamProviderConfirmationStudent:
    "A Team member could not reply because the current Team data-use authorization needs Teacher confirmation. Ask a Teacher to review and confirm it, then explicitly send a new message.",
  teamProviderConfirmationTeacher:
    "A Team member could not reply because the current Team data-use authorization needs confirmation. Review and confirm it, then explicitly send a new message.",
  teamChatReadOnly: "This Public Team Chat is read-only.",
  chatAgentDeleted:
    "The publisher deleted this Agent. This chat can't continue; its history is kept.",
  chatAgentUnavailable:
    "This Agent is no longer available to you. This chat can't continue; its history is kept.",
  chatTeamDeleted:
    "The publisher deleted this Team. This chat can't continue; its history is kept.",
  chatTeamMemberDeleted:
    "{name} was deleted by its publisher. This Team chat can't continue; its history is kept.",
  teamAnswerNotRecorded:
    "Your answer was not recorded. Send it again to continue the assessment.",
  teamRecipients: "Recipients",
  teamAllMembers: "All",
  teamPartialResult:
    "Some members could not reply. Successful replies are kept.",
  teamCheckStatus: "Check Team Chat status",
  assessmentStageScoring: "Answers saved · scoring",
  assessmentStageSummarizing: "Scored · writing the summary",
  assessmentStageCompleted: "Scoring finished · the test is complete",
  assessmentProgress: "Test progress",
  knowledgeGenerationProgress: "Knowledge generation progress",
  knowledgeGenerationQueued: "Knowledge generation queued",
  knowledgeGenerationRunning: "Generating Knowledge",
  knowledgeGenerationMaterializing: "Saving Knowledge",
  knowledgeGenerationCompleted: "Knowledge generation complete",
  knowledgeGenerationFailed: "Knowledge generation failed",
  teamResume: "Resume",
  teamTurnPending:
    "This Team turn is still running. Check its status to resume updates.",
} as const;

export type MessageKey = keyof typeof enMessages;

export type MessageValues = Record<string, string | number>;
export type Translator = {
  (key: MessageKey): string;
  (key: MessageKey, values: MessageValues): string;
};

const avatarTemplateKeys: Record<string, MessageKey> = {
  "wave1-default-head": "avatarTemplateDefault",
  "maya-warm-scholar": "avatarTemplateWarmScholar",
  "maya-civic-observer": "avatarTemplateCivicObserver",
  "unavailable-template": "avatarTemplateUnavailable",
};

const avatarOptionKeys: Record<string, MessageKey> = {
  demo: "avatarThemeDemo",
  warm_sand: "avatarThemeWarmSand",
  cool_slate: "avatarThemeCoolSlate",
  civic_olive: "avatarThemeCivicOlive",
  default: "avatarEyeDefault",
  brown: "avatarEyeBrown",
  hazel: "avatarEyeHazel",
  blue: "avatarEyeBlue",
  green: "avatarEyeGreen",
  gray: "avatarEyeGray",
  neutral: "avatarExpressionNeutral",
  attentive: "avatarExpressionAttentive",
  happy: "avatarExpressionHappy",
  serious_angry: "avatarExpressionSeriousAngry",
  sad: "avatarExpressionSad",
  low: "avatarStrengthLow",
  medium: "avatarStrengthMedium",
  high: "avatarStrengthHigh",
  calm: "avatarMotionCalm",
  active: "avatarMotionActive",
  idle: "avatarStateIdle",
  listening: "avatarStateListening",
  speaking: "avatarStateSpeaking",
  thinking: "avatarStateThinking",
  nod_yes: "avatarStateNodYes",
};

export function avatarTemplateLabel(
  templateId: string,
  fallbackName: string,
): string {
  const key = avatarTemplateKeys[templateId];
  return key ? t(key) : fallbackName;
}

export function avatarOptionLabel(value: string): string {
  const key = avatarOptionKeys[value];
  return key ? t(key) : value.replaceAll("_", " ");
}

export function t(key: MessageKey): string {
  return enMessages[key];
}

export function tm(key: MessageKey, values: MessageValues): string {
  return t(key).replace(/\{(\w+)\}/g, (_, name: string) =>
    String(values[name] ?? `{${name}}`),
  );
}

const translator = ((key: MessageKey, values?: MessageValues) =>
  values ? tm(key, values) : t(key)) as Translator;

/** The translator for components (kept as a hook-shaped call site). */
export function useT(): Translator {
  return translator;
}

const errorCodeKeys: Record<string, MessageKey> = {
  knowledge_import_invalid: "knowledgeImportInvalid",
  knowledge_import_too_large: "knowledgeImportTooLarge",
  knowledge_import_no_text: "knowledgeImportNoText",
  knowledge_import_unsupported: "knowledgeImportUnsupported",
  knowledge_import_processing_failed: "knowledgeImportProcessingFailed",
  knowledge_import_ocr_unavailable: "knowledgeImportOcrUnavailable",
  knowledge_import_ocr_failed: "knowledgeImportOcrFailed",
  knowledge_import_ocr_timeout: "knowledgeImportOcrTimeout",
  unauthenticated: "errorUnauthenticated",
  account_not_found: "errorAccountNotFound",
  username_taken: "errorUsernameTaken",
  registration_busy: "errorRegistrationBusy",
  password_incorrect: "errorPasswordIncorrect",
  account_inactive: "errorAccountInactive",
  forbidden: "errorForbidden",
  not_found: "errorNotFound",
  agent_deleted: "chatAgentDeleted",
  agent_unavailable: "chatAgentUnavailable",
  csrf_failed: "errorCsrfFailed",
  invalid_state: "errorInvalidState",
  provider_preflight_blocked: "debateProviderSetupIncomplete",
  preview_not_ready: "debatePreviewNotReady",
  cleanup_deferred: "debateCleanupDeferred",
  rebirth_refresh_failed: "debateRebirthRefreshFailed",
  version_immutable: "errorVersionImmutable",
  stale_revision: "errorStaleRevision",
  stale_metadata_revision: "errorStaleRevision",
  stale_control_version: "errorStaleControlVersion",
  idempotency_conflict: "errorIdempotencyConflict",
  demo_round_count_fixed: "errorDemoRoundCountFixed",
  participant_count_invalid: "errorParticipantCountInvalid",
  participant_duplicate: "errorParticipantDuplicate",
  agent_not_current: "errorAgentNotCurrent",
  agent_name_conflict: "errorAgentNameConflict",
  agent_archived: "errorAgentArchived",
  agent_visibility_locked: "errorAgentVisibilityLocked",
  document_visibility_follows_agent: "errorRagFollowsAgent",
  team_member_source_unavailable: "errorTeamMemberSourceUnavailable",
  cross_group_reference: "errorCrossGroupReference",
  agent_md_missing: "blockAgentMdMissing",
  rag_missing: "blockRagMissing",
  rag_index_pending: "blockRagPending",
  rag_index_failed: "blockRagFailed",
  avatar_missing: "blockAvatarMissing",
  voice_unavailable_fallback_used: "errorVoiceFallback",
  audio_invalid: "errorAudioInvalid",
  voice_enrollment_failed: "errorVoiceEnrollmentFailed",
  voice_clone_refused: "errorVoiceCloneRefused",
  debate_already_running: "errorDebateAlreadyRunning",
  previous_audio_cleanup_confirmation_required: "errorPreviousAudioCleanup",
  turn_generation_failed: "errorTurnGenerationFailed",
  interaction_not_ready: "errorInteractionNotReady",
  interaction_closed: "errorInteractionClosed",
  participant_not_in_debate: "errorParticipantNotInDebate",
  topic_language_invalid: "errorTopicLanguageInvalid",
  audio_not_retained: "errorAudioNotRetained",
  barrage_insight_failed: "errorBarrageInsightFailed",
  report_failed: "errorReportFailed",
  translation_not_configured: "errorTranslationNotConfigured",
  provider_unavailable: "errorProviderUnavailable",
  rag_upload_index_failed: "errorRagIndexFailed",
  debate_agents_not_ready: "debateAgentsNotReady",
  chat_failed: "errorChatFailed",
  agent_history_retained: "errorAgentHistoryRetained",
  agent_in_team: "errorAgentInTeam",
  duplicate_team_agent: "errorDuplicateTeamAgent",
  team_member_private: "errorTeamMemberPrivate",
  invalid_team_name: "errorInvalidTeamName",
  team_visibility_locked: "errorTeamVisibilityLocked",
  team_member_version_not_immutable: "errorTeamMemberNotPublished",
  private_source_for_public_agent: "errorPrivateSourceForPublicAgent",
  private_source_for_public_set: "errorPrivateSourceForPublicSet",
  stale_base_version: "errorStaleBaseVersion",
  chat_busy: "errorChatBusy",
  chat_message_empty: "errorChatMessageEmpty",
  chat_interrupted: "errorChatInterrupted",
  chat_attachments_unavailable: "errorChatAttachmentsUnavailable",
  next_not_ready: "errorNextNotReady",
  no_next_turn: "errorNoNextTurn",
  active_debate_exists: "errorActiveDebateExists",
  output_language_locked: "errorOutputLanguageLocked",
  final_input_required: "errorFinalInputRequired",
  final_input_not_ready: "errorFinalInputNotReady",
  knowledge_generation_sources_missing: "errorKnowledgeSourcesMissing",
  invalid_knowledge_set_name: "errorInvalidKnowledgeName",
  duplicate_knowledge_set_binding: "errorDuplicateKnowledgeBinding",
  duplicate_knowledge_set_source: "errorDuplicateKnowledgeSource",
  personal_set_owner_only: "errorPersonalSetOwnerOnly",
  registration_unavailable: "errorRegistrationUnavailable",
  group_not_found: "errorGroupNotFound",
  group_change_forbidden: "errorGroupChangeForbidden",
  account_read_only: "errorAccountReadOnly",
  idempotency_in_progress: "errorIdempotencyInProgress",
  assessment_ruleset_incomplete: "errorAssessmentRulesetIncomplete",
  barrage_too_long: "errorBarrageTooLong",
  barrage_blank: "errorBarrageBlank",
  barrage_collection_closed: "errorBarrageCollectionClosed",
  teaching_protocol_invalid: "errorTeachingProtocolInvalid",
  cleanup_busy: "errorCleanupBusy",
  internal_error: "errorInternal",
  host_memory_pressure: "errorHostMemoryPressure",
  host_load_pressure: "errorServerBusy",
  llm_admission_busy: "errorServerBusy",
  create_admission_busy: "errorServerBusy",
  write_pressure: "errorServerBusy",
  adaptive_admission_busy: "errorServerBusy",
  auth_login_queued: "loginQueueNext",
  voice_provider_unavailable: "errorVoiceProviderUnavailable",
  chat_acceptance_unknown: "errorChatAcceptanceUnknown",
  memory_entry_invalid: "brainformMemoryInvalid",
  assessment_control_failed: "assessmentControlFailed",
  chat_transport_uncertain: "errorChatTransportUncertain",
  chat_history_refresh_failed: "errorChatHistoryRefreshFailed",
  file_operation_failed: "errorFileOperationFailed",
  chat_attachment_type_unsupported: "errorChatAttachmentType",
  chat_attachment_too_large: "errorChatAttachmentTooLarge",
  chat_attachment_limit: "errorChatAttachmentLimit",
  chat_attachment_text_too_long: "errorChatAttachmentTextTooLong",
  chat_attachment_encoding_unsupported: "errorChatAttachmentEncoding",
  chat_attachment_invalid: "errorChatAttachmentInvalid",
  chat_attachment_empty: "errorChatAttachmentInvalid",
  malformed_request: "errorMalformedRequest",
};

type ErrorCopyCatalog = {
  messages: Record<string, { en: string }>;
  codes: Record<string, string>;
};

/**
 * Copy for every other code the backend can send (PR D3): internal stage
 * and provider codes share a few family messages, codes a reader can act on
 * have their own. backend/tests/test_error_copy_contract.py keeps it complete.
 */
export function errorCopyFor(code: string): string | null {
  const catalog = errorCopy as ErrorCopyCatalog;
  const key = Object.hasOwn(catalog.codes, code) ? catalog.codes[code] : null;
  return key ? (catalog.messages[key]?.en ?? null) : null;
}

/**
 * Translate a stable platform error code at render time.  Unknown Error
 * messages are already-safe application fallbacks and remain visible for
 * diagnostics; supplier details never enter this function from the API DTO.
 */
export function localizeError(
  error: unknown,
  fallback: MessageKey = "errorRequestFallback",
): string {
  if (error && typeof error === "object") {
    const candidate = error as {
      code?: unknown;
      status?: unknown;
      details?: unknown;
    };
    if (
      (candidate.code === "knowledge_import_invalid" ||
        candidate.code === "file_operation_failed") &&
      candidate.details &&
      typeof candidate.details === "object" &&
      "reason" in candidate.details &&
      (candidate.details.reason === "invalid_utf8" ||
        candidate.details.reason === "empty_markdown" ||
        candidate.details.reason === "invalid_control_chars")
    ) {
      return t("knowledgeMarkdownInvalid");
    }
    if (
      candidate.code === "auth_login_queued" &&
      candidate.details &&
      typeof candidate.details === "object" &&
      "position" in candidate.details
    ) {
      const position = candidate.details.position;
      if (
        typeof position === "number" &&
        Number.isSafeInteger(position) &&
        position >= 0
      ) {
        return position === 0
          ? t("loginQueueNext")
          : tm("loginQueueWaiting", { position });
      }
      return t("loginQueueNext");
    }
    if (
      candidate.code === "auth_rate_limited" &&
      candidate.details &&
      typeof candidate.details === "object" &&
      "retry_after_seconds" in candidate.details
    ) {
      const seconds = candidate.details.retry_after_seconds;
      if (
        typeof seconds === "number" &&
        Number.isSafeInteger(seconds) &&
        seconds > 0
      ) {
        return tm("errorAuthRateLimited", { seconds });
      }
    }
    const details =
      candidate.details && typeof candidate.details === "object"
        ? (candidate.details as Record<string, unknown>)
        : {};
    if (candidate.code === "agent_in_team" && Array.isArray(details.teams)) {
      const names = details.teams
        .map((team) =>
          team && typeof team === "object"
            ? (team as { team_name?: unknown }).team_name
            : null,
        )
        .filter((name): name is string => typeof name === "string")
        .map((name) => `“${name}”`);
      const others =
        typeof details.other_team_count === "number"
          ? details.other_team_count
          : 0;
      const parts = [
        ...(names.length
          ? [tm("errorAgentInTeamNamed", { teams: names.join(" ") })]
          : []),
        ...(others > 0
          ? [tm("errorAgentInTeamOthers", { count: others })]
          : []),
      ];
      if (parts.length) return parts.join(" ");
    }
    if (typeof candidate.code === "string") {
      const key = errorCodeKeys[candidate.code];
      // A message that names its Agent gets the name the server sent.
      if (key && typeof details.agent_name === "string")
        return tm(key, { name: details.agent_name });
      if (key) return t(key);
      const copy = errorCopyFor(candidate.code);
      if (copy) return copy;
    }
    if (typeof candidate.status === "number") {
      if (candidate.status === 401) return t("errorUnauthenticated");
      if (candidate.status === 403) return t("errorForbidden");
      if (candidate.status === 404) return t("errorNotFound");
      // A plain 500 is a server bug (internal_error), not a provider outage.
      if (candidate.status === 500) return t("errorInternal");
      if (candidate.status > 500) return t("errorProviderUnavailable");
    }
  }
  // fetch rejects with a TypeError when the connection itself fails; its
  // browser wording ("Failed to fetch") names no next step.
  if (error instanceof TypeError) return t("errorNetwork");
  if (error instanceof Error && error.message) return error.message;
  // Never only "the request failed": keep the stable code for the reader.
  if (error && typeof error === "object") {
    const code = (error as { code?: unknown }).code;
    if (typeof code === "string" && /^[a-z_]+$/.test(code))
      return tm("errorRequestFallbackCode", { code });
  }
  return t(fallback);
}

const statusKeys: Record<string, MessageKey> = {
  active: "statusActive",
  inactive: "statusInactive",
  archived: "statusArchived",
  draft: "statusDraft",
  published: "statusPublished",
  superseded: "statusSuperseded",
  ready: "statusReady",
  failed: "statusFailed",
  pending: "statusPending",
  indexing: "statusIndexing",
  matched: "statusMatched",
  no_match: "statusNoMatch",
  not_started: "statusNotStarted",
  generating: "statusGenerating",
  open: "statusOpen",
  closed: "statusClosed",
  finalized: "statusFinalized",
  running: "statusRunning",
  completed: "statusCompleted",
  stopped: "statusStopped",
  debate_finished: "statusDebateFinished",
  preparing: "statusPreparing",
  playing: "statusPlaying",
  paused: "statusPaused",
  outcome_unknown: "statusOutcomeUnknown",
  deleted: "statusDeleted",
  deleting: "statusDeleting",
  validating: "statusValidating",
  enrolling: "statusEnrolling",
  preview_ready: "statusPreviewReady",
  partial: "statusPartial",
  interrupted: "statusInterrupted",
};

export function statusLabel(status: string): string {
  const key = statusKeys[status];
  return key ? t(key) : status.replaceAll("_", " ");
}

const blockerKeys: Record<string, MessageKey> = {
  agent_md_missing: "blockAgentMdMissing",
  rag_missing: "blockRagMissing",
  rag_index_pending: "blockRagPending",
  rag_index_failed: "blockRagFailed",
  avatar_missing: "blockAvatarMissing",
};

export function blockerLabel(blocker: string): string {
  const key = blockerKeys[blocker];
  return key ? t(key) : blocker.replaceAll("_", " ");
}

const roleKeys: Record<string, MessageKey> = {
  teacher: "teacher",
  student: "student",
  leader: "leader",
  admin: "admin",
  member: "member",
};

export function roleLabel(role: string): string {
  const key = roleKeys[role];
  return key ? t(key) : role;
}
