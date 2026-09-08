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
import { validateDebateTopic } from "../../../lib/debate-topic";
import { useLocale, useT } from "../../locale";
import { useSession } from "../../session-provider";
import { DebateCleanupControls } from "../debate-cleanup-controls";

import {
  EmptyCard,
  ErrorNotice,
  LoadingCard,
  PageIntro,
  SectionCard,
  StatusBadge,
} from "../../ui";
import styles from "./debate-setup.module.css";

export type { DebateDetail, DebateDraftRequest, DebateSummary };

export type DebateListController = {
  load: (courseId: string) => Promise<DebateSummary[]>;
};

export type DebateCreateController = {
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

function interpolate(
  value: string,
  values: Record<string, string | number>,
): string {
  return value.replace(/\{(\w+)\}/g, (_, key: string) =>
    String(values[key] ?? `{${key}}`),
  );
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

  if (loading) return <LoadingCard />;
  if (error) return <ErrorNotice error={error} onRetry={() => void load()} />;

  return (
    <div className={styles.pageStack}>
      <PageIntro
        eyebrow={t("debates")}
        title={t("debatePreviewTitle")}
        action={
          <Link className="primary-action" href="/teacher/debates/new">
            {t("newDebate")}
          </Link>
        }
      />
      <SectionCard>
        {debates.length === 0 ? (
          <div className={styles.emptyState}>
            <strong>{t("debateNoDebates")}</strong>
            <Link className="secondary-action" href="/teacher/debates/new">
              {t("newDebate")}
            </Link>
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
                  {stalled(debate) ? (
                    <PrewarmBadge
                      expected={
                        debate.preview?.expected_turns ??
                        debate.expected_turns ??
                        0
                      }
                      prepared={
                        debate.preview?.prepared_turns ??
                        debate.prepared_turns ??
                        0
                      }
                      stall={debate.stall}
                    />
                  ) : debate.status === "draft" ? (
                    <PrewarmBadge
                      expected={
                        debate.preview?.expected_turns ??
                        debate.expected_turns ??
                        0
                      }
                      prepared={
                        debate.preview?.prepared_turns ??
                        debate.prepared_turns ??
                        0
                      }
                    />
                  ) : (
                    <StatusBadge status={debate.status} />
                  )}
                </Link>
                <div className={styles.debateActions}>
                  {stalled(debate) || debate.status === "failed" ? (
                    <ClassroomResetButton
                      debateId={debate.id}
                      action="remake"
                      onDone={() => void load(true)}
                    />
                  ) : null}
                  {["completed", "debate_finished"].includes(debate.status) ? (
                    <ClassroomResetButton
                      debateId={debate.id}
                      action="rebirth"
                      onDone={() => void load(true)}
                    />
                  ) : null}
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
                    showGenerateAudio={false}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </SectionCard>
    </div>
  );
}

/**
 * How ready a draft is, in the words the teacher acts on.
 *
 * "Thinking" while it warms, with the share done, and "Ready" once every turn
 * is generated. Either way the debate can be started: an unwarmed turn simply
 * waits where it always did.
 */
/** A debate whose generation stopped and is still worth resuming.

 * Only while it could still reach the end: a stopped or failed debate has a
 * failed turn in its history too, and calling that a stall would offer a
 * Resume that leads nowhere.
 */
function stalled(debate: DebateSummary): boolean {
  return (
    debate.stall != null &&
    (debate.status === "draft" || debate.status === "running")
  );
}

function PrewarmBadge({
  prepared,
  expected,
  stall,
}: {
  prepared: number;
  expected: number;
  stall?: DebateSummary["stall"];
}) {
  const t = useT();
  const complete = expected > 0 && prepared >= expected;
  // A stalled task must not look as if its preparation count will advance.
  if (stall) {
    return (
      <span
        className="status-badge status-bad"
        data-prewarm="stalled"
        title={t("debateStalledReason")
          .replace("{round}", String(stall.round_no))
          .replace("{code}", stall.safe_error_code)}
      >
        <span aria-hidden="true" />
        {t("debateStalled")}
      </span>
    );
  }
  return (
    <span
      className={`status-badge ${complete ? "status-good" : "status-warn"}`}
      data-prewarm={complete ? "ready" : "thinking"}
    >
      <span aria-hidden="true" />
      {complete ? t("debatePrewarmReady") : `${prepared} / ${expected} turns`}
    </span>
  );
}

function ClassroomResetButton({
  debateId,
  action,
  onDone,
}: {
  debateId: string;
  action: "remake" | "rebirth";
  onDone: () => void;
}) {
  const { api } = useSession();
  const [busy, setBusy] = useState(false);
  const label = action === "rebirth" ? "Rebirth" : "Remake";
  return (
    <button
      className="secondary-action"
      disabled={busy}
      type="button"
      onClick={async () => {
        if (busy) return;
        if (
          !window.confirm(
            action === "rebirth"
              ? "Keep Preview and reset this classroom? Messages, Report and the final round will be removed."
              : "Recover this turn and continue the debate? Failed generation may call the provider again.",
          )
        )
          return;
        setBusy(true);
        try {
          const detail = await api.debate(debateId);
          await api[action === "rebirth" ? "rebirthDebate" : "remakeDebate"](
            debateId,
            {
              expected_revision: detail.revision,
              expected_control_version: detail.playback.control_version,
            },
            { idempotency: createIdempotencyHandle() },
          );
          onDone();
        } catch {
          // A refused action leaves the row unchanged.
        } finally {
          setBusy(false);
        }
      }}
    >
      {label}
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
  const [outputLanguage, setOutputLanguage] = useState<"en" | "zh">("en");
  const ruleSetId: DebateRuleSetId = "ordered_multi_expert_mutual_learning_v1";
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [topicError, setTopicError] = useState<string | null>(null);
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
      const next = await effectiveController.loadCandidates(courseId);
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

  const selectedCandidates = useMemo(
    () =>
      selectedIds
        .map((id) => candidates.find((item) => item.agent.id === id))
        .filter(Boolean) as PublishedAgentSummary[],
    [candidates, selectedIds],
  );

  function toggleCandidate(candidate: PublishedAgentSummary) {
    setFormError(null);
    const id = candidate.agent.id;
    if (selectedIds.includes(id)) {
      setSelectedIds((current) => current.filter((item) => item !== id));
      setParticipantDrafts((current) => {
        const next = { ...current };
        delete next[id];
        return next;
      });
      return;
    }
    if (selectedIds.length >= 5) {
      setFormError(copy(t, "debateSelectAtMost"));
      return;
    }
    setSelectedIds((current) => [...current, id]);
    setParticipantDrafts((current) => ({
      ...current,
      [id]: defaultParticipant(),
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
    setFormError(null);
    const topicValidation = validateDebateTopic(topic, outputLanguage);
    if (!topicValidation.valid) {
      setTopicError(
        copy(
          t,
          topicValidation.reason === "required"
            ? "debateTopicRequired"
            : "debateTopicLanguageInvalid",
        ),
      );
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
      <PageIntro
        eyebrow={copy(t, "newDebate")}
        title={copy(t, "newDebateTitle")}
        action={
          <Link className="secondary-action" href="/teacher/debates">
            {copy(t, "debateBack")}
          </Link>
        }
      />
      {error ? <ErrorNotice error={error} onRetry={() => void load()} /> : null}
      <form className={styles.pageStack} onSubmit={submit}>
        <SectionCard title={copy(t, "debateTopic")}>
          <label className="stack-form">
            <span className={styles.srOnly}>{copy(t, "debateTopic")}</span>
            <textarea
              aria-label={copy(t, "debateTopic")}
              aria-describedby={topicError ? "debate-topic-error" : undefined}
              aria-invalid={topicError !== null}
              disabled={busy}
              id="debate-topic"
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
          </label>
        </SectionCard>

        <SectionCard title={copy(t, "debateCandidates")}>
          {candidates.length === 0 ? (
            <EmptyCard title={copy(t, "debateNoCandidates")} />
          ) : (
            <div className={styles.candidateGrid}>
              {candidates.map((candidate) => {
                const selected = selectedIds.includes(candidate.agent.id);
                const order = selectedIds.indexOf(candidate.agent.id);
                return (
                  <button
                    aria-pressed={selected}
                    className={`${styles.candidate} ${selected ? styles.candidateSelected : ""}`}
                    disabled={busy}
                    key={candidate.agent.id}
                    onClick={() => toggleCandidate(candidate)}
                    type="button"
                  >
                    <span className={styles.candidateTop}>
                      <span className={styles.orderMark}>
                        {selected ? String.fromCharCode(65 + order) : "＋"}
                      </span>
                    </span>
                    <span className={styles.candidateName}>
                      {candidate.agent.name}
                    </span>
                    <span className={styles.candidateDescription}>
                      {candidate.agent.description || copy(t, "debateCurrent")}
                    </span>
                    <span className={styles.candidateHint}>
                      {candidate.current_version.version_label} ·{" "}
                      {copy(t, "debateCurrent")}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </SectionCard>

        <SectionCard title={copy(t, "debateSelected")}>
          {selectedCandidates.length ? (
            <div className={styles.selectedList}>
              {selectedCandidates.map((candidate, index) => {
                const id = candidate.agent.id;
                const draft = participantDrafts[id] ?? defaultParticipant();
                return (
                  <div className={styles.selectedRow} key={id}>
                    <div className={styles.selectedIdentity}>
                      <span className={styles.slotMark}>
                        {String.fromCharCode(65 + index)}
                      </span>
                      <div>
                        <strong>{candidate.agent.name}</strong>
                        <small>
                          {interpolate(copy(t, "debateVersionSnapshot"), {
                            version: candidate.current_version.version_label,
                          })}
                        </small>
                      </div>
                    </div>
                    <div className={styles.selectedControls}>
                      <div
                        className={styles.choiceGroup}
                        aria-label={copy(t, "debateStance") as string}
                      >
                        <button
                          aria-pressed={draft.mode === "assigned"}
                          className={`${styles.choice} ${draft.mode === "assigned" ? styles.choiceActive : ""}`}
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
                          className={`${styles.choice} ${draft.mode === "open" ? styles.choiceActive : ""}`}
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
                      ) : (
                        <span className={styles.fieldHint}>
                          {copy(t, "debateOpen")}
                        </span>
                      )}
                      <input
                        aria-label={`${candidate.agent.name} ${copy(t, "debateNote")}`}
                        className={styles.noteInput}
                        disabled={busy}
                        onChange={(event) =>
                          updateParticipant(id, { note: event.target.value })
                        }
                        placeholder={copy(t, "debateNotePlaceholder")}
                        value={draft.note}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          ) : (
            <p className={styles.emptyCopy}>{copy(t, "debateSelectAtLeast")}</p>
          )}
        </SectionCard>

        <SectionCard title={copy(t, "debateMutualLearningRuleSet")}>
          <label className={styles.roundField}>
            <span className={styles.roundLabel}>Language</span>
            <select
              aria-label="Language"
              disabled={busy}
              value={outputLanguage}
              onChange={(event) =>
                setOutputLanguage(event.target.value as "en" | "zh")
              }
            >
              <option value="en">English</option>
              <option value="zh">Chinese</option>
            </select>
          </label>
          <div className={styles.fixedRule}>
            <p
              aria-label={copy(t, "debateRuleSet")}
              className={styles.rulePhases}
              data-testid="debate-rule-set"
            >
              {copy(t, "debateMutualLearningRules")}
            </p>
          </div>
          {formError ? (
            <div className="form-error" role="alert">
              {formError}
            </div>
          ) : null}
          <div className={styles.submitRow}>
            <button
              className="primary-action"
              disabled={busy || candidates.length === 0}
              type="submit"
            >
              {busy ? copy(t, "debateCreating") : copy(t, "debateCreateAction")}
            </button>
          </div>
        </SectionCard>
      </form>
    </div>
  );
}

// Keep the existing name available for the page-level integration point.
