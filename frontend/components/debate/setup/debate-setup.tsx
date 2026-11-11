"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
} from "react";

import {
  createIdempotencyHandle,
  isAmbiguousMutationFailure,
  type IdempotencyHandle,
  type DebateDetail,
  type DebateDraftRequest,
  type DebateLLMDefaults,
  type DebateRulesetDefaults,
  type DebateSummary,
  type PlatformApi,
  type PublishedAgentSummary,
} from "../../../lib/api";
import { localizeError, type MessageKey } from "../../../lib/i18n";
import { RulesetEditor, type TeachingPrompts } from "./ruleset-editor";
import {
  LlmParamsCard,
  defaultParamValues,
  defaultVoiceValues,
  paramsPayload,
  voicePayload,
  type LLMParamValues,
  type VoiceParamValues,
} from "./llm-params-card";
import { CreateCard } from "./create-card";
import { validateDebateTopic } from "../../../lib/debate-topic";
import { useT } from "../../../lib/i18n";
import { useSession } from "../../session-provider";
import { ClassroomResetButton } from "../classroom-reset-button";
import { DebateCleanupControls } from "../debate-cleanup-controls";
import { DebateStatus } from "../debate-status";
import { IconBust, IconPlay, IconPlus, IconSpinner } from "../../quiet-icons";
import { Button } from "../../ui/button";
import { NewButton } from "../../ui/agent-card";
import { cn } from "../../../lib/utils";
import { LIST_CARD_LIFT } from "../../agent-chrome";
import {
  CREATE_SEG,
  CREATE_SEG_BUTTON,
  CREATE_TEXTAREA,
  DEBATE_PAGE,
  DEBATE_ROW_BUTTON,
  DEBATE_ROW_DANGER_BUTTON,
  DEBATE_TITLE,
  RIBBON_COLORS,
} from "../debate-chrome";
import { EndRunningDebatePrompt } from "../../debate-beta/stage/end-running-debate-prompt";
import { WorkspaceIcon } from "../../workspace-icon";

import { EmptyCard, ErrorNotice, LoadingCard } from "../../ui";
import {
  ChecklistBadge,
  CreateChecklist,
  checklistLineId,
  useCreateChecklist,
  type ChecklistItem,
} from "../../agent-issue-list";
import { AGENT_ISSUE_MESSAGES, issueKey } from "../../../lib/agent-readiness";
import {
  agentIssuesFromError,
  debateFieldProblems,
  mergeIssues,
  readinessIssues,
} from "../../../lib/agent-readiness";
import { PageAction, pageActionClass } from "../../page-action";
import { celebrate } from "../../../lib/confetti";

export type { DebateDetail, DebateDraftRequest, DebateSummary };

export type DebateListController = {
  load: (courseId: string) => Promise<DebateSummary[]>;
};

export type DebateCreateController = {
  loadRuleset: (courseId: string) => Promise<DebateRulesetDefaults>;
  loadCandidates: (courseId: string) => Promise<PublishedAgentSummary[]>;
  /** The env defaults and ranges the parameter card starts from. Without
   * it the card is not shown and the server freezes those defaults itself. */
  loadLLMDefaults?: (courseId: string) => Promise<DebateLLMDefaults>;
  create: (
    courseId: string,
    payload: DebateDraftRequest,
    idempotency: IdempotencyHandle,
  ) => Promise<DebateDetail>;
};

function copy(t: (key: MessageKey) => string, key: MessageKey): string {
  return t(key);
}

function teacherCourseId(
  user: ReturnType<typeof useSession>["user"],
): string | null {
  return (
    user?.courses.find((membership) => membership.role === "teacher")
      ?.course_id ?? null
  );
}

