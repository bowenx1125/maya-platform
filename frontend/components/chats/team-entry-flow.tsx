"use client";
import { PRESS_MOTION } from "../ui/button";

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
  PlatformApiError,
  type ChatAgent,
  type IdempotencyHandle,
  type PlatformApi,
  type TeamDetailDto,
  type TeamSummaryDto,
  type TeamUpdateRequest,
  type TeamWriteRequest,
} from "../../lib/api";
import { localizeError } from "../../lib/i18n";
import { useT } from "../../lib/i18n";
import { PageAction } from "../page-action";
import { PageBanner } from "../page-banner";
import { teamVersionLabel } from "../studyform-layout";
import { useSession } from "../session-provider";
import {
  LoadingCard,
  Notice,
  RetryPill,
  SectionCard,
  StickerBadge,
} from "../ui";
import { cn } from "../../lib/utils";
import {
  clearTeamDraft,
  readTeamDraft,
  teamDraftKey,
  writeTeamDraft,
} from "../../lib/team-return";
import { AGENT_PAGE } from "../agent-chrome";
import { MascotFigure } from "../academy/mascots";
import { agentMascot } from "../ui/agent-card";
import { WorkspaceIcon } from "../workspace-icon";
import Link from "next/link";
import styles from "../agent-chat.module.css";
import { celebrate } from "../../lib/confetti";

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
  visibility: "private" | "public";
  memberVersionIds: string[];
  leaderVersionId: string;
  sharedSetIds: string[];
};

const EMPTY_FORM: FormState = {
  name: "",
  visibility: "private",
  memberVersionIds: [],
  leaderVersionId: "",
  sharedSetIds: [],
};

function sameIds(left: string[], right: string[]) {
  return (
    left.length === right.length &&
    [...left].sort().every((id, index) => id === [...right].sort()[index])
  );
}

function sameTeamForm(left: FormState, right: FormState) {
  return (
    left.name === right.name &&
    left.visibility === right.visibility &&
    left.leaderVersionId === right.leaderVersionId &&
    sameIds(left.memberVersionIds, right.memberVersionIds) &&
    sameIds(left.sharedSetIds, right.sharedSetIds)
  );
}

// A public Team's roster is visible to others, so it may hold only public
// Agents; switching to Public drops any private member already chosen.
function withTeamVisibility(
  form: FormState,
  visibility: FormState["visibility"],
  agents: ChatAgent[],
): FormState {
  if (visibility === "private") return { ...form, visibility };
  const privateIds = new Set(
    agents
      .filter((agent) => agent.visibility === "private")
      .map((agent) => agent.version_id),
  );
  return {
    ...form,
    visibility,
    memberVersionIds: form.memberVersionIds.filter((id) => !privateIds.has(id)),
    leaderVersionId: privateIds.has(form.leaderVersionId)
      ? ""
      : form.leaderVersionId,
  };
}

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
 * Private or Public is chosen only while creating a Team. Afterwards the
 * form keeps that choice, and a reader who is not the owner sees the saved
 * members, Leader and Brainform names without being able to change them.
 */
