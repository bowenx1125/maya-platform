"use client";

import {
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
} from "react";
import { usePathname, useRouter } from "next/navigation";

import {
  createIdempotencyHandle,
  isAmbiguousMutationFailure,
  type ChatAgent,
  type IdempotencyHandle,
  type PlatformApi,
  type TeamDetailDto,
  type TeamSummaryDto,
  type TeamUpdateRequest,
  type TeamWriteRequest,
} from "../../lib/api";
import { useT } from "../locale";
import { PageAction } from "../page-action";
import { useSession } from "../session-provider";
import styles from "../agent-chat.module.css";

type KnowledgeSetChoice = { id: string; name: string };

type TeamEntryApi = {
  teams(courseId: string): Promise<TeamSummaryDto[]>;
  team(teamId: string): Promise<TeamDetailDto>;
  createTeam(
    courseId: string,
    body: TeamWriteRequest,
    options?: { idempotency: IdempotencyHandle },
  ): Promise<TeamDetailDto>;
  updateTeam(
    teamId: string,
    body: TeamUpdateRequest,
    options?: { idempotency: IdempotencyHandle },
  ): Promise<TeamDetailDto>;
};

type PendingTeamMutation = {
  scopeKey: string;
  handle: IdempotencyHandle;
  body: TeamWriteRequest;
  teamId: string | null;
  expectedRevision: number | null;
};

type FormState = {
  name: string;
  memberVersionIds: string[];
  leaderVersionId: string;
  sharedSetIds: string[];
};

const EMPTY_FORM: FormState = {
  name: "",
  memberVersionIds: [],
  leaderVersionId: "",
  sharedSetIds: [],
};

function teamApi(api: PlatformApi): TeamEntryApi | null {
  const candidate = api as PlatformApi & Partial<TeamEntryApi>;
  return [
    candidate.teams,
    candidate.team,
    candidate.createTeam,
    candidate.updateTeam,
  ].every((method) => typeof method === "function")
    ? (candidate as PlatformApi & TeamEntryApi)
    : null;
}

/**
 * The server publishes a Teacher's public personal Team to the course as a
 * Maya Team; any other Team stays readable only by its owner. The variant
 * therefore fixes visibility instead of offering it as a choice.
 */