export function TeacherDebateList({
  controller,
}: {
  controller?: DebateListController;
}) {
  const t = useT();
  const { api, user } = useSession();
  const [debates, setDebates] = useState<DebateSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const courseId = teacherCourseId(user);
  const loadSequence = useRef(0);
  const [endingId, setEndingId] = useState<string | null>(null);
  const [endBusy, setEndBusy] = useState(false);
  const [endError, setEndError] = useState<unknown>(null);

  // Progress is worth watching closely only while something is moving: a
  // draft still warming its turns, or a running lesson. A list of finished or
  // stalled Debates used to ask the server every two seconds for as long as
  // the page stayed open. Set from each answer as it arrives, so the next
  // check is timed by what the server just said.
  const inMotion = useRef(true);
  const load = useCallback(
    async (silent = false, propagateError = false) => {
      const sequence = ++loadSequence.current;
      if (!courseId) {
        setError(new Error(t("debateNoCourse")));
        setLoading(false);
        return;
      }
      if (!silent) {
        setLoading(true);
        setError(null);
      }
      try {
        const next = controller
          ? await controller.load(courseId)
          : await api.debates(courseId);
        if (sequence !== loadSequence.current) return;
        inMotion.current = next.some(
          (row) =>
            !row.stall &&
            (row.status === "running" ||
              (row.status === "draft" && !row.preview?.ready)),
        );
        setDebates(next);
        setError(null);
      } catch (cause) {
        if (!silent && sequence === loadSequence.current) setError(cause);
        if (propagateError) throw cause;
      } finally {
        if (sequence === loadSequence.current) setLoading(false);
      }
    },
    [api, controller, courseId, t],
  );

  const refreshRows = useCallback(() => load(true), [load]);

  const ending = endingId
    ? debates.find((row) => row.id === endingId)
    : undefined;

  const finishListedDebate = useCallback(async () => {
    if (!ending || endBusy) return;
    if (
      typeof api.debate !== "function" ||
      typeof api.finishDebate !== "function"
    )
      return;
    setEndBusy(true);
    setEndError(null);
    try {
      const running = await api.debate(ending.id);
      await api.finishDebate(
        ending.id,
        {
          expected_control_version: running.playback.control_version,
          expected_current_turn_id: running.playback.current_turn_id,
        },
        { idempotency: createIdempotencyHandle() },
      );
      setEndingId(null);
      await load(true, true);
    } catch (cause) {
      setEndError(cause);
    } finally {
      setEndBusy(false);
    }
  }, [api, ending, endBusy, load]);

  useEffect(() => {
    let stopped = false;
    let timer: number;
    const poll = async (initial = false) => {
      if (initial || document.visibilityState !== "hidden")
        await load(!initial);
      if (!stopped)
        timer = window.setTimeout(
          () => void poll(),
          inMotion.current ? 2000 : 15000,
        );
    };
    const refreshVisible = () => {
      if (document.visibilityState !== "hidden") void load(true);
    };
    timer = window.setTimeout(() => void poll(true), 0);
    window.addEventListener("focus", refreshVisible);
    document.addEventListener("visibilitychange", refreshVisible);
    return () => {
      stopped = true;
      loadSequence.current += 1;
      window.clearTimeout(timer);
      window.removeEventListener("focus", refreshVisible);
      document.removeEventListener("visibilitychange", refreshVisible);
    };
  }, [load]);

  return (
    <div className={DEBATE_PAGE}>
      {/* The Debates title stays visible; New sits at the right of the
        title row (owner: New is top-right, not in the sidebar). */}
      <div className="mb-[22px] flex items-center gap-3">
        <h1 className={DEBATE_TITLE}>{t("debatePreviewTitle")}</h1>
        <span
          className="relative h-0 flex-1 border-t-[3px] border-dotted border-[#111] after:absolute after:top-[-9px] after:right-0 after:size-[14px] after:rounded-full after:border-[2.5px] after:border-[#111] after:bg-[#A3E635] after:content-['']"
          aria-hidden="true"
        />
        {courseId ? (
          <NewButton
            href="/teacher/debates/new"
            label={t("newDebate")}
            className={pageActionClass("new")}
          />
        ) : (
          <Button
            type="button"
            className={pageActionClass("new")}
            disabled
            aria-label={t("newDebate")}
          >
            <IconPlus size={16} />
            {t("newDebate")}
          </Button>
        )}
      </div>
      {loading ? <LoadingCard /> : null}
      {error ? <ErrorNotice error={error} onRetry={() => void load()} /> : null}
      {endError ? (
        <ErrorNotice
          error={endError}
          onRetry={() => void finishListedDebate()}
        />
      ) : null}
      {ending ? (
        <EndRunningDebatePrompt
          topic={ending.topic}
          zh={false}
          busy={endBusy}
          canEnd={
            typeof api.finishDebate === "function" &&
            typeof api.debate === "function"
          }
          onCancel={() => {
            if (!endBusy) {
              setEndingId(null);
              setEndError(null);
            }
          }}
          onEnd={() => void finishListedDebate()}
        />
      ) : null}
      {!loading && !error ? (
        debates.length === 0 ? (
          <DebateEmpty message={t("debateNoDebates")} />
        ) : (
          <div className="grid gap-3.5">
            {debates.map((debate, index) => (
              <div
                className={`relative grid grid-cols-[70px_1fr_150px] rounded-[18px] border-2 border-[#111] bg-white shadow-[0_4px_0_#111] [grid-template-areas:'v_b_s'_'v_a_a'] max-[600px]:grid-cols-[52px_1fr] max-[600px]:[grid-template-areas:'v_b'_'v_s'_'a_a'] ${LIST_CARD_LIFT}`}
                data-testid="debate-row"
                key={debate.id}
              >
                <span
                  className="grid items-start justify-items-center self-start [grid-area:v] before:-mt-1.5 before:h-16 before:w-[34px] before:border-2 before:border-t-0 before:border-[#111] before:bg-(--c) before:[clip-path:polygon(0_0,100%_0,100%_100%,50%_78%,0_100%)] before:content-['']"
                  style={
                    {
                      "--c": RIBBON_COLORS[index % RIBBON_COLORS.length],
                    } as CSSProperties
                  }
                  aria-hidden="true"
                />
                <Link
                  className="py-3.5 pr-4 text-inherit no-underline [grid-area:b]"
                  href={`/teacher/debates/${debate.id}/control`}
                >
                  <h2 className="m-0 font-display text-lg leading-[normal] font-bold tracking-normal">
                    {debate.topic}
                  </h2>
                  <div className="mt-2 flex gap-2 font-body text-xs leading-[normal] font-bold [&>span]:rounded-full [&>span]:border-2 [&>span]:border-[#111] [&>span]:bg-white [&>span]:px-2.5 [&>span]:py-px">
                    <span>
                      {t("debateRounds", { count: debate.round_count })}
                    </span>
                    <span>
                      {new Date(debate.created_at).toLocaleDateString()}
                    </span>
                  </div>
                </Link>
                {/* A draft is not idle: it is warming its turns in the
                  background, so the list says how far along it is rather
                  than only that it is a draft. A stall outranks both other
                  readings, and a running debate can stall too: the lesson
                  that stopped generating mid-round used to read Running
                  with nothing to act on. */}
                <div className="relative grid place-items-center border-0 border-l-[2.5px] border-dashed border-[#111] px-3 py-3.5 [grid-area:s] before:absolute before:top-[-11px] before:left-[-11px] before:size-[18px] before:rounded-full before:border-2 before:border-[#111] before:bg-[#DCEBFF] before:[clip-path:inset(50%_0_0_0)] before:content-[''] after:absolute after:bottom-[-11px] after:left-[-11px] after:size-[18px] after:rounded-full after:border-2 after:border-[#111] after:bg-[#DCEBFF] after:[clip-path:inset(0_0_50%_0)] after:content-[''] max-[600px]:justify-items-start max-[600px]:items-center max-[600px]:border-t-2 max-[600px]:border-l-0 max-[600px]:border-[#11111155] max-[600px]:px-0 max-[600px]:py-2 max-[600px]:before:hidden max-[600px]:after:hidden">
                  <DebateStatus debate={debate} pill />
                </div>
                <div className="mt-0.5 flex flex-wrap items-center gap-2 border-0 border-t-2 border-dashed border-[#11111155] pt-2.5 pr-4 pb-3 [grid-area:a] max-[600px]:px-3">
                  {["completed", "debate_finished"].includes(debate.status) ? (
                    <ClassroomResetButton
                      debateId={debate.id}
                      onDone={() => load(true, true)}
                    />
                  ) : null}
                  {/* The row itself opens Preview, so it has no button of
                    its own. */}
                  {!["failed", "stopped"].includes(debate.status) &&
                  (debate.preview?.ready ||
                    ["running", "completed", "debate_finished"].includes(
                      debate.status,
                    )) ? (
                    <Link
                      className={DEBATE_ROW_BUTTON}
                      href={`/teacher/debates-beta/${debate.id}/control`}
                      aria-label="Immerse"
                    >
                      <IconPlay size={18} />
                      <span>Immerse</span>
                    </Link>
                  ) : (
                    <Button
                      variant="noShadow"
                      className={DEBATE_ROW_BUTTON}
                      type="button"
                      aria-label="Immerse"
                      disabled
                    >
                      <IconPlay size={18} />
                      <span>Immerse</span>
                    </Button>
                  )}
                  <DebateCleanupControls
                    key={user?.id}
                    api={api}
                    debateId={debate.id}
                    loadDetail={() => api.debate(debate.id)}
                    onVoiceDeleted={refreshRows}
                    onAllDeleted={() => {
                      loadSequence.current += 1;
                      setDebates((rows) =>
                        rows.filter((row) => row.id !== debate.id),
                      );
                    }}
                    className="contents"
                    labelled
                    iconClassName={DEBATE_ROW_BUTTON}
                    dangerClassName="ml-auto text-[#B91C1C] max-[600px]:ml-0"
                    audioRestoreNeeded={debate.audio_restore_needed}
                    restoreOwnerId={user?.id}
                    afterVoice={
                      debate.status === "running" ? (
                        <Button
                          variant="noShadow"
                          className={DEBATE_ROW_DANGER_BUTTON}
                          type="button"
                          aria-label="End"
                          busy={endBusy && endingId === debate.id}
                          disabled={endBusy}
                          onClick={() => {
                            setEndError(null);
                            setEndingId(debate.id);
                          }}
                        >
                          {endBusy && endingId === debate.id ? (
                            <IconSpinner size={18} />
                          ) : (
                            <WorkspaceIcon name="stop" size={18} />
                          )}
                          <span>End</span>
                        </Button>
                      ) : null
                    }
                  />
                </div>
              </div>
            ))}
          </div>
        )
      ) : null}
    </div>
  );
}