export function TeamEntryFlow({
  api,
  courseId,
  agents,
  variant = "team",
  groupId = null,
  standalone = false,
  backHref,
  agentCreateHref,
  initialRouteMode,
  initialTeamId,
  onSaved,
  onCancel,
}: {
  api: PlatformApi;
  courseId: string;
  agents: ChatAgent[];
  variant?: "team" | "maya";
  groupId?: string | null;
  standalone?: boolean;
  backHref?: string;
  /** Create Agent page for the empty Members board ("Agents" button). */
  agentCreateHref?: string;
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
  const dataScope = `${user?.id ?? "anonymous"}:${identityGeneration}:${courseId}:${variant}`;
  const actionScope = `${dataScope}:${standalone ? pathname : "inline"}:${initialRouteMode ?? ""}:${initialTeamId ?? ""}`;
  const routeOpensForm = !standalone || initialRouteMode === "team-new";
  const dataScopeRef = useRef(dataScope);
  const actionScopeRef = useRef(actionScope);
  const saveSequence = useRef(0);
  const [teams, setTeams] = useState<TeamSummaryDto[]>([]);
  const [knowledgeSets, setKnowledgeSets] = useState<KnowledgeSetChoice[]>([]);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  // Snapshot of the form as loaded for edit; Done stays off until it differs,
  // matching Agent publishOnDone. Create keeps Done clickable for validation.
  const [baselineForm, setBaselineForm] = useState<FormState | null>(null);
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
  // Shown only after Done; empty-name and member rules stay quiet until then.
  const [submitHint, setSubmitHint] = useState("");
  // Closing a notice hides that one failure; the next one shows again.
  const [dismissedError, setDismissedError] = useState<unknown>(null);
  const requestSeq = useRef(0);
  const pendingMutation = useRef<PendingTeamMutation | null>(null);
  const routedEdit = useRef("");
  const editScope = useRef<string | null>(null);
  const [mutationUnknown, setMutationUnknown] = useState(false);
  // A Team form left for Create Agent (empty Members board) comes back here.
  const draftKey = teamDraftKey(groupId ?? courseId, initialTeamId ?? null);
  const restoredDraft = useRef("");

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
      setBaselineForm(null);
    }
    setLoadError(null);
    setError(null);
    setSubmitHint("");
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

  useEffect(() => {
    if (!standalone || loading) return;
    const ready =
      initialRouteMode === "team-edit"
        ? Boolean(initialTeamId) && editing?.id === initialTeamId
        : formOpen;
    const key = `${dataScope}:${draftKey}`;
    if (!ready || restoredDraft.current === key) return;
    restoredDraft.current = key;
    const draft = readTeamDraft(draftKey);
    if (!draft) return;
    const timer = window.setTimeout(
      () =>
        setForm({
          ...draft,
          visibility: editing ? editing.visibility : draft.visibility,
        }),
      0,
    );
    return () => window.clearTimeout(timer);
  }, [
    dataScope,
    draftKey,
    editing,
    formOpen,
    initialRouteMode,
    initialTeamId,
    loading,
    standalone,
  ]);

  function syncManageRoute(modeValue: string, teamId?: string) {
    if (!standalone || typeof window === "undefined") return;
    // Older Maya Team links still open this same form.
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
    if (standalone) clearTeamDraft(draftKey);
    setEditing(null);
    setFormOpen(false);
    setForm(EMPTY_FORM);
    setBaselineForm(null);
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
      editScope.current = dataScope;
      setEditing(detail);
      // A member Agent published again since the Team was saved: edit with its
      // current version. Keeping the old id beside the new choice put the same
      // Agent in twice ("An Agent can only appear once in a Team").
      const currentVersion = (member: TeamDetailDto["members"][number]) =>
        agents.find((agent) => agent.agent_id === member.agent_id)
          ?.version_id ?? member.agent_version_id;
      const memberIds = [...detail.members]
        .sort((left, right) => left.position - right.position)
        .map(currentVersion);
      const leader = detail.members.find((member) => member.is_leader);
      const nextForm: FormState = {
        name: detail.display_name,
        visibility: detail.visibility,
        memberVersionIds: memberIds,
        leaderVersionId: leader ? currentVersion(leader) : "",
        sharedSetIds: detail.shared_knowledge_set_ids,
      };
      setForm(nextForm);
      setBaselineForm(nextForm);
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
    if (!apiForTeams || saving || readOnly) return;
    const validation = !form.name.trim()
      ? t("teamNameRequired")
      : form.memberVersionIds.length < 2
        ? t("teamNeedsTwoMembers")
        : !form.leaderVersionId
          ? t("teamChooseLeader")
          : "";
    if (validation) {
      setSubmitHint(validation);
      setError(null);
      setDismissedError(null);
      return;
    }
    setSubmitHint("");
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
              group_id: groupId,
              visibility: editing?.visibility ?? form.visibility,
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
    setDismissedError(null);
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
    celebrate();
    setSaving(false);
    setMutationUnknown(false);
    setError(null);
    setEditing(null);
    setForm(EMPTY_FORM);
    setBaselineForm(null);
    if (!standalone) {
      onSaved?.(savedTeam);
      return;
    }
    // Leave the form directly. A version list between Done and Studyform
    // only flashes the version that was just saved.
    clearTeamDraft(draftKey);
    setSaved(true);
    syncManageRoute("teams");
    onSaved?.(savedTeam);
  }

  const readOnly = Boolean(editing && !editing.can_edit);
  const teamDirty =
    !editing ||
    baselineForm === null ||
    !sameTeamForm(form, baselineForm) ||
    mutationUnknown;
  const memberChoices =
    readOnly && editing
      ? [...editing.members]
          .sort((left, right) => left.position - right.position)
          .map((member) => ({
            versionId: member.agent_version_id,
            agentId: member.agent_id,
            theme: agents.find((agent) => agent.agent_id === member.agent_id)
              ?.avatar_config?.material_theme,
            name: member.display_name,
            versionLabel: "",
            available: true,
          }))
      : agents
          .filter(
            (agent) =>
              form.visibility === "private" || agent.visibility !== "private",
          )
          .map((agent) => ({
            versionId: agent.version_id,
            agentId: agent.agent_id,
            theme: agent.avatar_config?.material_theme,
            name: agent.name,
            versionLabel: agent.version_label,
            available: agent.available,
          }));
  const namedSets = new Map(
    visibleKnowledgeSets.map((set) => [set.id, set.name]),
  );
  for (const set of editing?.shared_knowledge_sets ?? []) {
    namedSets.set(set.id, set.display_name);
  }
  const knowledgeChoices = readOnly
    ? form.sharedSetIds.map((id) => ({
        id,
        name: namedSets.get(id) ?? id,
      }))
    : visibleKnowledgeSets;
  const title = variant === "maya" ? t("mayaTeams") : t("chatTargetTeams");
  const topFormError =
    submitHint ||
    (error && error !== dismissedError
      ? mutationUnknown
        ? t("teamSaveUnknown")
        : error instanceof PlatformApiError
          ? localizeError(error, "teamSaveFailed")
          : t("teamSaveFailed")
      : "");

  // U3: a validation hint is a field error; its field wears sticker 1.
  const hintField = !submitHint
    ? null
    : submitHint === t("teamNameRequired")
      ? "name"
      : "members";
  const busy = readOnly || saving || mutationUnknown;
  const teamsReturnHref = (() => {
    const params = new URLSearchParams();
    if (groupId) params.set("group_id", groupId);
    params.set("mode", initialTeamId ? "team-edit" : "team-new");
    if (initialTeamId) params.set("team_id", initialTeamId);
    return `${pathname}?${params.toString()}`;
  })();
  const agentsHref = agentCreateHref
    ? `${agentCreateHref}?return=${encodeURIComponent(teamsReturnHref)}`
    : undefined;
  const formReady = !loading && apiForTeams && (editing || formOpen);

  if (
    standalone &&
    (formOpen ||
      editing ||
      initialRouteMode === "team-edit" ||
      initialRouteMode === "team-new")
  ) {
    // Approved 13-teams-final E1 cork board with G2 "checked" stickers and the
    // H2 Studyform banner (Back · title · Done).
    const sectionHead = (label: string, guide?: string, guideText?: string) => (
      <div className="mb-4 mt-[-42px] flex items-center gap-2.5">
        <h2 className="m-0 inline-block -skew-x-12 -rotate-1 bg-[#111] px-3.5 py-[3px] font-display text-[15px] leading-normal font-extrabold tracking-[1px] text-white uppercase">
          {label}
        </h2>
        {guide ? (
          <span
            className="inline-grid size-[22px] cursor-help place-items-center rounded-full border-2 border-[#111] bg-[#FFE14D] font-body text-xs font-extrabold text-[#111] shadow-[2px_2px_0_#111]"
            data-ui-guide={guide}
            data-ui-guide-text={guideText}
            aria-hidden="true"
          >
            ?
          </span>
        ) : null}
      </div>
    );
    const cardClass =
      "relative mt-[22px] rounded-[6px] border-[3px] border-[#111] bg-white px-[22px] pt-7 pb-[22px] shadow-[0_0_0_3px_#67E8F9,7px_7px_0_3px_#111]";
    const tilts = [-1.2, 0.8, -0.6, 1.2, -0.9];
    return (
      <section className={AGENT_PAGE} aria-label={title}>
        <PageBanner
          title={
            editing || initialRouteMode === "team-edit"
              ? t("chatEditTeam")
              : title
          }
        >
          <PageAction
            name="back"
            placement="page"
            disabled={saving || mutationUnknown}
            onClick={closeForm}
          />
          {readOnly ? null : (
            <PageAction
              name="done"
              placement="page"
              form={formId}
              disabled={
                !formReady || saving || (Boolean(editing) && !teamDirty)
              }
            />
          )}
        </PageBanner>
        {loading ? <LoadingCard /> : null}
        {loadError && loadError !== dismissedError ? (
          <Notice
            inline
            tone="error"
            onClose={() => setDismissedError(loadError)}
          >
            {apiForTeams ? t("teamLoadFailed") : t("teamApiNotConnected")}
          </Notice>
        ) : null}
        {saved ? (
          <Notice inline tone="success" onClose={() => setSaved(false)}>
            {variant === "maya"
              ? t("mayaTeamPublished")
              : t("teamSavedWaitingForChat")}
          </Notice>
        ) : null}
        {teamListRefreshError ? (
          <Notice
            inline
            tone="warning"
            onClose={() => setTeamListRefreshError(false)}
            action={
              <RetryPill
                disabled={teamListRefreshing}
                onClick={() => void refreshTeamList()}
              >
                {teamListRefreshing ? t("loading") : t("retryTeamList")}
              </RetryPill>
            }
          >
            {t("teamListRefreshFailed")}
          </Notice>
        ) : null}
        {formReady ? (
          <form
            id={formId}
            className="m-0 block p-0"
            onSubmit={(event) => void saveTeam(event)}
          >
            {topFormError ? (
              <Notice
                inline
                tone="error"
                badge={hintField ? 1 : undefined}
                onClose={() => {
                  setSubmitHint("");
                  if (error) setDismissedError(error);
                }}
              >
                {topFormError}
              </Notice>
            ) : null}
            <div className="grid grid-cols-[1.05fr_1fr] items-start gap-7 max-[767px]:grid-cols-1">
              <section className="relative mt-[22px] min-h-[260px] rounded-[12px] border-[3px] border-[#111] bg-[#E8D5B5] px-5 py-7 shadow-[0_0_0_3px_#67E8F9,7px_7px_0_3px_#111] [background-image:radial-gradient(#0001_1px,transparent_1.5px)] [background-size:14px_14px] [&>div:first-child]:mt-[-44px]">
                {sectionHead(
                  t("teamMembers"),
                  "chat.teamMembers",
                  t("teamMembersHelp"),
                )}
                {hintField === "members" ? <StickerBadge n={1} /> : null}
                {memberChoices.length ? (
                  <div
                    className="flex flex-wrap gap-x-4 gap-y-[22px]"
                    role="group"
                    aria-label={t("teamMembers")}
                  >
                    {memberChoices.map((agent, index) => {
                      const checked = form.memberVersionIds.includes(
                        agent.versionId,
                      );
                      const isLeader =
                        checked && form.leaderVersionId === agent.versionId;
                      return (
                        <div
                          key={agent.versionId}
                          className={cn(
                            "relative flex w-[132px] flex-col items-center gap-2 rounded-[6px] border-[3px] border-[#111] px-1.5 py-2.5 max-[767px]:w-[calc(50%-8px)]",
                            checked
                              ? "translate-x-[-2px] translate-y-[-4px] rotate-0 bg-[#FFE14D] shadow-[6px_8px_0_#111]"
                              : "bg-white shadow-[3px_3px_0_#111]",
                          )}
                          style={
                            checked
                              ? undefined
                              : { rotate: `${tilts[index % tilts.length]}deg` }
                          }
                        >
                          {isLeader ? (
                            <span className="absolute -top-3 -left-2 z-[3] inline-block -rotate-3 rounded-[6px] border-2 border-[#111] bg-[#FF4D8D] px-2 py-px font-body text-[10px] leading-normal font-extrabold text-[#111] shadow-[2px_2px_0_#111]">
                              {t("leader")}
                            </span>
                          ) : null}
                          <label className="m-0 flex cursor-pointer flex-col items-center gap-1.5 text-center">
                            <input
                              type="checkbox"
                              className="absolute top-2 left-2 m-0 size-[18px] flex-none accent-[#FF4D8D]"
                              checked={checked}
                              disabled={busy || agent.available === false}
                              onChange={() => {
                                setSubmitHint("");
                                toggleMember(agent.versionId);
                              }}
                            />
                            <span
                              className={cn(
                                "grid size-[60px] place-items-center overflow-hidden rounded-full border-2 border-[#111] bg-white",
                                checked &&
                                  "shadow-[0_0_0_3px_#fff,0_0_0_5px_#111]",
                              )}
                              aria-hidden="true"
                            >
                              <MascotFigure
                                id={agentMascot(agent.agentId, agent.theme)}
                                className="h-[120%] w-auto translate-y-[8%]"
                              />
                            </span>
                            <strong className="font-body text-xs font-extrabold tracking-[-0.01em] [overflow-wrap:anywhere]">
                              {agent.name}
                              {agent.versionLabel
                                ? ` · ${agent.versionLabel}`
                                : ""}
                            </strong>
                          </label>
                          <label className="m-0 inline-flex items-center gap-1.5 font-body text-xs font-bold has-[:disabled]:[&>span]:opacity-45">
                            <input
                              type="radio"
                              className="m-0 size-[18px] flex-none accent-[#FF4D8D]"
                              name={`${formId}-leader`}
                              aria-label={t("teamSetLeader", {
                                name: agent.name,
                              })}
                              checked={form.leaderVersionId === agent.versionId}
                              disabled={busy || !checked}
                              onChange={() => {
                                setSubmitHint("");
                                setForm((current) => ({
                                  ...current,
                                  leaderVersionId: agent.versionId,
                                }));
                              }}
                            />
                            <span>{t("leader")}</span>
                          </label>
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="grid justify-items-start gap-3.5 rounded-[8px] border-[3px] border-[#111] bg-white p-3.5">
                    <p className="m-0 font-body text-[15px] font-semibold text-[#111]">
                      {t("teamMembersNoAgents")}
                    </p>
                    {agentsHref ? (
                      <Link
                        href={agentsHref}
                        className={`inline-flex min-h-11 items-center gap-1.5 rounded-[10px] border-[3px] border-[#111] bg-[#A3E635] px-4 py-[7px] font-body text-sm font-extrabold text-[#111] no-underline [&_svg]:size-4 ${PRESS_MOTION}`}
                        onClick={() => writeTeamDraft(draftKey, form)}
                      >
                        <WorkspaceIcon name="agent" />
                        {t("teamGoToAgents")}
                      </Link>
                    ) : null}
                  </div>
                )}
              </section>
              <div className="min-w-0">
                <section className={cardClass}>
                  {sectionHead(t("teamName"))}
                  <div className="relative">
                    {hintField === "name" ? <StickerBadge n={1} /> : null}
                    <input
                      className="box-border w-full rounded-[10px] border-[3px] border-[#111] bg-white px-3.5 py-2.5 font-body text-lg font-semibold text-[#111]"
                      aria-label={t("teamName")}
                      value={form.name}
                      maxLength={120}
                      disabled={busy}
                      onChange={(event) => {
                        setSubmitHint("");
                        setForm((current) => ({
                          ...current,
                          name: event.target.value,
                        }));
                      }}
                    />
                  </div>
                  {!editing ? (
                    <div
                      className="mt-3 inline-flex overflow-hidden rounded-[10px] border-[3px] border-[#111] bg-white shadow-[3px_3px_0_#111]"
                      role="group"
                      aria-label={t("agentVisibility")}
                    >
                      {(["private", "public"] as const).map((option) => (
                        <button
                          key={option}
                          type="button"
                          className={cn(
                            "m-0 min-h-0 cursor-pointer rounded-none border-0 bg-white px-4 py-1.5 font-body text-[13px] leading-normal font-extrabold text-[#111] shadow-none",
                            option === "public" &&
                              "border-l-[3px] border-[#111]",
                            form.visibility === option &&
                              (option === "public"
                                ? "bg-[#22C55E]"
                                : "bg-[#E5E7EB]"),
                          )}
                          aria-pressed={form.visibility === option}
                          disabled={saving || mutationUnknown}
                          onClick={() => {
                            setSubmitHint("");
                            setForm((current) =>
                              withTeamVisibility(current, option, agents),
                            );
                          }}
                        >
                          {t(
                            option === "private"
                              ? "privateOption"
                              : "publicOption",
                          )}
                        </button>
                      ))}
                    </div>
                  ) : null}
                </section>
                <section className={cardClass}>
                  {sectionHead(
                    t("teamSharedKnowledge"),
                    "chat.teamSharedKnowledge",
                    t("teamSharedKnowledgeHelp"),
                  )}
                  {knowledgeChoices.length ? (
                    <div role="group" aria-label={t("teamSharedKnowledge")}>
                      {knowledgeChoices.map((set) => {
                        const on = form.sharedSetIds.includes(set.id);
                        return (
                          <label
                            key={set.id}
                            className={cn(
                              "relative mb-2.5 flex cursor-pointer items-center gap-2.5 rounded-[8px] border-2 border-[#111] px-3 py-2.5",
                              on
                                ? "translate-x-[-2px] translate-y-[-2px] bg-[#FFE14D] shadow-[5px_5px_0_#111]"
                                : "bg-white shadow-[2px_2px_0_#111]",
                            )}
                          >
                            <input
                              type="checkbox"
                              className="m-0 size-[18px] flex-none accent-[#FF4D8D]"
                              checked={on}
                              disabled={busy}
                              onChange={() =>
                                setForm((current) => ({
                                  ...current,
                                  sharedSetIds: current.sharedSetIds.includes(
                                    set.id,
                                  )
                                    ? current.sharedSetIds.filter(
                                        (id) => id !== set.id,
                                      )
                                    : [...current.sharedSetIds, set.id],
                                }))
                              }
                            />
                            <strong className="font-body text-sm font-bold [overflow-wrap:anywhere]">
                              {set.name}
                            </strong>
                          </label>
                        );
                      })}
                    </div>
                  ) : (
                    <p className="m-0 font-body text-sm font-medium text-[#4B5563]">
                      {t("teamNoSharedKnowledge")}
                    </p>
                  )}
                </section>
              </div>
            </div>
          </form>
        ) : null}
      </section>
    );
  }

  return (
    <section
      className={
        !loading && apiForTeams && (editing || formOpen)
          ? `${styles.entryFlow} ${styles.entryFlowForm}`
          : styles.entryFlow
      }
      aria-label={title}
    >
      <div className={styles.entrySection}>
        {loading ? <LoadingCard /> : null}
        {loadError && loadError !== dismissedError ? (
          <Notice
            inline
            tone="error"
            onClose={() => setDismissedError(loadError)}
          >
            {apiForTeams ? t("teamLoadFailed") : t("teamApiNotConnected")}
          </Notice>
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
                <small>{teamVersionLabel(team.current_version_seq)}</small>
              </li>
            ))}
          </ul>
        ) : null}
        {standalone &&
        !formOpen &&
        !loading &&
        !loadError &&
        !visibleTeams.length ? (
          <p className={styles.entryHint}>{t("teamNoneYet")}</p>
        ) : null}

        {saved ? (
          <Notice inline tone="success" onClose={() => setSaved(false)}>
            {variant === "maya"
              ? t("mayaTeamPublished")
              : t("teamSavedWaitingForChat")}
          </Notice>
        ) : null}
        {teamListRefreshError ? (
          <Notice
            inline
            tone="warning"
            onClose={() => setTeamListRefreshError(false)}
            action={
              <RetryPill
                disabled={teamListRefreshing}
                onClick={() => void refreshTeamList()}
              >
                {teamListRefreshing ? t("loading") : t("retryTeamList")}
              </RetryPill>
            }
          >
            {t("teamListRefreshFailed")}
          </Notice>
        ) : null}

        {!loading && apiForTeams && (editing || formOpen) ? (
          <form
            id={formId}
            className={
              readOnly
                ? `${styles.teamForm} ${styles.teamFormReadOnly}`
                : styles.teamForm
            }
            onSubmit={(event) => void saveTeam(event)}
          >
            {/* Owner request (2026-10-13): the same cards, rows and width as
                Agents New, centred on the page. */}
            {topFormError ? (
              <Notice
                inline
                tone="error"
                badge={hintField ? 1 : undefined}
                onClose={() => {
                  setSubmitHint("");
                  if (error) setDismissedError(error);
                }}
              >
                {topFormError}
              </Notice>
            ) : null}
            <SectionCard title={t("teamName")}>
              <div className="stack-form wide-form quiet-create">
                <label className="relative">
                  {hintField === "name" ? <StickerBadge n={1} /> : null}
                  <input
                    aria-label={t("teamName")}
                    value={form.name}
                    maxLength={120}
                    disabled={readOnly || saving || mutationUnknown}
                    onChange={(event) => {
                      setSubmitHint("");
                      setForm((current) => ({
                        ...current,
                        name: event.target.value,
                      }));
                    }}
                  />
                </label>
                {!editing ? (
                  <div className="agent-identity">
                    <div
                      className="visibility-toggle"
                      role="group"
                      aria-label={t("agentVisibility")}
                    >
                      {(["private", "public"] as const).map((option) => (
                        <button
                          key={option}
                          type="button"
                          aria-pressed={form.visibility === option}
                          disabled={saving || mutationUnknown}
                          onClick={() => {
                            setSubmitHint("");
                            setForm((current) =>
                              withTeamVisibility(current, option, agents),
                            );
                          }}
                        >
                          {t(
                            option === "private"
                              ? "privateOption"
                              : "publicOption",
                          )}
                        </button>
                      ))}
                    </div>
                  </div>
                ) : null}
              </div>
            </SectionCard>
            <SectionCard
              title={t("teamMembers")}
              guide="chat.teamMembers"
              guideText={t("teamMembersHelp")}
            >
              <div
                className="document-list"
                role="group"
                aria-label={t("teamMembers")}
              >
                {memberChoices.map((agent) => {
                  const checked = form.memberVersionIds.includes(
                    agent.versionId,
                  );
                  return (
                    <div className="document-row" key={agent.versionId}>
                      <label className="document-select">
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={
                            readOnly ||
                            agent.available === false ||
                            saving ||
                            mutationUnknown
                          }
                          onChange={() => {
                            setSubmitHint("");
                            toggleMember(agent.versionId);
                          }}
                        />
                        <span className="document-main">
                          <strong>
                            {agent.name}
                            {agent.versionLabel
                              ? ` · ${agent.versionLabel}`
                              : ""}
                          </strong>
                        </span>
                      </label>
                      <div className="row-actions">
                        <label className={styles.entryChoice}>
                          <input
                            type="radio"
                            name={`${formId}-leader`}
                            aria-label={t("teamSetLeader", {
                              name: agent.name,
                            })}
                            checked={form.leaderVersionId === agent.versionId}
                            disabled={
                              readOnly || !checked || saving || mutationUnknown
                            }
                            onChange={() => {
                              setSubmitHint("");
                              setForm((current) => ({
                                ...current,
                                leaderVersionId: agent.versionId,
                              }));
                            }}
                          />
                          <span>{t("leader")}</span>
                        </label>
                      </div>
                    </div>
                  );
                })}
              </div>
            </SectionCard>
            <SectionCard
              title={t("teamSharedKnowledge")}
              guide="chat.teamSharedKnowledge"
              guideText={t("teamSharedKnowledgeHelp")}
            >
              {knowledgeChoices.length ? (
                <div
                  className="document-list"
                  role="group"
                  aria-label={t("teamSharedKnowledge")}
                >
                  {knowledgeChoices.map((set) => (
                    <div className="document-row" key={set.id}>
                      <label className="document-select">
                        <input
                          type="checkbox"
                          checked={form.sharedSetIds.includes(set.id)}
                          disabled={readOnly || saving || mutationUnknown}
                          onChange={() =>
                            setForm((current) => ({
                              ...current,
                              sharedSetIds: current.sharedSetIds.includes(
                                set.id,
                              )
                                ? current.sharedSetIds.filter(
                                    (id) => id !== set.id,
                                  )
                                : [...current.sharedSetIds, set.id],
                            }))
                          }
                        />
                        <span className="document-main">
                          <strong>{set.name}</strong>
                        </span>
                      </label>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="muted-copy">{t("teamNoSharedKnowledge")}</p>
              )}
            </SectionCard>
            {readOnly ? null : (
              <PageAction
                name="done"
                form={formId}
                disabled={saving || (Boolean(editing) && !teamDirty)}
              />
            )}
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