export function TeamEntryFlow({
  api,
  courseId,
  agents,
  variant = "team",
  standalone = false,
  backHref,
  initialRouteMode,
  initialTeamId,
  onSaved,
  onCancel,
}: {
  api: PlatformApi;
  courseId: string;
  agents: ChatAgent[];
  variant?: "team" | "maya";
  standalone?: boolean;
  backHref?: string;
  initialRouteMode?: string;
  initialTeamId?: string;
  onSaved?: (team: TeamDetailDto) => void;
  onCancel?: () => void;
}) {
  const t = useT();
  const router = useRouter();
  const pathname = usePathname();
  const { identityGeneration, user } = useSession();
  const apiForTeams = useMemo(() => teamApi(api), [api]);
  const formId = useId();
  const headingId = useId();
  const visibility: TeamWriteRequest["visibility"] =
    variant === "maya" ? "public" : "private";
  const dataScope = `${user?.id ?? "anonymous"}:${identityGeneration}:${courseId}:${variant}`;
  const actionScope = `${dataScope}:${standalone ? pathname : "inline"}:${initialRouteMode ?? ""}:${initialTeamId ?? ""}`;
  const routeOpensForm = !standalone || initialRouteMode === "team-new";
  const dataScopeRef = useRef(dataScope);
  const actionScopeRef = useRef(actionScope);
  const saveSequence = useRef(0);
  const [teams, setTeams] = useState<TeamSummaryDto[]>([]);
  const [knowledgeSets, setKnowledgeSets] = useState<KnowledgeSetChoice[]>([]);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [editing, setEditing] = useState<TeamDetailDto | null>(null);
  const [formRoute, setFormRoute] = useState({
    scopeKey: actionScope,
    open: routeOpensForm,
  });
  const formOpen = formRoute.open;
  const setFormOpen = (open: boolean) =>
    setFormRoute({ scopeKey: actionScope, open });
  const [listLoading, setListLoading] = useState(true);
  const [editLoadingScope, setEditLoadingScope] = useState<string | null>(null);
  const [loadedTeamScope, setLoadedTeamScope] = useState<string | null>(null);
  const [teamListRefreshing, setTeamListRefreshing] = useState(false);
  const [teamListRefreshError, setTeamListRefreshError] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [error, setError] = useState<unknown>(null);
  const requestSeq = useRef(0);
  const pendingMutation = useRef<PendingTeamMutation | null>(null);
  const routedEdit = useRef("");
  const editScope = useRef<string | null>(null);
  const [mutationUnknown, setMutationUnknown] = useState(false);

  if (formRoute.scopeKey !== actionScope) {
    const keepLoadedEdit =
      standalone &&
      initialRouteMode === "team-edit" &&
      editing?.id === initialTeamId &&
      editScope.current === dataScope;
    setFormRoute({ scopeKey: actionScope, open: routeOpensForm });
    if (!keepLoadedEdit) {
      setEditing(null);
      setForm(EMPTY_FORM);
    }
    setLoadError(null);
    setError(null);
  }
  const loading =
    listLoading ||
    editLoadingScope === actionScope ||
    loadedTeamScope !== dataScope;
  const canShowLoadedData = loadedTeamScope === dataScope;
  const visibleTeams = canShowLoadedData
    ? teams.filter(
        (team) =>
          variant !== "maya" ||
          (team.can_edit &&
            team.visibility === "public" &&
            team.ownership_scope === "personal" &&
            team.group_id === null),
      )
    : [];
  const visibleKnowledgeSets = canShowLoadedData ? knowledgeSets : [];

  useLayoutEffect(() => {
    dataScopeRef.current = dataScope;
  }, [dataScope]);

  useLayoutEffect(() => {
    const changed = actionScopeRef.current !== actionScope;
    actionScopeRef.current = actionScope;
    saveSequence.current += 1;
    if (changed) {
      setSaving(false);
      setTeamListRefreshing(false);
      setError(null);
      setMutationUnknown(false);
    }
  }, [actionScope]);

  useEffect(
    () => () => {
      requestSeq.current += 1;
      saveSequence.current += 1;
    },
    [],
  );

  useEffect(() => {
    let active = true;
    const sequence = ++requestSeq.current;
    const requestScope = dataScope;
    const owns = () =>
      active &&
      requestSeq.current === sequence &&
      dataScopeRef.current === requestScope;
    const timer = window.setTimeout(() => {
      setTeams([]);
      setKnowledgeSets([]);
      setLoadError(null);
      setListLoading(true);
      if (!apiForTeams) {
        setLoadError(new Error(t("teamApiNotConnected")));
        setLoadedTeamScope(requestScope);
        setListLoading(false);
        return;
      }
      const knowledgeRequest =
        typeof api.brainformKnowledge === "function"
          ? api.brainformKnowledge(courseId).then((rows) => {
              const seen = new Set<string>();
              return rows.flatMap((row) => {
                if (seen.has(row.canonical_set_id)) return [];
                seen.add(row.canonical_set_id);
                return [
                  {
                    id: row.canonical_set_id,
                    name: row.knowledge_display_name,
                  },
                ];
              });
            })
          : api
              .knowledgeSets(courseId)
              .then((sets) =>
                sets.map((set) => ({ id: set.id, name: set.display_name })),
              );
      void Promise.all([
        standalone ? apiForTeams.teams(courseId) : Promise.resolve([]),
        knowledgeRequest,
      ])
        .then(([teamList, sets]) => {
          if (!owns()) return;
          setTeams(teamList);
          setKnowledgeSets(sets);
          setLoadedTeamScope(requestScope);
        })
        .catch((cause) => {
          if (!owns()) return;
          setLoadError(cause);
          setLoadedTeamScope(requestScope);
        })
        .finally(() => {
          if (owns()) setListLoading(false);
        });
    }, 0);
    return () => {
      active = false;
      window.clearTimeout(timer);
      if (requestSeq.current === sequence) requestSeq.current += 1;
    };
    // `t` only formats the not-connected message and must not reload data.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, apiForTeams, courseId, dataScope, standalone]);

  useEffect(() => {
    if (!standalone || initialRouteMode !== "team-edit") {
      routedEdit.current = "";
      return;
    }
    if (!initialTeamId || loading) return;
    const key = `${user?.id ?? "anonymous"}:${identityGeneration}:${courseId}:${initialTeamId}`;
    if (routedEdit.current === key) return;
    routedEdit.current = key;
    const timer = window.setTimeout(() => void editTeam(initialTeamId), 0);
    return () => window.clearTimeout(timer);
    // editTeam is declared below and only reads this component's current props.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    courseId,
    identityGeneration,
    initialRouteMode,
    initialTeamId,
    loading,
    standalone,
    user?.id,
  ]);

  function syncManageRoute(modeValue: string, teamId?: string) {
    if (!standalone || typeof window === "undefined") return;
    // Studyform keeps Maya Team and private Team on different query modes.
    // Writing the shared internal name back would reopen the other form.
    const nextMode =
      variant === "maya" && modeValue === "team-edit"
        ? "maya-edit"
        : variant === "maya" && modeValue === "team-new"
          ? "maya-new"
          : modeValue;
    const params = new URLSearchParams(window.location.search);
    const sameTeam = teamId
      ? params.get("team_id") === teamId
      : !params.get("team_id");
    if (params.get("mode") === nextMode && sameTeam) return;
    params.set("mode", nextMode);
    if (teamId) params.set("team_id", teamId);
    else params.delete("team_id");
    const query = params.toString();
    router.push(`${pathname}${query ? `?${query}` : ""}`, { scroll: false });
  }

  async function refreshTeamList() {
    if (!apiForTeams) return;
    const scopeKey = actionScopeRef.current;
    const sequence = ++requestSeq.current;
    setTeamListRefreshing(true);
    setTeamListRefreshError(false);
    try {
      const teamList = await apiForTeams.teams(courseId);
      if (
        requestSeq.current !== sequence ||
        actionScopeRef.current !== scopeKey
      )
        return;
      setTeams(teamList);
    } catch {
      if (
        requestSeq.current === sequence &&
        actionScopeRef.current === scopeKey
      )
        setTeamListRefreshError(true);
    } finally {
      if (
        requestSeq.current === sequence &&
        actionScopeRef.current === scopeKey
      )
        setTeamListRefreshing(false);
    }
  }

  function closeForm() {
    setEditing(null);
    setFormOpen(false);
    setForm(EMPTY_FORM);
    setLoadError(null);
    setError(null);
    setSaved(false);
    syncManageRoute("teams");
  }

  async function editTeam(teamId: string) {
    if (!apiForTeams || mutationUnknown) return;
    if (standalone)
      routedEdit.current = `${user?.id ?? "anonymous"}:${identityGeneration}:${courseId}:${teamId}`;
    const scopeKey = actionScopeRef.current;
    const sequence = ++requestSeq.current;
    setEditLoadingScope(scopeKey);
    setLoadError(null);
    try {
      const detail = await apiForTeams.team(teamId);
      if (
        requestSeq.current !== sequence ||
        actionScopeRef.current !== scopeKey
      )
        return;
      if (!detail.can_edit) throw new Error(t("teamNotEditable"));
      editScope.current = dataScope;
      setEditing(detail);
      const memberIds = [...detail.members]
        .sort((left, right) => left.position - right.position)
        .map((member) => member.agent_version_id);
      setForm({
        name: detail.display_name,
        memberVersionIds: memberIds,
        leaderVersionId:
          detail.members.find((member) => member.is_leader)?.agent_version_id ??
          "",
        sharedSetIds: detail.shared_knowledge_set_ids,
      });
      setFormOpen(true);
      setSaved(false);
      syncManageRoute("team-edit", teamId);
    } catch (cause) {
      if (
        requestSeq.current === sequence &&
        actionScopeRef.current === scopeKey
      )
        setLoadError(cause);
    } finally {
      if (
        requestSeq.current === sequence &&
        actionScopeRef.current === scopeKey
      )
        setEditLoadingScope(null);
    }
  }

  function toggleMember(versionId: string) {
    setForm((current) => {
      const selected = current.memberVersionIds.includes(versionId);
      const memberVersionIds = selected
        ? current.memberVersionIds.filter((id) => id !== versionId)
        : [...current.memberVersionIds, versionId];
      return {
        ...current,
        memberVersionIds,
        leaderVersionId:
          selected && current.leaderVersionId === versionId
            ? ""
            : current.leaderVersionId,
      };
    });
  }

  async function saveTeam(event: FormEvent) {
    event.preventDefault();
    if (!apiForTeams || saving) return;
    const intentScope = actionScopeRef.current;
    const sequence = ++saveSequence.current;
    const isCurrentIntent = () =>
      actionScopeRef.current === intentScope &&
      saveSequence.current === sequence;
    const pending =
      pendingMutation.current?.scopeKey === intentScope
        ? pendingMutation.current
        : {
            scopeKey: intentScope,
            handle: createIdempotencyHandle(),
            body: {
              display_name: form.name.trim(),
              group_id: null,
              visibility,
              members: form.memberVersionIds.map(
                (agent_version_id, position) => ({
                  agent_version_id,
                  is_leader: agent_version_id === form.leaderVersionId,
                  position,
                }),
              ),
              shared_knowledge_set_ids: form.sharedSetIds,
            },
            teamId: editing?.id ?? null,
            expectedRevision: editing?.metadata_revision ?? null,
          };
    pendingMutation.current = pending;
    setSaving(true);
    setError(null);
    setSaved(false);
    let savedTeam: TeamDetailDto;
    try {
      if (pending.teamId && pending.expectedRevision !== null) {
        savedTeam = await apiForTeams.updateTeam(
          pending.teamId,
          {
            display_name: pending.body.display_name,
            visibility: pending.body.visibility,
            members: pending.body.members,
            shared_knowledge_set_ids: pending.body.shared_knowledge_set_ids,
            expected_metadata_revision: pending.expectedRevision,
          },
          { idempotency: pending.handle },
        );
      } else {
        savedTeam = await apiForTeams.createTeam(courseId, pending.body, {
          idempotency: pending.handle,
        });
      }
    } catch (cause) {
      if (!isCurrentIntent()) {
        if (
          !isAmbiguousMutationFailure(cause) &&
          pendingMutation.current === pending
        )
          pendingMutation.current = null;
        return;
      }
      setError(cause);
      if (isAmbiguousMutationFailure(cause)) {
        setMutationUnknown(true);
      } else {
        pendingMutation.current = null;
      }
      setSaving(false);
      return;
    }
    if (pendingMutation.current === pending) pendingMutation.current = null;
    if (!isCurrentIntent()) return;
    setSaving(false);
    setMutationUnknown(false);
    setError(null);
    setEditing(null);
    setForm(EMPTY_FORM);
    if (!standalone) {
      onSaved?.(savedTeam);
      return;
    }
    // Leave the form directly. A version list between Done and Studyform
    // only flashes the version that was just saved.
    setSaved(true);
    syncManageRoute("teams");
    onSaved?.(savedTeam);
  }

  const formErrors = !form.name.trim()
    ? t("teamNameRequired")
    : form.memberVersionIds.length < 2
      ? t("teamNeedsTwoMembers")
      : !form.leaderVersionId
        ? t("teamChooseLeader")
        : "";
  const title = variant === "maya" ? t("mayaTeams") : t("chatTargetTeams");

  return (
    <section className={styles.entryFlow} aria-labelledby={headingId}>
      <div className={styles.entryHeading}>
        <div>
          <h2 id={headingId}>{title}</h2>
        </div>
      </div>

      <div className={styles.entrySection}>
        {loading ? <p role="status">{t("loading")}</p> : null}
        {loadError ? (
          <p role="alert" className={styles.entryError}>
            {apiForTeams ? t("teamLoadFailed") : t("teamApiNotConnected")}
          </p>
        ) : null}
        {standalone && !formOpen && visibleTeams.length ? (
          <ul className={styles.entryTeamList} aria-label={title}>
            {visibleTeams.map((team) => (
              <li key={team.id}>
                <button
                  className="text-link"
                  type="button"
                  disabled={loading || mutationUnknown}
                  onClick={() => void editTeam(team.id)}
                >
                  {team.display_name}
                </button>
                <small>
                  {t("teamVersionLabel", { seq: team.current_version_seq })}
                </small>
              </li>
            ))}
          </ul>
        ) : null}
        {standalone &&
        !formOpen &&
        !loading &&
        !loadError &&
        !visibleTeams.length ? (
          <p className={styles.entryHint}>{t("mayaTeamNoneYet")}</p>
        ) : null}

        {saved ? (
          <p role="status" className={styles.entryNotice}>
            {variant === "maya"
              ? t("mayaTeamPublished")
              : t("teamSavedWaitingForChat")}
          </p>
        ) : null}
        {teamListRefreshError ? (
          <div className={styles.entryError}>
            <p role="status">{t("teamListRefreshFailed")}</p>
            <button
              className="inline-button"
              type="button"
              disabled={teamListRefreshing}
              onClick={() => void refreshTeamList()}
            >
              {teamListRefreshing ? t("loading") : t("retryTeamList")}
            </button>
          </div>
        ) : null}

        {!loading && apiForTeams && (editing || formOpen) ? (
          <form
            id={formId}
            className={styles.teamForm}
            onSubmit={(event) => void saveTeam(event)}
          >
            <label>
              {t("teamName")}
              <input
                value={form.name}
                maxLength={120}
                disabled={saving || mutationUnknown}
                onChange={(event) =>
                  setForm((current) => ({
                    ...current,
                    name: event.target.value,
                  }))
                }
                required
              />
            </label>
            <fieldset>
              <legend
                data-ui-guide="chat.teamMembers"
                data-ui-guide-text={t("teamMembersHelp")}
                tabIndex={0}
              >
                {t("teamMembers")}
              </legend>
              <div className={styles.entryMemberList}>
                {agents.map((agent) => {
                  const checked = form.memberVersionIds.includes(
                    agent.version_id,
                  );
                  return (
                    <div className={styles.entryMember} key={agent.version_id}>
                      <label className={styles.entryChoice}>
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={
                            agent.available === false ||
                            saving ||
                            mutationUnknown
                          }
                          onChange={() => toggleMember(agent.version_id)}
                        />
                        <span>
                          {agent.name} · {agent.version_label}
                        </span>
                      </label>
                      <label className={styles.entryChoice}>
                        <input
                          type="radio"
                          name={`${formId}-leader`}
                          aria-label={t("teamSetLeader", {
                            name: agent.name,
                          })}
                          checked={form.leaderVersionId === agent.version_id}
                          disabled={!checked || saving || mutationUnknown}
                          onChange={() =>
                            setForm((current) => ({
                              ...current,
                              leaderVersionId: agent.version_id,
                            }))
                          }
                        />
                        <span>{t("leader")}</span>
                      </label>
                    </div>
                  );
                })}
              </div>
            </fieldset>
            <fieldset>
              <legend
                data-ui-guide="chat.teamSharedKnowledge"
                data-ui-guide-text={t("teamSharedKnowledgeHelp")}
                tabIndex={0}
              >
                {t("teamSharedKnowledge")}
              </legend>
              {visibleKnowledgeSets.length ? (
                visibleKnowledgeSets.map((set) => (
                  <label className={styles.entryChoice} key={set.id}>
                    <input
                      type="checkbox"
                      checked={form.sharedSetIds.includes(set.id)}
                      disabled={saving || mutationUnknown}
                      onChange={() =>
                        setForm((current) => ({
                          ...current,
                          sharedSetIds: current.sharedSetIds.includes(set.id)
                            ? current.sharedSetIds.filter((id) => id !== set.id)
                            : [...current.sharedSetIds, set.id],
                        }))
                      }
                    />
                    <span>{set.name}</span>
                  </label>
                ))
              ) : (
                <p>{t("teamNoSharedKnowledge")}</p>
              )}
            </fieldset>
            {error ? (
              <p role="alert" className={styles.entryError}>
                {mutationUnknown ? t("teamSaveUnknown") : t("teamSaveFailed")}
              </p>
            ) : null}
            <PageAction
              name="done"
              form={formId}
              disabled={saving || (!mutationUnknown && Boolean(formErrors))}
            />
            {formErrors ? (
              <p className={styles.entryHint}>{formErrors}</p>
            ) : null}
          </form>
        ) : null}
        {formOpen ? (
          <PageAction
            name="back"
            disabled={saving || mutationUnknown}
            onClick={standalone ? closeForm : onCancel}
          />
        ) : standalone && backHref ? (
          <PageAction name="back" href={backHref} />
        ) : null}
      </div>
    </section>
  );
}