/** Empty list: a bracket of blank slots waiting on a smiling trophy. The
 * New button stays in the title row, so the card holds none. */
function DebateEmpty({ message }: { message: string }) {
  const slot =
    "h-[42px] rounded-full border-[2.5px] border-dashed border-[#11111166] bg-[color-mix(in_srgb,var(--c)_25%,#fff)]";
  return (
    <div className="mx-auto mt-5 max-w-[620px] rounded-[28px] border-2 border-[#111] bg-white px-6 pt-[30px] pb-[30px] text-center shadow-[0_5px_0_#111]">
      <div
        className="mb-[18px] grid grid-cols-[1fr_1fr_auto_1fr_1fr] items-center gap-3 max-[600px]:grid-cols-[1fr_auto_1fr]"
        aria-hidden="true"
      >
        <i
          className={cn(slot, "max-[600px]:hidden")}
          style={{ "--c": "#FFE14D" } as CSSProperties}
        />
        <i className={slot} style={{ "--c": "#67E8F9" } as CSSProperties} />
        <span className="grid size-[110px] place-items-center rounded-full border-[2.5px] border-[#111] bg-[#FFE14D] shadow-[4px_5px_0_#111]">
          <span className="relative h-5 w-[60px]">
            <span className="absolute top-0.5 left-0 h-[9px] w-5 rounded-b-[20px] border-4 border-t-0 border-[#111]" />
            <span className="absolute top-0.5 right-0 h-[9px] w-5 rounded-b-[20px] border-4 border-t-0 border-[#111]" />
          </span>
        </span>
        <i className={slot} style={{ "--c": "#A3E635" } as CSSProperties} />
        <i
          className={cn(slot, "max-[600px]:hidden")}
          style={{ "--c": "#FF8FB5" } as CSSProperties}
        />
      </div>
      <p className="mx-0 mt-1.5 mb-4 font-display text-xl leading-[normal] font-extrabold tracking-normal">
        <strong>{message}</strong>
      </p>
    </div>
  );
}

