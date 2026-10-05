"use client";

import {
  Fragment,
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import type {
  ProviderDataCallDisclosureResponse,
  TeamDetailDto,
  TeamStandingGrantConfirmation,
  TeamStandingGrantPreview,
  TeamStandingGrantRequest,
} from "../../lib/api";
import { useSession } from "../session-provider";
import { PageIntro, SectionCard } from "../ui";
import { ProviderDataCallDisclosure } from "./provider-data-call-disclosure";
import styles from "./provider-chat-approvals.module.css";

const TEAM_CHAT_OPERATION = "llm_agent_chat" as const;
const TEAM_EMBEDDING_OPERATION = "embedding_query" as const;
type TeamStandingOperation = TeamStandingGrantRequest["provider_operation"];

type PublishedTeacherTeam = Pick<
  TeamDetailDto,
  "id" | "display_name" | "current_version_id"
>;

export function TeacherChatProviderApprovalsPage({
  courseId,
}: {
  courseId: string;
}) {
  const { identityGeneration, user } = useSession();
  const actorScopeKey = `${user?.id ?? "anonymous"}:${identityGeneration}:${courseId}`;
  return (
    <TeacherChatProviderApprovalsPageForScope
      key={actorScopeKey}
      actorScopeKey={actorScopeKey}
      actorUserId={user?.id ?? null}
      courseId={courseId}
    />
  );
}

function TeacherChatProviderApprovalsPageForScope({
  actorScopeKey,
  actorUserId,
  courseId,
}: {
  actorScopeKey: string;
  actorUserId: string | null;
  courseId: string;
}) {
  const { api } = useSession();
  const [disclosure, setDisclosure] =
    useState<ProviderDataCallDisclosureResponse | null>(null);
  const [embeddingDisclosure, setEmbeddingDisclosure] =
    useState<ProviderDataCallDisclosureResponse | null>(null);
  const [teams, setTeams] = useState<PublishedTeacherTeam[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const requestSequence = useRef(0);
  const activeScope = useRef(actorScopeKey);
  const courseDisclosureScopeKey = disclosure
    ? `${actorScopeKey}:${disclosure.policy_hash}:${disclosure.manifest_hash}:${disclosure.confirmation_revision}`
    : `${actorScopeKey}:course-disclosure-loading`;

  useLayoutEffect(() => {
    activeScope.current = actorScopeKey;
    requestSequence.current += 1;
    return () => {
      activeScope.current = "";
      requestSequence.current += 1;
    };
  }, [actorScopeKey, api]);

  const disclosureController = useMemo(
    () => ({
      load: () => api.getChatStandingProviderDisclosure(courseId),
      confirm: (request: {
        policy_hash: string;
        manifest_hash: string;
        expected_revision: number;
      }) => api.confirmProviderDataCallDisclosure(request),
    }),
    [api, courseId],
  );
  const embeddingDisclosureController = useMemo(
    () => ({
      load: async () => {
        if (!embeddingDisclosure) throw new Error("Disclosure is unavailable.");
        return embeddingDisclosure;
      },
      confirm: (request: {
        policy_hash: string;
        manifest_hash: string;
        expected_revision: number;
      }) => api.confirmProviderDataCallDisclosure(request),
    }),
    [api, embeddingDisclosure],
  );

  const load = useCallback(async () => {
    const requestId = ++requestSequence.current;
    const isCurrent = () =>
      requestSequence.current === requestId &&
      activeScope.current === actorScopeKey;
    setLoading(true);
    setError(null);
    setDisclosure(null);
    setEmbeddingDisclosure(null);
    setTeams([]);
    if (!courseId) {
      if (isCurrent()) {
        setError(new Error("A course is required."));
        setLoading(false);
      }
      return;
    }
    try {
      const [currentDisclosure, currentEmbeddingDisclosure, summaries] =
        await Promise.all([
          api.getChatStandingProviderDisclosure(courseId),
          api.getChatStandingProviderDisclosure(
            courseId,
            TEAM_EMBEDDING_OPERATION,
          ),
          api.teams(courseId),
        ]);
      if (!isCurrent()) return;
      setDisclosure(currentDisclosure);
      setEmbeddingDisclosure(currentEmbeddingDisclosure);
      const candidates = summaries.filter(
        (team) =>
          team.can_edit &&
          team.owner_user_id === actorUserId &&
          team.ownership_scope === "personal" &&
          team.visibility === "public",
      );
      const details = await Promise.all(
        candidates.map(async (team) => {
          try {
            return await api.team(team.id);
          } catch {
            return null;
          }
        }),
      );
      if (!isCurrent()) return;
      setTeams(
        details
          .filter(
            (team): team is TeamDetailDto =>
              team !== null &&
              team.owner_user_id === actorUserId &&
              team.publication_state === "published" &&
              team.ownership_scope === "personal" &&
              team.visibility === "public",
          )
          .map((team) => ({
            id: team.id,
            display_name: team.display_name,
            current_version_id: team.current_version_id,
          })),
      );
    } catch (cause) {
      if (isCurrent()) setError(cause);
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, [actorScopeKey, actorUserId, api, courseId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  return (
    <div className={styles.page}>
      <PageIntro title="Chat Provider disclosure" />
      <SectionCard
        title="Course Chat disclosure"
        description={`Course scope: ${courseId || "unavailable"}`}
      >
        <p className={styles.notice}>
          This confirmation binds the course disclosure to the displayed policy,
          manifest and revision. It does not expose or count student messages.
        </p>
        <ProviderDataCallDisclosure
          key={courseDisclosureScopeKey}
          controller={disclosureController}
          scopeKey={courseDisclosureScopeKey}
          existingDisclosure={disclosure}
          existingDisclosureError={error}
          onRetry={() => void load()}
        />
      </SectionCard>

      {embeddingDisclosure ? (
        <SectionCard
          title="Course retrieval disclosure"
          description={`Course scope: ${courseId || "unavailable"}`}
        >
          <ProviderDataCallDisclosure
            key={`${actorScopeKey}:embedding:${embeddingDisclosure.policy_hash}:${embeddingDisclosure.manifest_hash}:${embeddingDisclosure.confirmation_revision}`}
            controller={embeddingDisclosureController}
            scopeKey={`${actorScopeKey}:embedding:${embeddingDisclosure.policy_hash}:${embeddingDisclosure.manifest_hash}:${embeddingDisclosure.confirmation_revision}`}
            existingDisclosure={embeddingDisclosure}
            existingDisclosureError={error}
            onRetry={() => void load()}
          />
        </SectionCard>
      ) : null}

      <SectionCard
        title="Published Team Provider resources"
        description="Review and confirm the exact current resource binding for each published Team you own. Existing grants stay limited to their confirmed version and policy."
      >
        {loading ? (
          <p className={styles.notice}>Loading published Teams…</p>
        ) : null}
        {error ? (
          <div>
            <p className={styles.error} role="alert">
              The course disclosure and published Teams could not be loaded.
            </p>
            <button
              className={styles.retry}
              type="button"
              onClick={() => void load()}
            >
              Try again
            </button>
          </div>
        ) : null}
        {!loading && !error && teams.length === 0 ? (
          <p className={styles.empty}>
            No published Team owned by this Teacher is available in this course.
          </p>
        ) : null}
        {disclosure && embeddingDisclosure && teams.length > 0 ? (
          <div className={styles.teams}>
            {teams.map((team) => (
              <Fragment key={`${actorScopeKey}:${team.current_version_id}`}>
                <TeamStandingGrant
                  key={`${team.current_version_id}:${disclosure.policy_hash}:${TEAM_CHAT_OPERATION}`}
                  teamName={team.display_name}
                  teamVersionId={team.current_version_id}
                  policyHash={disclosure.policy_hash}
                  providerOperation={TEAM_CHAT_OPERATION}
                  operationLabel="Chat reply"
                />
                <TeamStandingGrant
                  key={`${team.current_version_id}:${embeddingDisclosure.policy_hash}:${TEAM_EMBEDDING_OPERATION}`}
                  teamName={team.display_name}
                  teamVersionId={team.current_version_id}
                  policyHash={embeddingDisclosure.policy_hash}
                  providerOperation={TEAM_EMBEDDING_OPERATION}
                  operationLabel="Knowledge retrieval"
                />
              </Fragment>
            ))}
          </div>
        ) : null}
      </SectionCard>
    </div>
  );
}

function TeamStandingGrant({
  teamName,
  teamVersionId,
  policyHash,
  providerOperation,
  operationLabel,
}: {
  teamName: string;
  teamVersionId: string;
  policyHash: string;
  providerOperation: TeamStandingOperation;
  operationLabel: string;
}) {
  const { api } = useSession();
  const [preview, setPreview] = useState<TeamStandingGrantPreview | null>(null);
  const [confirmation, setConfirmation] =
    useState<TeamStandingGrantConfirmation | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const requestSequence = useRef(0);
  const mounted = useRef(true);

  useLayoutEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      requestSequence.current += 1;
    };
  }, []);

  const load = useCallback(async () => {
    const requestId = ++requestSequence.current;
    const isCurrent = () =>
      mounted.current && requestSequence.current === requestId;
    setLoading(true);
    setError(null);
    setConfirmation(null);
    try {
      const next = await api.previewTeamProviderStandingGrant({
        team_version_id: teamVersionId,
        provider_operation: providerOperation,
        policy_hash: policyHash,
      });
      if (!isCurrent()) return;
      setPreview(next);
    } catch (cause) {
      if (!isCurrent()) return;
      setPreview(null);
      setError(cause);
    } finally {
      if (isCurrent()) setLoading(false);
    }
  }, [api, policyHash, providerOperation, teamVersionId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function confirm() {
    if (!preview || busy) return;
    const requestId = ++requestSequence.current;
    const isCurrent = () =>
      mounted.current && requestSequence.current === requestId;
    setBusy(true);
    setError(null);
    try {
      const result = await api.confirmTeamProviderStandingGrant({
        team_version_id: preview.team_version_id,
        provider_operation: providerOperation,
        policy_hash: preview.policy_hash,
        expected_resource_hash: preview.resource_hash,
        expected_team_epoch: preview.team_epoch,
        expected_publication_epoch: preview.publication_epoch,
      });
      if (!isCurrent()) return;
      setConfirmation(result);
    } catch (cause) {
      if (!isCurrent()) return;
      setError(cause);
    } finally {
      if (isCurrent()) setBusy(false);
    }
  }

  return (
    <section
      className={styles.team}
      aria-label={`${teamName} Provider binding`}
    >
      <div className={styles.teamHeader}>
        <h3>
          {teamName} · {operationLabel}
        </h3>
        <p>Team version: {teamVersionId}</p>
      </div>
      {loading ? (
        <p className={styles.notice}>Preparing exact resource binding…</p>
      ) : null}
      {preview ? (
        <>
          <dl className={styles.binding}>
            <dt>Policy hash</dt>
            <dd>{preview.policy_hash}</dd>
            <dt>Resource hash</dt>
            <dd>{preview.resource_hash}</dd>
            <dt>Team epoch</dt>
            <dd>{preview.team_epoch}</dd>
            <dt>Publication epoch</dt>
            <dd>{preview.publication_epoch}</dd>
          </dl>
          {confirmation ? (
            <p className={styles.result} role="status">
              Confirmed for this exact Team resource binding at{" "}
              {confirmation.confirmed_at}.
            </p>
          ) : null}
          <button
            className={styles.confirm}
            type="button"
            disabled={busy || loading || confirmation !== null}
            onClick={() => void confirm()}
          >
            {busy ? "Confirming…" : `Confirm ${operationLabel} resources`}
          </button>
        </>
      ) : null}
      {error ? (
        <div>
          <p className={styles.error} role="alert">
            {preview
              ? "The Team binding could not be confirmed. Review the current binding and retry."
              : "The Team resource binding is unavailable."}
          </p>
          <button
            className={styles.retry}
            type="button"
            disabled={loading || busy}
            onClick={() => void load()}
          >
            Refresh binding
          </button>
        </div>
      ) : null}
    </section>
  );
}
