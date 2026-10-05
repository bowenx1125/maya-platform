"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";

import {
  createIdempotencyHandle,
  isAmbiguousMutationFailure,
  type IdempotencyHandle,
  type DebateDetail,
  type DebateDraftRequest,
  type DebateSummary,
  type PlatformApi,
  type PublishedAgentSummary,
} from "../../../lib/api";
import { localizeError, type MessageKey } from "../../../lib/i18n";
import { RulesetEditor, type TeachingPrompts } from "./ruleset-editor";
import sectionStyles from "./create-section.module.css";
import { validateDebateTopic } from "../../../lib/debate-topic";
import { useLocale, useT } from "../../locale";
import { useSession } from "../../session-provider";
import { DebateCleanupControls } from "../debate-cleanup-controls";
import { DebateStatus } from "../debate-status";

import {
  EmptyCard,
  ErrorNotice,
  LoadingCard,
  PageIntro,
  SectionCard,
} from "../../ui";
import rulesetStyles from "./ruleset-editor.module.css";
import styles from "./debate-setup.module.css";
import { PageAction } from "../../page-action";

export type { DebateDetail, DebateDraftRequest, DebateSummary };

export type DebateListController = {
  load: (courseId: string) => Promise<DebateSummary[]>;
};

export type DebateCreateController = {
  loadRuleset: (courseId: string) => Promise<TeachingPrompts>;
  loadCandidates: (courseId: string) => Promise<PublishedAgentSummary[]>;
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

  const load = useCallback(
    async (silent = false) => {
      const sequence = ++loadSequence.current;
      if (!courseId) {
        setError(new Error(t("debateCreateUnavailable")));
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
        setDebates(next);
        setError(null);
      } catch (cause) {
        if (!silent && sequence === loadSequence.current) setError(cause);
      } finally {
        if (sequence === loadSequence.current) setLoading(false);
      }
    },
    [api, controller, courseId, t],
  );

  useEffect(() => {
    let stopped = false;
    let timer: number;
    const poll = async (initial = false) => {
      if (initial || document.visibilityState !== "hidden")
        await load(!initial);
      if (!stopped) timer = window.setTimeout(() => void poll(), 2000);
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

  const newDebate = (
    <PageAction name="new" href="/teacher/debates/new" disabled={!courseId} />
  );

  return (
    <div className={styles.pageStack}>
      <PageIntro title={t("debatePreviewTitle")} />
      {loading ? <LoadingCard /> : null}
      {error ? <ErrorNotice error={error} onRetry={() => void load()} /> : null}
      {!loading && !error ? (
        <SectionCard action={debates.length > 0 ? newDebate : undefined}>
          {debates.length === 0 ? (
            <div className={styles.emptyState}>
              <strong>{t("debateNoDebates")}</strong>
              {newDebate}
            </div>
          ) : (
            <div className={styles.list}>
              {debates.map((debate) => (
                <div className={styles.debateRow} key={debate.id}>
                  <Link
                    className={styles.debateCard}
                    href={`/teacher/debates/${debate.id}/control`}
                  >
                    <div>
                      <h2>{debate.topic}</h2>
                      <div className={styles.metaRow}>
                        <span>{copy(t, "debateRounds")}</span>
                        <span>
                          {new Date(debate.created_at).toLocaleDateString()}
                        </span>
                      </div>
                    </div>
                    {/* A draft is not idle: it is warming its turns in the
                      background, so the list says how far along it is rather
                      than only that it is a draft. */}
                    {/* A stall outranks both other readings, and a running
                      debate can stall too: the lesson that stopped generating
                      mid-round used to read Running with nothing to act on. */}
                    <DebateStatus debate={debate} />
                  </Link>
                  <div className={styles.debateActions}>
                    {["completed", "debate_finished"].includes(
                      debate.status,
                    ) ? (
                      <ClassroomResetButton
                        debateId={debate.id}
                        onDone={() => void load(true)}
                      />
                    ) : null}
                    {!["failed", "stopped"].includes(debate.status) &&
                    (debate.preview?.ready ||
                      ["running", "completed", "debate_finished"].includes(
                        debate.status,
                      )) ? (
                      <Link
                        className="secondary-action"
                        href={`/teacher/debates-beta/${debate.id}/control`}
                      >
                        Immerse
                      </Link>
                    ) : (
                      <button type="button" disabled>
                        Immerse
                      </button>
                    )}
                    <DebateCleanupControls
                      api={api}
                      debateId={debate.id}
                      loadDetail={() => api.debate(debate.id)}
                      onVoiceDeleted={load}
                      onAllDeleted={() => {
                        loadSequence.current += 1;
                        setDebates((rows) =>
                          rows.filter((row) => row.id !== debate.id),
                        );
                      }}
                      className={styles.listCleanup}
                      audioRestoreNeeded={debate.audio_restore_needed}
                    />
                  </div>
                </div>
              ))}
            </div>
          )}
        </SectionCard>
      ) : null}
    </div>
  );
}

function ClassroomResetButton({
  debateId,
  onDone,
}: {
  debateId: string;
  onDone: () => void;
}) {
  const { api } = useSession();
  const [busy, setBusy] = useState(false);
  const active = useRef(false);
  return (
    <button
      className="secondary-action"
      disabled={busy}
      type="button"
      onClick={async () => {
        if (active.current) return;
        if (
          !window.confirm(
            "Keep Preview and reset this classroom? Messages, Report and the final round will be removed.",
          )
        )
          return;
        active.current = true;
        setBusy(true);
        try {
          const detail = await api.debate(debateId);
          await api.rebirthDebate(
            debateId,
            {
              expected_revision: detail.revision,
              expected_control_version: detail.playback.control_version,
            },
            { idempotency: createIdempotencyHandle() },
          );
        } catch {
          // A refused action leaves the row unchanged.
        } finally {
          active.current = false;
          setBusy(false);
          onDone();
        }
      }}
    >
      Rebirth
    </button>
  );
}

type StanceValue = "support" | "oppose" | "neutral";
// A new Debate is always ordered multi-expert mutual learning. The legacy demo
// RuleSets remain readable on existing Debates but can no longer be created.
type DebateRuleSetId = "ordered_multi_expert_mutual_learning_v1";
type SetupDraftPayload = Omit<
  DebateDraftRequest,
  "round_count" | "rule_set_id"
> & {
  round_count: 4;
  rule_set_id: DebateRuleSetId;
};
type ParticipantDraft = {
  mode: "assigned" | "open";
  stance: StanceValue | null;
  note: string;
};

const defaultParticipant = (): ParticipantDraft => ({
  mode: "open",
  stance: null,
  note: "",
});

function defaultCreateController(api: PlatformApi): DebateCreateController {
  return {
    loadCandidates: (courseId) => api.publishedAgents(courseId),
    loadRuleset: (courseId) => api.debateRulesetDefaults(courseId),
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
  const [rulesEditing, setRulesEditing] = useState(false);
  const rulesLoaded = useRef(false);
  const [outputLanguage, setOutputLanguage] = useState<"en" | "zh">("zh");
  const ruleSetId: DebateRuleSetId = "ordered_multi_expert_mutual_learning_v1";
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [topicError, setTopicError] = useState<string | null>(null);
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
      setError(new Error(copy(t, "debateCreateUnavailable")));
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [next, defaults] = await Promise.all([
        effectiveController.loadCandidates(courseId),
        rulesLoaded.current
          ? Promise.resolve(null)
          : effectiveController.loadRuleset(courseId),
      ]);
      if (defaults !== null) {
        setTeachingPrompts(defaults);
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

  function toggleCandidate(candidate: PublishedAgentSummary) {
    setFormError(null);
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
    const topicValidation = validateDebateTopic(topic);
    if (!topicValidation.valid) {
      setTopicError(copy(t, "debateTopicRequired"));
      return;
    }
    setTopicError(null);
    if (selectedIds.length < 2) {
      setFormError(copy(t, "debateSelectAtLeast"));
      return;
    }
    if (!courseId) {
      setFormError(copy(t, "debateCreateUnavailable"));
      return;
    }
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
          teacher_note: draft.note,
        };
      }),
      round_count: 4,
      rule_set_id: ruleSetId,
      total_duration_seconds: null,
      turn_duration_seconds: null,
    };
    if (
      payload.participants.some(
        (item) => item.stance_mode === "assigned" && !item.assigned_stance,
      )
    ) {
      setFormError(copy(t, "debateAssigned"));
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
      if (!created?.id) throw new Error(copy(t, "debateCreateUnavailable"));
      createMutation.current = null;
      router.replace("/teacher/debates");
    } catch (cause) {
      if (!isAmbiguousMutationFailure(cause)) createMutation.current = null;
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  if (loading) return <LoadingCard />;
  if (error && candidates.length === 0) {
    return <ErrorNotice error={error} onRetry={() => void load()} />;
  }

  return (
    <div className={styles.pageStack}>
      <PageIntro title={copy(t, "newDebateTitle")} />
      <PageAction name="back" href="/teacher/debates" disabled={busy} />
      {error ? <ErrorNotice error={error} onRetry={() => void load()} /> : null}
      <form
        id="create-debate-form"
        className={styles.pageStack}
        onSubmit={submit}
      >
        <div className={styles.topicColumns}>
          <SectionCard
            title={copy(t, "debateTopic")}
            className={`${styles.topicCard} ${sectionStyles.section}`}
            guide="debate.topic"
          >
            <div>
              <textarea
                ref={topicInputRef}
                aria-label={copy(t, "debateTopic")}
                aria-describedby={topicError ? "debate-topic-error" : undefined}
                aria-invalid={topicError !== null}
                disabled={busy}
                id="debate-topic"
                className={styles.contextInput}
                onChange={(event) => {
                  setTopic(event.target.value);
                  if (topicError) setTopicError(null);
                }}
                placeholder={copy(t, "debateTopicPlaceholder")}
                required
                rows={3}
                value={topic}
              />
              {topicError ? (
                <span
                  className={styles.fieldError}
                  id="debate-topic-error"
                  role="alert"
                >
                  {topicError}
                </span>
              ) : null}
            </div>
          </SectionCard>
          <SectionCard
            title="Background"
            className={`${styles.topicCard} ${sectionStyles.section}`}
            guide="debate.background"
          >
            <textarea
              ref={backgroundInputRef}
              aria-label="Background"
              className={styles.contextInput}
              disabled={busy}
              placeholder="Optional context"
              rows={3}
              value={background}
              onChange={(event) => setBackground(event.target.value)}
            />
          </SectionCard>
        </div>

        <SectionCard
          className={sectionStyles.section}
          title="Agents Order"
          guide="debate.agentOrder"
        >
          <p className={styles.listMeta} role="status">
            {copy(t, "debateSelectCount").replace(
              "{count}",
              `${selectedIds.length}/5`,
            )}
          </p>
          {candidates.length === 0 ? (
            <EmptyCard title={copy(t, "debateNoCandidates")} />
          ) : (
            <div className={styles.agentOrderList}>
              {candidates.map((candidate) => {
                const id = candidate.agent.id;
                const order = selectedIds.indexOf(id);
                const selected = order !== -1;
                const draft = participantDrafts[id] ?? defaultParticipant();
                return (
                  <div
                    key={id}
                    className={`${styles.agentOrderRow} ${selected ? styles.agentOrderSelected : ""}`}
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
                      className={styles.agentIdentity}
                      disabled={busy}
                      aria-label={candidate.agent.name}
                      aria-pressed={selected}
                      onClick={() => toggleCandidate(candidate)}
                    >
                      <span className={styles.orderNumber} aria-hidden="true">
                        {selected ? order + 1 : "+"}
                      </span>
                      <span className={styles.agentText}>
                        <strong>{candidate.agent.name}</strong>
                        <span className={styles.agentMeta}>
                          <span className="status-pill status-good">
                            {candidate.current_version.version_label}
                          </span>
                          <span>{candidate.group_name}</span>
                        </span>
                      </span>
                    </button>
                    {selected ? (
                      <div
                        data-agent-controls
                        className={`${styles.orderControls} ${draft.mode === "open" ? styles.orderControlsOpen : ""}`}
                      >
                        <div
                          className={rulesetStyles.languageSwitch}
                          aria-label={copy(t, "debateStance") as string}
                        >
                          <button
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
                            aria-label={`${candidate.agent.name} ${copy(t, "debateAssigned")}`}
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
                        <input
                          aria-label={`${candidate.agent.name} ${copy(t, "debateNote")}`}
                          className={styles.noteInput}
                          disabled={busy}
                          onChange={(event) =>
                            updateParticipant(id, { note: event.target.value })
                          }
                          placeholder="Agent note"
                          value={draft.note}
                        />
                      </div>
                    ) : null}
                  </div>
                );
              })}
            </div>
          )}
        </SectionCard>

        <RulesetEditor
          prompts={teachingPrompts}
          language={outputLanguage}
          disabled={busy}
          onLanguageChange={setOutputLanguage}
          onSave={setTeachingPrompts}
          onEditingChange={setRulesEditing}
        />
        {formError ? (
          <div className="form-error" role="alert">
            {formError}
          </div>
        ) : null}
        {/* Creating mid-edit would freeze rules other than the ones on
          screen, so Done waits until the ruleset edit is saved or discarded. */}
        {!rulesEditing ? (
          <div className="button-row">
            <PageAction
              name="done"
              form="create-debate-form"
              disabled={busy || candidates.length === 0}
            />
          </div>
        ) : null}
      </form>
    </div>
  );
}

// Keep the existing name available for the page-level integration point.