type StanceValue = "support" | "oppose" | "neutral";
// A new Debate is always ordered multi-expert mutual learning. The legacy demo
// RuleSets remain readable on existing Debates but can no longer be created.
type DebateRuleSetId = "ordered_multi_expert_mutual_learning_v1";
// The teacher note never reaches the model (manifests forbid exporting it),
// so the form no longer offers or sends one.
type SetupParticipant = Omit<
  DebateDraftRequest["participants"][number],
  "teacher_note"
>;
type SetupDraftPayload = Omit<
  DebateDraftRequest,
  "round_count" | "rule_set_id" | "participants"
> & {
  round_count: 4;
  rule_set_id: DebateRuleSetId;
  participants: SetupParticipant[];
};
type ParticipantDraft = {
  mode: "assigned" | "open";
  stance: StanceValue | null;
};

const defaultParticipant = (): ParticipantDraft => ({
  mode: "open",
  stance: null,
});

function defaultCreateController(api: PlatformApi): DebateCreateController {
  return {
    loadCandidates: (courseId) => api.publishedAgents(courseId),
    loadRuleset: (courseId) => api.debateRulesetDefaults(courseId),
    loadLLMDefaults: (courseId) => api.debateLLMDefaults(courseId),
    create: (courseId, payload, idempotency) =>
      api.createDebate(courseId, payload, { idempotency }),
  };
}

