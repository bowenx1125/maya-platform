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
import type { MessageKey } from "../../../lib/i18n";
import { validateDebateTopic } from "../../../lib/debate-topic";
import { useT } from "../../locale";
import { useSession } from "../../session-provider";
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

  const load = useCallback(async () => {
    if (!courseId) {
      setError(new Error(t("debateCreateUnavailable")));
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const next = controller
        ? await controller.load(courseId)
        : await api.debates(courseId);
      setDebates(next);
    } catch (cause) {
      setError(cause);
    } finally {
      setLoading(false);
    }
  }, [api, controller, courseId, t]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  if (loading) return <LoadingCard />;
  if (error) return <ErrorNotice error={error} onRetry={() => void load()} />;

  return (
    <div className={styles.pageStack}>
      <PageIntro
        eyebrow={t("debateList")}
        title={t("debateList")}
        description={t("debateListLede")}
        action={
          <Link className="primary-action" href="/teacher/debates/new">
            {t("newDebate")}
          </Link>
        }
      />
      <SectionCard
        title={t("debateList")}
        description={t("debateSelectCount", { count: debates.length })}
      >
        {debates.length === 0 ? (
          <div className={styles.emptyState}>
            <strong>{t("debateNoDebates")}</strong>
            <p className={styles.emptyCopy}>{t("newDebateLede")}</p>
            <Link className="secondary-action" href="/teacher/debates/new">
              {t("newDebate")}
            </Link>
          </div>
        ) : (
          <div className={styles.list}>
            {debates.map((debate) => (
              <Link
                className={styles.debateCard}
                href={`/teacher/debates/${debate.id}/control`}
                key={debate.id}
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
                <StatusBadge status={debate.status} />
              </Link>
            ))}
          </div>
        )}
      </SectionCard>
    </div>
  );
}

type StanceValue = "support" | "oppose" | "neutral";
// A new Debate is always ordered multi-expert mutual learning. The legacy demo
// RuleSets remain readable on existing Debates but can no longer be created.
type DebateRuleSetId = "ordered_multi_expert_mutual_learning_v1";
type MutualRoundCount = 2 | 3 | 4 | 5;
type SetupDraftPayload = Omit<
  DebateDraftRequest,
  "round_count" | "rule_set_id"
> & {
  round_count: MutualRoundCount;
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
  const ruleSetId: DebateRuleSetId = "ordered_multi_expert_mutual_learning_v1";
  const [roundCount, setRoundCount] = useState<MutualRoundCount>(2);
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
    const topicValidation = validateDebateTopic(topic);
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
      participants: selectedIds.map((agentId) => {
        const draft = participantDrafts[agentId] ?? defaultParticipant();
        return {
          agent_id: agentId,
          stance_mode: draft.mode,
          assigned_stance: draft.mode === "assigned" ? draft.stance : null,
          teacher_note: draft.note,
        };
      }),
      round_count:
        ruleSetId === "ordered_multi_expert_mutual_learning_v1"
          ? roundCount
          : 2,
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
        description={copy(t, "newDebateLede")}
        action={
          <Link className="secondary-action" href="/teacher/debates">
            {copy(t, "debateBack")}
          </Link>
        }
      />
      {error ? <ErrorNotice error={error} onRetry={() => void load()} /> : null}
      <form className={styles.pageStack} onSubmit={submit}>
        <SectionCard
          title={copy(t, "debateTopic")}
          description={copy(t, "debateTopicPlaceholder")}
        >
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

        <SectionCard
          title={copy(t, "debateCandidates")}
          description={copy(t, "debateCandidatesLede")}
        >
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
                      <StatusBadge status={candidate.agent.status} />
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

        <SectionCard
          title={copy(t, "debateSelected")}
          description={copy(t, "debateSelectedLede")}
        >
          <div className={styles.selectedSummary}>
            <span className={styles.summaryPill}>
              {interpolate(copy(t, "debateSelectCount"), {
                count: selectedCandidates.length,
              })}
            </span>
            <span className={styles.fixedPill}>{copy(t, "debateRounds")}</span>
          </div>
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

        <SectionCard title={copy(t, "debateRuleSet")}>
          <div className={styles.fixedRule}>
            <p
              aria-label={copy(t, "debateRuleSet")}
              data-testid="debate-rule-set"
            >
              {copy(t, "debateMutualLearningRuleSet")}
            </p>
            <strong>
              {ruleSetId === "ordered_multi_expert_mutual_learning_v1"
                ? copy(t, "debateMutualLearningRules")
                : copy(t, "debateFixedRulesLede")}
            </strong>
            {ruleSetId === "ordered_multi_expert_mutual_learning_v1" ? (
              // Label, control, hint - the shape every other field in this
              // form uses. The chosen value used to be repeated in a line
              // below the select, which said nothing the control did not, and
              // the label reached for a global utility class inside a module.
              <label className={styles.roundField}>
                <span className={styles.roundLabel}>
                  {copy(t, "debateRoundCount")}
                </span>
                <select
                  aria-label={copy(t, "debateRoundCount")}
                  disabled={busy}
                  onChange={(event) =>
                    setRoundCount(
                      Number(event.target.value) as MutualRoundCount,
                    )
                  }
                  value={roundCount}
                >
                  {[2, 3, 4, 5].map((value) => (
                    <option key={value} value={value}>
                      {copy(t, "debateRoundOption").replace(
                        "{count}",
                        String(value),
                      )}
                    </option>
                  ))}
                </select>
                <span className={styles.fieldHint}>
                  {copy(t, "debateRoundCountHint").replace(
                    "{turns}",
                    String(selectedIds.length * roundCount),
                  )}
                </span>
              </label>
            ) : (
              <span className={styles.fieldHint}>{copy(t, "debateFlow")}</span>
            )}
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
            <span className={styles.fieldHint}>
              {copy(t, "debateSelectedLede")}
            </span>
          </div>
        </SectionCard>
      </form>
    </div>
  );
}

// Keep the existing name available for the page-level integration point.