export function TeacherDebateCreate({
  controller,
}: {
  controller?: DebateCreateController;
}) {
  const t = useT();
  const router = useRouter();
  const { api, user } = useSession();
  const courseId = teacherCourseId(user);
  const effectiveController = useMemo(
    () => controller ?? defaultCreateController(api),
    [api, controller],
  );
  const [candidates, setCandidates] = useState<PublishedAgentSummary[]>([]);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [participantDrafts, setParticipantDrafts] = useState<
    Record<string, ParticipantDraft>
  >({});
  const [topic, setTopic] = useState("");
  const [background, setBackground] = useState("");
  const topicInputRef = useRef<HTMLTextAreaElement>(null);
  const backgroundInputRef = useRef<HTMLTextAreaElement>(null);
  const [teachingPrompts, setTeachingPrompts] = useState<TeachingPrompts>({
    zh: "",
    en: "",
  });
  const [contract, setContract] = useState<TeachingPrompts | null>(null);
  const [rulesEditing, setRulesEditing] = useState(false);
  const [targetMinutes, setTargetMinutes] = useState(DEFAULT_TARGET_MINUTES);
  const [llmDefaults, setLLMDefaults] = useState<DebateLLMDefaults | null>(
    null,
  );
  const [llmValues, setLLMValues] = useState<LLMParamValues | null>(null);
  const [voiceValues, setVoiceValues] = useState<VoiceParamValues | null>(null);
  const rulesLoaded = useRef(false);
  const [outputLanguage, setOutputLanguage] = useState<"en" | "zh">("zh");
  const ruleSetId: DebateRuleSetId = "ordered_multi_expert_mutual_learning_v1";
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [topicError, setTopicError] = useState<string | null>(null);
  // The Agent the form problem is about (a stance), for its card's badge.
  const [formAgent, setFormAgent] = useState<string | null>(null);
  // Bumped on every validation pass and refusal, so the bar at the top is
  // scrolled back into view even when the same problem repeats.
  const [validationAttempt, setValidationAttempt] = useState(0);
  const formRef = useRef<HTMLFormElement>(null);
  useEffect(() => {
    if (loading || typeof ResizeObserver === "undefined") return;
    const inputs = [topicInputRef.current, backgroundInputRef.current].filter(
      (input): input is HTMLTextAreaElement => input !== null,
    );
    let height = Math.max(
      120,
      ...inputs.map((input) => input.getBoundingClientRect().height),
    );
    for (const input of inputs) input.style.height = `${height}px`;
    const observer = new ResizeObserver((entries) => {
      const resized = entries.find(
        (entry) =>
          Math.abs(entry.target.getBoundingClientRect().height - height) > 0.5,
      );
      if (!resized) return;
      height = Math.max(120, resized.target.getBoundingClientRect().height);
      for (const input of inputs) input.style.height = `${height}px`;
    });
    inputs.forEach((input) => observer.observe(input));
    return () => observer.disconnect();
  }, [loading]);

  const createMutation = useRef<{
    requestHash: string;
    handle: IdempotencyHandle;
  } | null>(null);

  const load = useCallback(async () => {
    if (!courseId) {
      setError(new Error(copy(t, "debateNoCourse")));
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [next, defaults, llm] = await Promise.all([
        effectiveController.loadCandidates(courseId),
        rulesLoaded.current
          ? Promise.resolve(null)
          : effectiveController.loadRuleset(courseId),
        rulesLoaded.current || !effectiveController.loadLLMDefaults
          ? Promise.resolve(null)
          : effectiveController.loadLLMDefaults(courseId),
      ]);
      if (llm !== null) {
        setLLMDefaults(llm);
        setLLMValues(defaultParamValues(llm.params));
        setVoiceValues(defaultVoiceValues(llm.voice_params ?? []));
      }
      if (defaults !== null) {
        // Only the editable Ruleset is kept for sending; the contract is the
        // platform's and is shown, never sent back.
        setTeachingPrompts({ zh: defaults.zh, en: defaults.en });
        setContract(defaults.contract ?? null);
        rulesLoaded.current = true;
      }
      setCandidates(next.filter((item) => item.agent.status === "active"));
    } catch (cause) {
      setError(cause);
    } finally {
      setLoading(false);
    }
  }, [courseId, effectiveController, t]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const agentNames = useMemo(
    () =>
      Object.fromEntries(
        candidates.map((item) => [item.agent.id, item.agent.name]),
      ) as Record<string, string>,
    [candidates],
  );
  // Read from each Agent's current published version by the server
  // (agents/readiness.py), so the form and the create agree.
  const selectedReadiness = selectedIds.flatMap((agentId) => {
    const candidate = candidates.find((item) => item.agent.id === agentId);
    return candidate ? readinessIssues(candidate) : [];
  });

  function toggleCandidate(candidate: PublishedAgentSummary) {
    setFormError(null);
    setFormAgent(null);
    setError(null);
    setValidationAttempt((attempt) => attempt + 1);
    const id = candidate.agent.id;
    if (selectedIds.includes(id)) {
      setSelectedIds((current) => current.filter((item) => item !== id));
      return;
    }
    if (selectedIds.length >= 5) {
      setFormError(copy(t, "debateSelectAtMost"));
      return;
    }
    setSelectedIds((current) => [...current, id]);
    setParticipantDrafts((current) => ({
      ...current,
      [id]: current[id] ?? defaultParticipant(),
    }));
  }

  function updateParticipant(id: string, patch: Partial<ParticipantDraft>) {
    setParticipantDrafts((current) => ({
      ...current,
      [id]: { ...(current[id] ?? defaultParticipant()), ...patch },
    }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (rulesEditing || busy || !rulesLoaded.current) return;
    setFormError(null);
    setFormAgent(null);
    setValidationAttempt((attempt) => attempt + 1);
    // Every problem at once, so the mascot lists them all in one bubble.
    const topicValidation = validateDebateTopic(topic);
    setTopicError(
      topicValidation.valid ? null : copy(t, "debateTopicRequired"),
    );
    const blocking = selectedReadiness.some((item) => item.blocking);
    const unstancedId = selectedIds.find((agentId) => {
      const draft = participantDrafts[agentId] ?? defaultParticipant();
      return draft.mode === "assigned" && !draft.stance;
    });
    let problem: string | null = null;
    if (selectedIds.length < 2) problem = copy(t, "debateSelectAtLeast");
    else if (!courseId) problem = copy(t, "debateNoCourse");
    else if (unstancedId) {
      problem = t("debateFieldStanceMissing", {
        name: agentNames[unstancedId] ?? "",
      });
      setFormAgent(unstancedId);
    }
    if (problem) setFormError(problem);
    // The same checks the server makes, already on screen: nothing to send.
    if (blocking) setError(null);
    if (!topicValidation.valid || blocking || problem || !courseId) return;
    const payload: SetupDraftPayload = {
      topic: topicValidation.normalized,
      background,
      teaching_prompts: teachingPrompts,
      output_language: outputLanguage,
      turn_protocol: "segments_v2",
      participants: selectedIds.map((agentId) => {
        const draft = participantDrafts[agentId] ?? defaultParticipant();
        return {
          agent_id: agentId,
          stance_mode: draft.mode,
          assigned_stance: draft.mode === "assigned" ? draft.stance : null,
        };
      }),
      round_count: 4,
      rule_set_id: ruleSetId,
      total_duration_seconds: null,
      turn_duration_seconds: null,
      target_minutes: targetMinutes,
      ...(llmValues ? { llm_params: paramsPayload(llmValues) } : {}),
      ...(voiceValues ? { voice_params: voicePayload(voiceValues) } : {}),
    };
    const unstanced = payload.participants.find(
      (item) => item.stance_mode === "assigned" && !item.assigned_stance,
    );
    if (unstanced) {
      setFormError(
        t("debateFieldStanceMissing", {
          name: agentNames[unstanced.agent_id] ?? "",
        }),
      );
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const requestHash = JSON.stringify(payload);
      if (createMutation.current?.requestHash !== requestHash) {
        createMutation.current = {
          requestHash,
          handle: createIdempotencyHandle(),
        };
      }
      const created = await effectiveController.create(
        courseId,
        payload as DebateDraftRequest,
        createMutation.current.handle,
      );
      if (!created?.id) throw new Error(copy(t, "debateCreateUnconfirmed"));
      createMutation.current = null;
      celebrate();
      router.replace("/teacher/debates");
    } catch (cause) {
      if (!isAmbiguousMutationFailure(cause)) createMutation.current = null;
      setError(cause);
      setValidationAttempt((attempt) => attempt + 1);
      // A refused Agent may have changed since the list was read: read it
      // again, so the bar's checks match what the server just said.
      if (agentIssuesFromError(cause)) void refreshCandidates();
    } finally {
      setBusy(false);
    }
  }

  async function refreshCandidates() {
    if (!courseId) return;
    try {
      const next = await effectiveController.loadCandidates(courseId);
      setCandidates(next.filter((item) => item.agent.status === "active"));
    } catch {
      // The bar already shows the server's answer.
    }
  }

  const issues = mergeIssues(
    [agentIssuesFromError(error) ?? [], selectedReadiness],
    agentNames,
  );
  const fieldLines = (
    debateFieldProblems(
      error,
      (index) => agentNames[selectedIds[index]] ?? "",
    ) ?? []
  ).map((problem) => ({
    text: t(problem.key, problem.params ?? {}),
    href: problem.anchor ? `#${problem.anchor}` : null,
  }));
  const mustFix =
    Boolean(topicError || formError || fieldLines.length) ||
    issues.some((item) => item.blocking);
  const otherError =
    error && !agentIssuesFromError(error) && fieldLines.length === 0
      ? error
      : null;
  const editAgentHref = (agentId: string) =>
    `/teacher/agents/${encodeURIComponent(agentId)}`;
  // In page order: the topic, then each Agent row top to bottom.
  const checklistItems: ChecklistItem[] = [
    ...(topicError
      ? [{ key: "topic", text: topicError, target: "debate-topic" }]
      : []),
    ...fieldLines.map((line) => ({
      key: `field:${line.text}`,
      text: line.text,
      target: line.href ? line.href.slice(1) : undefined,
    })),
    ...issues.map((item) => ({
      key: `agent:${issueKey(item)}`,
      text: t(AGENT_ISSUE_MESSAGES[item.issue], { name: item.agent_name }),
      agentId: item.agent_id,
      href: editAgentHref(item.agent_id),
      editLabel: t("agentIssueEdit", { name: item.agent_name }),
    })),
    ...(formError
      ? [
          {
            key: `form:${formError}`,
            text: formError,
            target: formAgent ? `debate-stance-${formAgent}` : "debate-agents",
            agentId: formAgent ?? undefined,
          },
        ]
      : []),
  ];
  const entries = useCreateChecklist(checklistItems, validationAttempt);
  const topicEntry = entries.find((entry) => entry.key === "topic");
  const agentEntry = (agentId: string) =>
    entries.find((entry) => entry.agentId === agentId && !entry.done);
  if (loading) return <LoadingCard />;
  if (error && candidates.length === 0) {
    return <ErrorNotice inline error={error} onRetry={() => void load()} />;
  }

  return (
    <div className={cn(DEBATE_PAGE, "flex flex-col")}>
      {/* The same title row as the Debates list, with Back and Done at its
        right like every other page's own keys. */}
      <div className="mb-[22px] flex flex-wrap items-center gap-3">
        <h1 className={DEBATE_TITLE}>{copy(t, "newDebateTitle")}</h1>
        <span
          className="relative h-0 min-w-6 flex-1 border-t-[3px] border-dotted border-[#111]"
          aria-hidden="true"
        />
        {/* Creating mid-edit would freeze rules other than the ones on
          screen, so Back and Done wait until the ruleset edit is saved or
          discarded. */}
        {!rulesEditing ? (
          <>
            <PageAction
              name="back"
              placement="page"
              href="/teacher/debates"
              disabled={busy}
            />
            <PageAction
              name="done"
              placement="page"
              form="create-debate-form"
              disabled={busy || candidates.length === 0}
              busy={busy}
            />
          </>
        ) : null}
      </div>
      <CreateChecklist
        title={t(mustFix ? "debateFixBeforeCreate" : "debateAgentsHints")}
        entries={entries}
        attempt={validationAttempt}
        alert={mustFix}
      />
      {otherError ? (
        <ErrorNotice
          error={otherError}
          onRetry={() => formRef.current?.requestSubmit()}
        />
      ) : null}
      <form
        // The mascot checklist names every problem; no browser popup.
        noValidate
        ref={formRef}
        id="create-debate-form"
        className="flex flex-col"
        onSubmit={submit}
      >
        <div className="grid grid-cols-2 gap-5 max-[600px]:grid-cols-1 max-[600px]:gap-0">
          <CreateCard
            title={copy(t, "debateTopic")}
            className="overflow-visible"
            guide="debate.topic"
          >
            <ChecklistBadge entry={topicEntry} />
            <div>
              <textarea
                ref={topicInputRef}
                aria-label={copy(t, "debateTopic")}
                aria-invalid={topicError !== null}
                aria-describedby={
                  topicEntry && !topicEntry.done
                    ? checklistLineId(topicEntry.n)
                    : undefined
                }
                disabled={busy}
                id="debate-topic"
                className={cn(
                  CREATE_TEXTAREA,
                  topicEntry && !topicEntry.done
                    ? "border-err! shadow-[0_0_0_3px_#FFE4E4,3px_3px_0_#EF4444]!"
                    : "",
                )}
                onChange={(event) => {
                  setTopic(event.target.value);
                  if (topicError) setTopicError(null);
                }}
                placeholder={copy(t, "debateTopicPlaceholder")}
                required
                rows={3}
                value={topic}
              />
            </div>
          </CreateCard>
          <CreateCard
            title="Background"
            className="[--sh:#67E8F9]"
            guide="debate.background"
          >
            <textarea
              ref={backgroundInputRef}
              aria-label="Background"
              className={CREATE_TEXTAREA}
              disabled={busy}
              placeholder="Optional context"
              rows={3}
              value={background}
              onChange={(event) => setBackground(event.target.value)}
            />
          </CreateCard>
        </div>

        <CreateCard title="Agents Order" guide="debate.agentOrder">
          <p
            className="my-2.5 flex items-center gap-2.5 font-body text-xs leading-[normal] font-bold"
            role="status"
          >
            <span className="inline-flex gap-[3px]" aria-hidden="true">
              {[0, 1, 2, 3, 4].map((slot) => (
                <i
                  key={slot}
                  className={cn(
                    "box-border size-3 rounded-full border-2 border-[#111] bg-white",
                    slot < selectedIds.length && "bg-[#FF4D8D]",
                  )}
                />
              ))}
            </span>
            {copy(t, "debateSelectCount").replace(
              "{count}",
              `${selectedIds.length}/5`,
            )}
          </p>
          {candidates.length === 0 ? (
            <EmptyCard title={copy(t, "debateNoCandidates")} />
          ) : (
            <div
              id="debate-agents"
              tabIndex={-1}
              className="grid gap-2 overflow-visible outline-none"
            >
              {candidates.map((candidate, index) => {
                const id = candidate.agent.id;
                const order = selectedIds.indexOf(id);
                const selected = order !== -1;
                const draft = participantDrafts[id] ?? defaultParticipant();
                const problem = selected ? agentEntry(id) : undefined;
                return (
                  <div
                    key={id}
                    data-invalid={problem ? true : undefined}
                    style={
                      {
                        "--tone": AGENT_TONES[index % AGENT_TONES.length],
                      } as CSSProperties
                    }
                    className={cn(
                      "relative box-border flex w-full cursor-pointer flex-wrap items-center gap-x-3 gap-y-2 rounded-[999px] border-[2.5px] border-[#111] bg-white py-1.5 pr-3.5 pl-1.5",
                      selected &&
                        "bg-[color-mix(in_srgb,var(--tone)_35%,#fff)] shadow-[3px_4px_0_var(--tone)]",
                      problem &&
                        "border-err! shadow-[0_0_0_3px_#FFE4E4,3px_3px_0_#EF4444]!",
                    )}
                    onClick={(event) => {
                      if (
                        !busy &&
                        !(event.target as HTMLElement).closest(
                          "button,input,select,textarea,label,[data-agent-controls]",
                        )
                      )
                        toggleCandidate(candidate);
                    }}
                  >
                    <button
                      type="button"
                      className="m-0 flex h-auto min-w-0 flex-1 cursor-pointer items-center gap-3 border-0 bg-transparent p-0 text-left font-body text-[#111] shadow-none disabled:cursor-default"
                      disabled={busy}
                      aria-label={candidate.agent.name}
                      aria-pressed={selected}
                      aria-describedby={
                        problem ? checklistLineId(problem.n) : undefined
                      }
                      onClick={() => toggleCandidate(candidate)}
                    >
                      <ChecklistBadge entry={problem} />
                      <span
                        className={cn(
                          "box-border grid size-7 flex-none place-items-center rounded-full border-2 border-[#111] bg-white font-body text-[15px] leading-[normal] font-extrabold",
                          selected && "bg-[#FF4D8D]",
                        )}
                        aria-hidden="true"
                      >
                        {selected ? order + 1 : "+"}
                      </span>
                      <span
                        className="box-border grid size-10 flex-none place-items-[end_center] overflow-hidden rounded-full border-2 border-[#111] bg-[var(--tone)] text-[#111]"
                        aria-hidden="true"
                      >
                        <IconBust />
                      </span>
                      <span className="min-w-0 text-base leading-[normal]">
                        <strong className="block text-[15px] leading-[normal] font-bold">
                          {candidate.agent.name}
                        </strong>
                        <span className="text-xs leading-[normal] text-[#4B5563]">
                          <span className="mr-1 rounded-full border-2 border-[#111] bg-white px-1.5 font-body text-[11px] font-bold whitespace-nowrap text-[#111]">
                            {candidate.current_version.version_label}
                          </span>{" "}
                          <span>{candidate.group_name}</span>
                        </span>
                      </span>
                    </button>
                    {selected ? (
                      <div
                        data-agent-controls
                        className="ml-auto flex flex-wrap items-center gap-2 max-[600px]:ml-0 max-[600px]:w-full max-[600px]:pb-1 max-[600px]:pl-1"
                      >
                        <div
                          className={CREATE_SEG}
                          aria-label={copy(t, "debateStance") as string}
                        >
                          <button
                            className={cn(CREATE_SEG_BUTTON, "border-l-0")}
                            aria-pressed={draft.mode === "assigned"}
                            disabled={busy}
                            onClick={() =>
                              updateParticipant(id, {
                                mode: "assigned",
                                stance: draft.stance ?? "neutral",
                              })
                            }
                            type="button"
                          >
                            {copy(t, "debateAssigned")}
                          </button>
                          <button
                            className={CREATE_SEG_BUTTON}
                            aria-pressed={draft.mode === "open"}
                            disabled={busy}
                            onClick={() =>
                              updateParticipant(id, {
                                mode: "open",
                                stance: null,
                              })
                            }
                            type="button"
                          >
                            {copy(t, "debateOpen")}
                          </button>
                        </div>
                        {draft.mode === "assigned" ? (
                          <select
                            id={`debate-stance-${id}`}
                            aria-label={`${candidate.agent.name} ${copy(t, "debateAssigned")}`}
                            className="h-auto rounded-full border-[2.5px] border-[#111] bg-white px-2.5 py-1 font-body text-xs font-bold text-[#111]"
                            disabled={busy}
                            onChange={(event) =>
                              updateParticipant(id, {
                                stance: event.target.value as StanceValue,
                              })
                            }
                            value={draft.stance ?? "neutral"}
                          >
                            <option value="support">
                              {copy(t, "debateSupport")}
                            </option>
                            <option value="oppose">
                              {copy(t, "debateOppose")}
                            </option>
                            <option value="neutral">
                              {copy(t, "debateNeutral")}
                            </option>
                          </select>
                        ) : null}
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}
        </CreateCard>

        <CreateCard
          title="Target length"
          className="[--sh:#FDBA74]"
          guide="debate.targetLength"
        >
          <div className="mt-3 flex flex-wrap items-center gap-2.5">
            <div
              className={CREATE_SEG}
              role="group"
              aria-label="Target length in minutes"
            >
              {TARGET_MINUTES.map((minutes, index) => (
                <button
                  key={minutes}
                  type="button"
                  className={cn(CREATE_SEG_BUTTON, index === 0 && "border-l-0")}
                  aria-label={`${minutes} minutes`}
                  aria-pressed={targetMinutes === minutes}
                  disabled={busy}
                  onClick={() => setTargetMinutes(minutes)}
                >
                  {minutes}
                </button>
              ))}
            </div>
            <span className="font-body text-xs leading-[normal] font-bold">
              minutes
            </span>
          </div>
          <p className="mt-2 mb-0 font-body text-xs leading-normal text-[#4B5563]">
            Speeches are kept short enough for the whole debate to fit this
            length.
          </p>
        </CreateCard>

        <RulesetEditor
          prompts={teachingPrompts}
          contract={contract}
          language={outputLanguage}
          disabled={busy}
          onLanguageChange={setOutputLanguage}
          onSave={setTeachingPrompts}
          onEditingChange={setRulesEditing}
        />
        {llmDefaults && llmValues ? (
          <LlmParamsCard
            specs={llmDefaults.params}
            values={llmValues}
            disabled={busy}
            onChange={(name, next) =>
              setLLMValues((current) =>
                current ? { ...current, [name]: next } : current,
              )
            }
            voiceSpecs={llmDefaults.voice_params ?? []}
            voiceValues={voiceValues ?? undefined}
            onVoiceChange={(name, next) =>
              setVoiceValues((current) =>
                current ? { ...current, [name]: next } : current,
              )
            }
            onReset={() => {
              setLLMValues(defaultParamValues(llmDefaults.params));
              setVoiceValues(
                defaultVoiceValues(llmDefaults.voice_params ?? []),
              );
            }}
          />
        ) : null}
      </form>
    </div>
  );
}

// The server accepts 3 to 10 and defaults to 5 (DebateDraftRequest).
const TARGET_MINUTES = [3, 4, 5, 6, 7, 8, 9, 10] as const;
const DEFAULT_TARGET_MINUTES = 5;

const AGENT_TONES = [
  "#FFE14D",
  "#67E8F9",
  "#A3E635",
  "#FF8FB5",
  "#FDBA74",
] as const;

// Keep the existing name available for the page-level integration point.
