"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";

import {
  isAmbiguousMutationFailure,
  isConflict,
  type AssetCitation,
  type AgentKnowledgeSets,
  type AssetContent,
  type AgentDetail,
  type Course,
  type KnowledgeAsset,
  type KnowledgeAssetFull,
  type KnowledgeAssetVersions,
  type KnowledgeAssetRequest,
  type KnowledgeDocument,
  type KnowledgeGraph,
  type KnowledgeGenerationStatus,
  type KnowledgeSetDetail,
  type KnowledgeSetSummary,
  type UpdateKnowledgeAssetRequest,
} from "../../lib/api";
import { useIdempotencyStore } from "../../lib/idempotency";
import { useT } from "../locale";
import { useSession } from "../session-provider";
import { TeacherKnowledgeSources } from "./teacher-knowledge-sources";
import {
  EmptyCard,
  ErrorNotice,
  LoadingCard,
  PageIntro,
  SectionCard,
} from "../ui";

import styles from "./knowledge-set-workspace.module.css";

type AssetKind = "concept" | "question" | "note";
type WorkspaceTab = "sources" | AssetKind;
type KnowledgeGenerationProgress = KnowledgeGenerationStatus & {
  accepted_item_count: number;
  materialized_item_count: number;
  failed_item_count: number;
};

type AssetDraft = {
  title: string;
  prompt: string;
  referenceAnswer: string | null;
  description: string;
  body: string;
  prerequisiteIds: string[];
  conceptIds: string[];
  rubricCriteria: Array<{ label: string; guidance: string; points: string }>;
  rubricTotalPoints: string;
};

const EMPTY_DRAFT: AssetDraft = {
  title: "",
  prompt: "",
  referenceAnswer: null,
  description: "",
  body: "",
  prerequisiteIds: [],
  conceptIds: [],
  rubricCriteria: [{ label: "Reasoning", guidance: "", points: "2" }],
  rubricTotalPoints: "2",
};

const TABS: WorkspaceTab[] = ["sources", "concept", "question", "note"];

function isFullAsset(asset: KnowledgeAsset): asset is KnowledgeAssetFull {
  return asset.audience === "full";
}

function labelForTab(tab: WorkspaceTab, t: ReturnType<typeof useT>): string {
  switch (tab) {
    case "sources":
      return t("sources");
    case "concept":
      return t("concepts");
    case "question":
      return t("questions");
    case "note":
      return t("notes");
  }
}

function GenerationStatusNotice({
  status,
  error,
  agentId,
  onRetry,
}: {
  status: KnowledgeGenerationStatus | null;
  error: unknown;
  agentId?: string;
  onRetry: () => void;
}) {
  const t = useT();
  if (error) {
    return (
      <div className="notice notice-warning" role="alert">
        <strong>{t("generationStatusUnavailable")}</strong>
        <span>{t("generationStatusUnavailableHelp")}</span>
        <button className="inline-button" type="button" onClick={onRetry}>
          {t("retryStatusCheck")}
        </button>
      </div>
    );
  }
  if (!status)
    return (
      <p className="notice" role="status">
        {t("loading")}
      </p>
    );
  const progress = status as KnowledgeGenerationProgress;
  const countLine = `${t("aiKnowledgeSavedItems")}: ${progress.materialized_item_count}; ${t("aiKnowledgeCandidates")}: ${progress.accepted_item_count}; ${t("aiKnowledgeFailedItems")}: ${progress.failed_item_count}`;
  if (status.state === "pending" || status.state === "running") {
    return (
      <div className="notice" role="status">
        <strong>Generating AI Knowledge</strong>
        {progress.accepted_item_count > 0 ||
        progress.materialized_item_count > 0 ||
        progress.failed_item_count > 0 ? (
          <span>{countLine}</span>
        ) : null}
      </div>
    );
  }
  const hasPartialItems =
    progress.materialized_item_count > 0 && progress.failed_item_count > 0;
  const partialFailure =
    status.safe_error_code === "knowledge_generation_partial_failure" &&
    progress.materialized_item_count > 0;
  if (status.state === "completed" && !hasPartialItems) {
    return (
      <div className="notice notice-success" role="status">
        <strong>{t("aiKnowledgeGenerationFinished")}</strong>
        <span>{countLine}</span>
      </div>
    );
  }
  const safeReason = status.safe_error_code
    ? ` (${status.safe_error_code.replaceAll("_", " ")})`
    : "";
  const unknownAcceptance = status.safe_error_code === "acceptance_unknown";
  const disclosureRequired =
    status.safe_error_code === "provider_confirmation_required" &&
    status.provider_manifest_hash;
  return (
    <div className="notice notice-warning" role="alert">
      <strong>
        {partialFailure || hasPartialItems
          ? t("aiKnowledgeGenerationPartial")
          : status.state === "blocked"
            ? t("aiKnowledgeGenerationBlocked")
            : t("aiKnowledgeGenerationStopped")}
        {safeReason}
      </strong>
      {progress.materialized_item_count > 0 ||
      progress.failed_item_count > 0 ||
      progress.accepted_item_count > 0 ? (
        <span>{countLine}</span>
      ) : null}
      <span>
        {unknownAcceptance
          ? t("aiKnowledgeGenerationUnknown")
          : disclosureRequired
            ? t("aiKnowledgeProviderConfirmationRecovery")
            : partialFailure || hasPartialItems
              ? t("aiKnowledgeGenerationPartialRecovery")
              : t("aiKnowledgeGenerationRecovery")}
      </span>
      {disclosureRequired ? (
        <Link
          className="text-link"
          href={`/teacher/provider-disclosures/${encodeURIComponent(status.provider_manifest_hash as string)}`}
        >
          {t("reviewProviderDisclosure")}
        </Link>
      ) : null}
      {agentId && !unknownAcceptance ? (
        <Link
          className="text-link"
          href={`/teacher/agents/${encodeURIComponent(agentId)}?flow=ai-knowledge`}
        >
          {t("openAgentWorkbench")}
        </Link>
      ) : null}
    </div>
  );
}

type KnowledgeSetWorkspaceProps = {
  agentId?: string;
  initialSetId?: string;
  generationJobId?: string;
  role?: "teacher" | "student";
};

export function KnowledgeSetWorkspace(props: KnowledgeSetWorkspaceProps) {
  const role = props.role ?? "teacher";
  const { identityGeneration, user } = useSession();
  const roleCourseId = user?.courses.find(
    (membership) => membership.role === role,
  )?.course_id;
  const actorScope = JSON.stringify({
    userId: user?.id ?? null,
    roleCourseId: roleCourseId ?? null,
    role,
    agentId: props.agentId ?? null,
    identityGeneration,
    courses: (user?.courses ?? [])
      .map((membership) => `${membership.course_id}:${membership.role}`)
      .sort(),
    groups: (user?.groups ?? []).map((group) => group.group_id).sort(),
  });
  return (
    <KnowledgeSetWorkspaceBody
      key={actorScope}
      agentId={props.agentId}
      initialSetId={props.initialSetId}
      generationJobId={props.generationJobId}
      role={role}
      roleCourseId={roleCourseId}
      actorScope={actorScope}
    />
  );
}

function KnowledgeSetWorkspaceBody({
  agentId,
  initialSetId,
  generationJobId,
  role,
  roleCourseId,
  actorScope,
}: {
  agentId?: string;
  initialSetId?: string;
  generationJobId?: string;
  role: "teacher" | "student";
  roleCourseId: string | undefined;
  actorScope: string;
}) {
  const t = useT();
  const { api, user } = useSession();
  const userCourses = useMemo(() => user?.courses ?? [], [user?.courses]);
  const userGroups = useMemo(() => user?.groups ?? [], [user?.groups]);
  const mutationStore = useIdempotencyStore();
  const [selectedCourseId, setSelectedCourseId] = useState<string | null>(null);
  const [availableCourses, setAvailableCourses] = useState<Course[]>([]);
  const workspaceScope = `${actorScope}:${selectedCourseId ?? "auto"}`;
  const actorScopeRef = useRef(workspaceScope);
  const selectedAssetIdRef = useRef<string | null>(null);
  const generationAssetRefreshRef = useRef(
    new Map<
      string,
      { materializedCount: number; terminalRefreshed: boolean }
    >(),
  );
  const generationAssetRequestRef = useRef(new Map<string, number>());
  const isCurrentScope = useCallback(
    (scope: string) => actorScopeRef.current === scope,
    [],
  );
  const [sets, setSets] = useState<KnowledgeSetSummary[]>([]);
  const [groups, setGroups] = useState<Array<{ id: string; name: string }>>([]);
  const [workspaceCourseId, setWorkspaceCourseId] = useState<string | null>(
    null,
  );
  const [selectedSetId, setSelectedSetId] = useState<string | null>(null);
  const selectedSetIdRef = useRef<string | null>(null);
  const [detail, setDetail] = useState<KnowledgeSetDetail | null>(null);
  const [loadedSetId, setLoadedSetId] = useState<string | null>(null);
  const [assets, setAssets] = useState<KnowledgeAsset[]>([]);
  const [selectedAsset, setSelectedAsset] = useState<KnowledgeAsset | null>(
    null,
  );
  const [assetHistory, setAssetHistory] =
    useState<KnowledgeAssetVersions | null>(null);
  const [assetHistoryOpen, setAssetHistoryOpen] = useState(false);
  const [assetHistoryLoading, setAssetHistoryLoading] = useState(false);
  const [assetHistoryError, setAssetHistoryError] = useState(false);
  const [graph, setGraph] = useState<KnowledgeGraph | null>(null);
  const [graphConceptDetail, setGraphConceptDetail] =
    useState<KnowledgeAsset | null>(null);
  const [graphConceptLoading, setGraphConceptLoading] = useState(false);
  const [sourceDocuments, setSourceDocuments] = useState<KnowledgeDocument[]>(
    [],
  );
  const [sourceIds, setSourceIds] = useState<string[]>([]);
  const [assetCitations, setAssetCitations] = useState<AssetCitation[]>([]);
  const [tab, setTab] = useState<WorkspaceTab>("sources");
  const [conceptView, setConceptView] = useState<"list" | "graph">("list");
  const [loading, setLoading] = useState(true);
  const [knowledgeView, setKnowledgeView] = useState<"sources" | "sets">(
    "sets",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [sourceError, setSourceError] = useState<unknown>(null);
  const [notice, setNotice] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newGroupId, setNewGroupId] = useState("");
  const [displayName, setDisplayName] = useState("");
  const [nameEditing, setNameEditing] = useState(false);
  const nameCommitPending = useRef(false);
  const cancelNameBlur = useRef(false);
  const [visibility, setVisibility] = useState<"private" | "public">("private");
  const [editingAsset, setEditingAsset] = useState<KnowledgeAssetFull | null>(
    null,
  );
  const [draft, setDraft] = useState<AssetDraft>(EMPTY_DRAFT);
  const [agentKnowledge, setAgentKnowledge] =
    useState<AgentKnowledgeSets | null>(null);
  const [agentSetIds, setAgentSetIds] = useState<string[]>([]);
  const [agentError, setAgentError] = useState<unknown>(null);
  const [generationStatusSnapshot, setGenerationStatusSnapshot] = useState<{
    jobId: string;
    status?: KnowledgeGenerationStatus;
    error?: unknown;
  } | null>(null);
  const [generationStatusRetry, setGenerationStatusRetry] = useState(0);

  const clearSelectedSetData = useCallback(() => {
    setDetail(null);
    setAssets([]);
    setSelectedAsset(null);
    setAssetHistory(null);
    setAssetHistoryOpen(false);
    setAssetHistoryLoading(false);
    selectedAssetIdRef.current = null;
    setGraph(null);
    setGraphConceptDetail(null);
    setGraphConceptLoading(false);
    setSourceDocuments([]);
    setSourceError(null);
    setEditingAsset(null);
    setDraft(EMPTY_DRAFT);
    setLoadedSetId(null);
    setError(null);
    setNotice("");
  }, []);

  const selectSet = useCallback(
    (nextSetId: string | null) => {
      if (selectedSetIdRef.current !== nextSetId) clearSelectedSetData();
      selectedSetIdRef.current = nextSetId;
      setSelectedSetId(nextSetId);
    },
    [clearSelectedSetData],
  );

  const selectCourse = useCallback(
    (courseId: string) => {
      actorScopeRef.current = `${actorScope}:${courseId}`;
      setSelectedCourseId(courseId);
      setWorkspaceCourseId(null);
      setSets([]);
      setGroups([]);
      selectSet(null);
      setAgentKnowledge(null);
      setAgentSetIds([]);
      setError(null);
      setLoading(true);
    },
    [actorScope, selectSet],
  );

  useEffect(() => {
    actorScopeRef.current = workspaceScope;
    return () => {
      if (actorScopeRef.current === workspaceScope) {
        actorScopeRef.current = `disposed:${workspaceScope}`;
      }
    };
  }, [workspaceScope]);

  const loadWorkspace = useCallback(async () => {
    const requestScope = workspaceScope;
    if (!roleCourseId && !agentId) {
      setLoading(false);
      setError(new Error(t("viewUnavailable")));
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const [courseList, agent] = await Promise.all([
        api.courses(),
        agentId ? api.agent(agentId) : Promise.resolve(null),
      ]);
      if (!isCurrentScope(requestScope)) return;
      const teacherCourses = courseList.filter((course) =>
        userCourses.some(
          (membership) =>
            membership.course_id === course.id && membership.role === role,
        ),
      );
      setAvailableCourses(teacherCourses);
      let courseId = agentId
        ? (agent as AgentDetail | null)?.course_id
        : (selectedCourseId ?? roleCourseId);
      if (agentId) {
        if (!teacherCourses.some((course) => course.id === courseId)) {
          throw new Error(t("viewUnavailable"));
        }
      } else if (!teacherCourses.some((course) => course.id === courseId)) {
        const fallbackCourseId = teacherCourses[0]?.id;
        if (!fallbackCourseId) throw new Error(t("viewUnavailable"));
        selectCourse(fallbackCourseId);
        return;
      }
      if (!courseId) throw new Error(t("viewUnavailable"));
      setWorkspaceCourseId(courseId);
      const [nextSets, nextGroups, nextAgentKnowledge] = await Promise.all([
        api.knowledgeSets(courseId),
        api.groups(courseId),
        agentId ? api.agentKnowledgeSets(agentId) : Promise.resolve(null),
      ]);
      if (!isCurrentScope(requestScope)) return;
      const joinedGroupIds = new Set(userGroups.map((item) => item.group_id));
      setSets(nextSets);
      setGroups(
        nextGroups
          .filter((group) => joinedGroupIds.has(group.id))
          .map((group) => ({ id: group.id, name: group.name })),
      );
      const currentSetId = selectedSetIdRef.current;
      const nextSetId = nextSets.some((row) => row.id === currentSetId)
        ? currentSetId
        : (initialSetId ?? nextSets[0]?.id ?? null);
      selectSet(nextSetId);
      setAgentKnowledge(nextAgentKnowledge);
      setAgentSetIds(nextAgentKnowledge?.sets.map((row) => row.id) ?? []);
      setAgentError(null);
    } catch (cause) {
      if (isCurrentScope(requestScope)) {
        setError(cause);
        setAgentError(cause);
      }
    } finally {
      if (isCurrentScope(requestScope)) setLoading(false);
    }
  }, [
    agentId,
    initialSetId,
    api,
    isCurrentScope,
    selectedCourseId,
    t,
    role,
    roleCourseId,
    workspaceScope,
    userCourses,
    userGroups,
    selectCourse,
    selectSet,
  ]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadWorkspace(), 0);
    return () => window.clearTimeout(timer);
  }, [loadWorkspace]);

  useEffect(() => {
    if (!generationJobId) return;
    let active = true;
    let timer: number | undefined;
    const refresh = async () => {
      try {
        const next = await api.knowledgeGenerationJob(generationJobId);
        if (!active) return;
        setGenerationStatusSnapshot({ jobId: generationJobId, status: next });
        if (next.state === "pending" || next.state === "running") {
          timer = window.setTimeout(() => void refresh(), 1500);
        }
      } catch (cause) {
        if (active)
          setGenerationStatusSnapshot({ jobId: generationJobId, error: cause });
      }
    };
    void refresh();
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [api, generationJobId, generationStatusRetry]);

  const refreshSelected = useCallback(
    async (setId: string, isStillCurrent?: () => boolean) => {
      const requestScope = workspaceScope;
      const [nextDetail, nextAssets, nextGraph] = await Promise.all([
        api.knowledgeSet(setId),
        api.knowledgeSetAssets(setId),
        api.knowledgeSetGraph(setId),
      ]);
      if (
        !isCurrentScope(requestScope) ||
        selectedSetIdRef.current !== setId ||
        (isStillCurrent && !isStillCurrent())
      )
        return false;
      setDetail(nextDetail);
      setAssets(nextAssets);
      const selectedId = selectedAssetIdRef.current;
      if (selectedId) {
        const nextSelected = nextAssets.find(
          (asset) => asset.id === selectedId,
        );
        if (nextSelected) setSelectedAsset(nextSelected);
      }
      setGraph(nextGraph);
      setGraphConceptDetail(null);
      setSets((current) =>
        current.map((row) => (row.id === nextDetail.id ? nextDetail : row)),
      );
      setDisplayName(nextDetail.display_name);
      setVisibility(nextDetail.visibility);
      setSourceIds(
        nextDetail.sources
          .filter((source) => source.available && source.document_id)
          .map((source) => source.document_id as string),
      );
      return true;
    },
    [api, isCurrentScope, workspaceScope],
  );

  useEffect(() => {
    if (generationStatusSnapshot?.jobId !== generationJobId) return;
    const status = generationStatusSnapshot?.status;
    if (!status || status.knowledge_set_id !== selectedSetId) return;
    const progress = status as KnowledgeGenerationProgress;
    if (progress.materialized_item_count <= 0) return;
    const terminal = status.state !== "pending" && status.state !== "running";
    const requestScope = workspaceScope;
    const refreshKey = `${requestScope}:${generationJobId}:${status.knowledge_set_id}`;
    const previous = generationAssetRefreshRef.current.get(refreshKey) ?? {
      materializedCount: 0,
      terminalRefreshed: false,
    };
    const countIncreased =
      progress.materialized_item_count > previous.materializedCount;
    const firstTerminalRefresh = terminal && !previous.terminalRefreshed;
    if (!countIncreased && !firstTerminalRefresh) return;
    let active = true;
    const requestId =
      (generationAssetRequestRef.current.get(refreshKey) ?? 0) + 1;
    generationAssetRequestRef.current.set(refreshKey, requestId);
    const isStillCurrent = () =>
      active &&
      isCurrentScope(requestScope) &&
      selectedSetIdRef.current === status.knowledge_set_id &&
      generationAssetRequestRef.current.get(refreshKey) === requestId;
    void (async () => {
      try {
        const applied = await refreshSelected(
          status.knowledge_set_id,
          isStillCurrent,
        );
        if (isStillCurrent() && applied && isCurrentScope(requestScope)) {
          generationAssetRefreshRef.current.set(refreshKey, {
            materializedCount: progress.materialized_item_count,
            terminalRefreshed: terminal,
          });
        }
      } catch (cause) {
        if (isStillCurrent() && isCurrentScope(requestScope)) {
          setError(cause);
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [
    generationStatusSnapshot,
    generationJobId,
    isCurrentScope,
    refreshSelected,
    selectedSetId,
    workspaceScope,
  ]);

  useEffect(() => {
    if (!selectedSetId || !workspaceCourseId) return;
    let active = true;
    const requestScope = workspaceScope;
    void (async () => {
      try {
        const [nextDetail, nextAssets, nextGraph] = await Promise.all([
          api.knowledgeSet(selectedSetId),
          api.knowledgeSetAssets(selectedSetId),
          api.knowledgeSetGraph(selectedSetId),
        ]);
        if (!active || !isCurrentScope(requestScope)) return;
        setDetail(nextDetail);
        setAssets(nextAssets);
        setGraph(nextGraph);
        setLoadedSetId(selectedSetId);
        setGraphConceptDetail(null);
        setDisplayName(nextDetail.display_name);
        setVisibility(nextDetail.visibility);
        setSourceIds(
          nextDetail.sources
            .filter((source) => source.available && source.document_id)
            .map((source) => source.document_id as string),
        );
        setEditingAsset(null);
        setSelectedAsset(null);
        setAssetHistory(null);
        setAssetHistoryOpen(false);
        setAssetHistoryLoading(false);
        selectedAssetIdRef.current = null;
        setDraft(EMPTY_DRAFT);
        const groupIds =
          nextDetail.ownership_scope === "group" && nextDetail.group_id
            ? [nextDetail.group_id]
            : groups.map((group) => group.id);
        const joined = new Set(userGroups.map((group) => group.group_id));
        const permittedGroupIds = groupIds.filter((id) => joined.has(id));
        const documentRequests: Promise<KnowledgeDocument[]>[] = [];
        if (role === "teacher") {
          documentRequests.push(api.workspaceDocuments(workspaceCourseId));
        }
        documentRequests.push(
          ...permittedGroupIds.map((id) => api.knowledge(id)),
        );
        const documentResults = await Promise.allSettled(documentRequests);
        if (!active || !isCurrentScope(requestScope)) return;
        const unique = new Map<string, KnowledgeDocument>();
        let documentLoadError: unknown = null;
        for (const result of documentResults) {
          if (result.status === "rejected") {
            documentLoadError ??= result.reason;
            continue;
          }
          for (const document of result.value) {
            unique.set(document.id, document);
          }
        }
        const visibleDocuments = [...unique.values()].filter((document) => {
          if (document.ownership_scope === "personal") {
            return (
              document.can_manage_visibility &&
              nextDetail.visibility === "private"
            );
          }
          if (nextDetail.group_id) {
            if (document.group_id !== nextDetail.group_id) return false;
            if (nextDetail.visibility === "public")
              return document.visibility === "public";
            return (
              document.visibility === "public" || document.can_manage_visibility
            );
          }
          return Boolean(
            document.group_id &&
            joined.has(document.group_id) &&
            (document.can_manage_visibility ||
              document.visibility === "public"),
          );
        });
        setSourceDocuments(visibleDocuments);
        setSourceError(documentLoadError);
      } catch (cause) {
        if (!active || !isCurrentScope(requestScope)) return;
        setLoadedSetId(selectedSetId);
        setError(cause);
        // A failure in an auxiliary document listing must not erase a Set
        // detail that was already read successfully.
        setSourceError(cause);
      }
    })();
    return () => {
      active = false;
    };
  }, [
    api,
    groups,
    isCurrentScope,
    role,
    selectedSetId,
    workspaceCourseId,
    workspaceScope,
    userGroups,
  ]);

  const detailLoading = Boolean(
    selectedSetId && workspaceCourseId && loadedSetId !== selectedSetId,
  );

  const setById = useMemo(
    () => new Map(sets.map((row) => [row.id, row])),
    [sets],
  );
  const currentSet = selectedSetId
    ? (setById.get(selectedSetId) ?? null)
    : null;
  const generatedByAgentId =
    role === "teacher" &&
    detail?.can_edit &&
    detail.ownership_scope === "personal" &&
    detail.owner_user_id === user?.id
      ? detail.generated_by_agent_id
      : null;
  const visibleAssets = useMemo(
    () => assets.filter((asset) => tab === "sources" || asset.kind === tab),
    [assets, tab],
  );

  function updateSetInList(next: KnowledgeSetSummary) {
    setSets((current) =>
      current.map((row) => (row.id === next.id ? next : row)),
    );
  }

  async function createSet(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!workspaceCourseId || !newName.trim()) return;
    const requestScope = workspaceScope;
    const body = {
      display_name: newName,
      ...(newGroupId ? { group_id: newGroupId } : {}),
    };
    const intent = `knowledge-set:create:${requestScope}:${JSON.stringify(body)}`;
    const handle = mutationStore.handleFor(intent);
    setBusy(true);
    setError(null);
    setNotice("");
    try {
      const created = await api.createKnowledgeSet(workspaceCourseId, body, {
        idempotency: handle,
      });
      if (!isCurrentScope(requestScope)) return;
      mutationStore.finish(intent, handle);
      setSets((current) => [
        ...current.filter((row) => row.id !== created.id),
        created,
      ]);
      selectSet(created.id);
      setNewName("");
      setNewGroupId("");
      setShowCreate(false);
      setNotice(t("setCreated"));
    } catch (cause) {
      if (!isCurrentScope(requestScope)) return;
      if (!isAmbiguousMutationFailure(cause))
        mutationStore.abandon(intent, handle);
      setError(cause);
    } finally {
      if (isCurrentScope(requestScope)) setBusy(false);
    }
  }

  async function saveMetadata(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!detail || !detail.can_edit || detail.metadata_revision == null) return;
    const changedVisibility =
      detail.ownership_scope === "group" && visibility !== detail.visibility;
    if (!changedVisibility) return;
    const requestScope = workspaceScope;
    const body = {
      expected_metadata_revision: detail.metadata_revision,
      visibility,
    };
    const intent = `knowledge-set:metadata:${requestScope}:${detail.id}:${JSON.stringify(body)}`;
    const handle = mutationStore.handleFor(intent);
    setBusy(true);
    setError(null);
    setNotice("");
    try {
      const next = await api.updateKnowledgeSet(detail.id, body, {
        idempotency: handle,
      });
      if (!isCurrentScope(requestScope)) return;
      mutationStore.finish(intent, handle);
      setDetail(next);
      updateSetInList(next);
      setDisplayName(next.display_name);
      setVisibility(next.visibility);
      setNotice(t("setSaved"));
    } catch (cause) {
      if (!isCurrentScope(requestScope)) return;
      if (!isAmbiguousMutationFailure(cause))
        mutationStore.abandon(intent, handle);
      setError(cause);
    } finally {
      if (isCurrentScope(requestScope)) setBusy(false);
    }
  }

  async function commitSetName() {
    if (
      nameCommitPending.current ||
      !detail?.can_edit ||
      detail.metadata_revision == null
    )
      return;
    const nextName = displayName.trim();
    if (!nextName || nextName === detail.display_name) {
      setDisplayName(detail.display_name);
      setNameEditing(false);
      return;
    }
    const requestScope = workspaceScope;
    const body = {
      expected_metadata_revision: detail.metadata_revision,
      display_name: nextName,
    };
    const intent = `knowledge-set:name:${requestScope}:${detail.id}:${JSON.stringify(body)}`;
    const handle = mutationStore.handleFor(intent);
    nameCommitPending.current = true;
    setBusy(true);
    setError(null);
    setNotice("");
    try {
      const next = await api.updateKnowledgeSet(detail.id, body, {
        idempotency: handle,
      });
      if (!isCurrentScope(requestScope)) return;
      mutationStore.finish(intent, handle);
      setDetail(next);
      updateSetInList(next);
      setDisplayName(next.display_name);
      setNameEditing(false);
      setNotice(t("setSaved"));
    } catch (cause) {
      if (!isCurrentScope(requestScope)) return;
      if (!isAmbiguousMutationFailure(cause))
        mutationStore.abandon(intent, handle);
      setError(cause);
    } finally {
      nameCommitPending.current = false;
      if (isCurrentScope(requestScope)) setBusy(false);
    }
  }

  async function revokeSet() {
    if (
      !detail ||
      !detail.can_edit ||
      detail.metadata_revision == null ||
      detail.content_revision == null
    )
      return;
    const requestScope = workspaceScope;
    const body = {
      expected_metadata_revision: detail.metadata_revision,
      expected_content_revision: detail.content_revision,
    };
    const intent = `knowledge-set:revoke:${requestScope}:${detail.id}:${JSON.stringify(body)}`;
    const handle = mutationStore.handleFor(intent);
    setBusy(true);
    setError(null);
    setNotice("");
    try {
      await api.deleteKnowledgeSet(detail.id, body, { idempotency: handle });
      if (!isCurrentScope(requestScope)) return;
      mutationStore.finish(intent, handle);
      setSets((current) => current.filter((row) => row.id !== detail.id));
      selectSet(null);
      setNotice(t("setRevoked"));
    } catch (cause) {
      if (!isCurrentScope(requestScope)) return;
      if (!isAmbiguousMutationFailure(cause))
        mutationStore.abandon(intent, handle);
      setError(cause);
    } finally {
      if (isCurrentScope(requestScope)) setBusy(false);
    }
  }

  async function saveSources(event?: React.FormEvent<HTMLFormElement>) {
    event?.preventDefault();
    if (!detail?.can_edit || detail.content_revision == null) return;
    const requestScope = workspaceScope;
    const body = {
      expected_content_revision: detail.content_revision,
      source_document_ids: sourceIds,
    };
    const intent = `knowledge-set:sources:${requestScope}:${detail.id}:${JSON.stringify(body)}`;
    const handle = mutationStore.handleFor(intent);
    setBusy(true);
    setError(null);
    setNotice("");
    try {
      const next = await api.replaceKnowledgeSetSources(detail.id, body, {
        idempotency: handle,
      });
      if (!isCurrentScope(requestScope)) return;
      mutationStore.finish(intent, handle);
      await refreshSelected(next.id);
      if (!isCurrentScope(requestScope)) return;
      updateSetInList(next);
      setNotice(t("sourcesSaved"));
    } catch (cause) {
      if (!isCurrentScope(requestScope)) return;
      if (!isAmbiguousMutationFailure(cause))
        mutationStore.abandon(intent, handle);
      setError(cause);
    } finally {
      if (isCurrentScope(requestScope)) setBusy(false);
    }
  }

  function startNewAsset() {
    selectedAssetIdRef.current = null;
    setSelectedAsset(null);
    setAssetHistory(null);
    setAssetHistoryOpen(false);
    setAssetHistoryLoading(false);
    setEditingAsset(null);
    setDraft(EMPTY_DRAFT);
    setAssetCitations([]);
  }

  function startEditAsset(asset: KnowledgeAsset) {
    selectedAssetIdRef.current = asset.id;
    setSelectedAsset(asset);
    setAssetHistory(null);
    setAssetHistoryOpen(false);
    setAssetHistoryLoading(false);
    setAssetHistoryError(false);
    if (!isFullAsset(asset)) {
      setEditingAsset(null);
      return;
    }
    const content = asset.current_version.content;
    setEditingAsset(asset);
    setTab(content.kind);
    setAssetCitations(content.citations ?? []);
    if (content.kind === "concept") {
      setDraft({
        ...EMPTY_DRAFT,
        title: content.title,
        description: content.description,
        prerequisiteIds: content.prerequisite_ids ?? [],
      });
    } else if (content.kind === "note") {
      setDraft({ ...EMPTY_DRAFT, title: content.title, body: content.body });
    } else {
      setDraft({
        ...EMPTY_DRAFT,
        prompt: content.prompt,
        referenceAnswer: content.reference_answer ?? null,
        conceptIds: content.concept_ids ?? [],
        rubricCriteria: (content.rubric.criteria ?? []).map((criterion) => ({
          label: criterion.label,
          guidance: criterion.guidance,
          points: String(criterion.points),
        })),
        rubricTotalPoints:
          content.rubric.total_points == null
            ? ""
            : String(content.rubric.total_points),
      });
    }
  }

  async function toggleAssetHistory(asset: KnowledgeAsset) {
    if (assetHistoryOpen && selectedAsset?.id === asset.id) {
      setAssetHistoryOpen(false);
      return;
    }
    selectedAssetIdRef.current = asset.id;
    setSelectedAsset(asset);
    setAssetHistoryOpen(true);
    if (assetHistory?.asset_id === asset.id) return;
    const requestScope = workspaceScope;
    setAssetHistoryLoading(true);
    setAssetHistoryError(false);
    try {
      const result = await api.knowledgeSetAssetVersions(asset.id);
      if (
        !isCurrentScope(requestScope) ||
        selectedAssetIdRef.current !== asset.id
      ) {
        return;
      }
      setAssetHistory(result);
    } catch {
      if (
        isCurrentScope(requestScope) &&
        selectedAssetIdRef.current === asset.id
      ) {
        setAssetHistoryError(true);
      }
    } finally {
      if (
        isCurrentScope(requestScope) &&
        selectedAssetIdRef.current === asset.id
      ) {
        setAssetHistoryLoading(false);
      }
    }
  }

  function currentContent(): AssetContent | null {
    const kind: AssetKind =
      editingAsset?.kind ??
      (tab === "question" || tab === "note" ? tab : "concept");
    if (kind === "concept") {
      if (!draft.title.trim()) return null;
      return {
        kind,
        title: draft.title,
        description: draft.description,
        prerequisite_ids: draft.prerequisiteIds,
        citations: assetCitations,
      };
    }
    if (kind === "note") {
      if (!draft.title.trim()) return null;
      return {
        kind,
        title: draft.title,
        body: draft.body,
        citations: assetCitations,
      };
    }
    if (!draft.prompt.trim() || draft.rubricCriteria.length === 0) return null;
    const rubricCriteria = draft.rubricCriteria.map((criterion) => {
      const points = Number(criterion.points);
      return { label: criterion.label, guidance: criterion.guidance, points };
    });
    if (
      draft.rubricCriteria.some(
        (criterion, index) =>
          !criterion.label.trim() ||
          !Number.isFinite(rubricCriteria[index]?.points) ||
          (rubricCriteria[index]?.points ?? -1) < 0,
      )
    ) {
      return null;
    }
    const totalPoints = draft.rubricTotalPoints.trim()
      ? Number(draft.rubricTotalPoints)
      : null;
    if (
      totalPoints !== null &&
      (!Number.isFinite(totalPoints) || totalPoints < 0)
    )
      return null;
    return {
      kind,
      prompt: draft.prompt,
      reference_answer: draft.referenceAnswer,
      concept_ids: draft.conceptIds,
      citations: assetCitations,
      rubric: {
        criteria: rubricCriteria,
        total_points: totalPoints,
      },
    };
  }

  async function saveAsset(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!detail?.can_edit || detail.content_revision == null) return;
    const content = currentContent();
    if (!content) return;
    const requestScope = workspaceScope;
    let body: UpdateKnowledgeAssetRequest | KnowledgeAssetRequest;
    if (editingAsset) {
      const expectedAssetVersionSeq = editingAsset.current_version_seq;
      if (expectedAssetVersionSeq == null) return;
      body = {
        expected_content_revision: detail.content_revision,
        expected_asset_version_seq: expectedAssetVersionSeq,
        content,
      };
    } else {
      body = { expected_content_revision: detail.content_revision, content };
    }
    const intent = `knowledge-asset:save:${requestScope}:${detail.id}:${editingAsset?.id ?? "new"}:${JSON.stringify(body)}`;
    const handle = mutationStore.handleFor(intent);
    setBusy(true);
    setError(null);
    setNotice("");
    try {
      if (editingAsset) {
        await api.updateKnowledgeSetAsset(
          editingAsset.id,
          body as UpdateKnowledgeAssetRequest,
          {
            idempotency: handle,
          },
        );
      } else {
        await api.createKnowledgeSetAsset(
          detail.id,
          body as KnowledgeAssetRequest,
          {
            idempotency: handle,
          },
        );
      }
      if (!isCurrentScope(requestScope)) return;
      mutationStore.finish(intent, handle);
      await refreshSelected(detail.id);
      if (!isCurrentScope(requestScope)) return;
      setNotice(t("assetSaved"));
      startNewAsset();
    } catch (cause) {
      if (!isCurrentScope(requestScope)) return;
      if (!isAmbiguousMutationFailure(cause))
        mutationStore.abandon(intent, handle);
      setError(cause);
    } finally {
      if (isCurrentScope(requestScope)) setBusy(false);
    }
  }

  async function saveAgentLinks(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!agentId || !agentKnowledge) return;
    const requestScope = workspaceScope;
    const body = {
      expected_agent_metadata_revision: agentKnowledge.agent_metadata_revision,
      set_ids: agentSetIds,
    };
    const intent = `knowledge-agent-sets:${requestScope}:${agentId}:${JSON.stringify(body)}`;
    const handle = mutationStore.handleFor(intent);
    setBusy(true);
    setAgentError(null);
    try {
      const next = await api.replaceAgentKnowledgeSets(agentId, body, {
        idempotency: handle,
      });
      if (!isCurrentScope(requestScope)) return;
      mutationStore.finish(intent, handle);
      setAgentKnowledge(next);
      setAgentSetIds(next.sets.map((row) => row.id));
      setNotice(t("setSaved"));
    } catch (cause) {
      if (!isCurrentScope(requestScope)) return;
      if (!isAmbiguousMutationFailure(cause))
        mutationStore.abandon(intent, handle);
      setAgentError(cause);
    } finally {
      if (isCurrentScope(requestScope)) setBusy(false);
    }
  }

  function toggleSource(documentId: string) {
    setSourceIds((current) =>
      current.includes(documentId)
        ? current.filter((id) => id !== documentId)
        : [...current, documentId],
    );
  }

  function toggleCitation(bindingId: string) {
    setAssetCitations((current) =>
      current.some((citation) => citation.source_binding_id === bindingId)
        ? current.filter((citation) => citation.source_binding_id !== bindingId)
        : [...current, { source_binding_id: bindingId, location: {} }],
    );
  }

  async function openGraphConcept(assetId: string) {
    const requestScope = workspaceScope;
    setGraphConceptLoading(true);
    setError(null);
    try {
      const next = await api.knowledgeSetAsset(assetId);
      if (isCurrentScope(requestScope)) setGraphConceptDetail(next);
    } catch (cause) {
      if (isCurrentScope(requestScope)) setError(cause);
    } finally {
      if (isCurrentScope(requestScope)) setGraphConceptLoading(false);
    }
  }

  if (loading) return <LoadingCard />;
  if (error && !roleCourseId && !agentId) return <ErrorNotice error={error} />;

  return (
    <div className={styles.page}>
      <PageIntro title={t("knowledge")} />
      <header className={styles.intro}>
        <div>
          <p className={styles.eyebrow}>{t("knowledge")}</p>
          <h1>{t("knowledge")}</h1>
          <p>
            {knowledgeView === "sets"
              ? t("knowledgeSetsIntro")
              : t("originalSourcesIntro")}
          </p>
        </div>
        {knowledgeView === "sets" ? (
          <div className={styles.headerActions}>
            {role === "teacher" ? (
              <Link
                className="primary-action"
                href="/teacher/agents/new?flow=ai-knowledge"
              >
                {t("createAiKnowledge")}
              </Link>
            ) : null}
            <button
              className="secondary-action"
              type="button"
              onClick={() => setShowCreate((current) => !current)}
            >
              {showCreate ? t("cancel") : t("newKnowledgeSet")}
            </button>
          </div>
        ) : null}
      </header>

      {role === "teacher" ? (
        <div className={styles.tabs} role="tablist" aria-label={t("knowledge")}>
          <button
            type="button"
            role="tab"
            aria-selected={knowledgeView === "sources"}
            className={knowledgeView === "sources" ? styles.activeTab : ""}
            onClick={() => setKnowledgeView("sources")}
          >
            {t("originalSources")}
          </button>
          <button
            type="button"
            role="tab"
            aria-selected={knowledgeView === "sets"}
            className={knowledgeView === "sets" ? styles.activeTab : ""}
            onClick={() => setKnowledgeView("sets")}
          >
            {t("knowledgeSets")}
          </button>
        </div>
      ) : null}
      {roleCourseId && availableCourses.length > 1 ? (
        <label className={styles.field}>
          <span>{t("selectCourse")}</span>
          <select
            value={selectedCourseId ?? workspaceCourseId ?? roleCourseId ?? ""}
            onChange={(event) => selectCourse(event.target.value)}
          >
            {availableCourses.map((course) => (
              <option key={course.id} value={course.id}>
                {course.name}
              </option>
            ))}
          </select>
        </label>
      ) : null}

      {role === "teacher" && knowledgeView === "sources" ? (
        <TeacherKnowledgeSources courseId={workspaceCourseId} groups={groups} />
      ) : (
        <>
          {notice ? (
            <p className={styles.notice} role="status">
              {notice}
            </p>
          ) : null}
          {generationJobId ? (
            <GenerationStatusNotice
              status={
                generationStatusSnapshot?.jobId === generationJobId
                  ? (generationStatusSnapshot.status ?? null)
                  : null
              }
              error={
                generationStatusSnapshot?.jobId === generationJobId
                  ? generationStatusSnapshot.error
                  : null
              }
              agentId={agentId}
              onRetry={() => setGenerationStatusRetry((current) => current + 1)}
            />
          ) : null}
          {error ? <ErrorNotice error={error} /> : null}

          {agentId ? (
            <SectionCard
              title={t("agentKnowledgeSets")}
              description={t("agentKnowledgeSetsLede")}
              className={styles.card}
            >
              {agentError ? <ErrorNotice error={agentError} /> : null}
              {agentKnowledge ? (
                <form className={styles.agentSetForm} onSubmit={saveAgentLinks}>
                  <div className={styles.checkList}>
                    {sets.length === 0 ? <p>{t("noResults")}</p> : null}
                    {sets.map((row) => (
                      <label className={styles.checkRow} key={row.id}>
                        <input
                          type="checkbox"
                          checked={agentSetIds.includes(row.id)}
                          onChange={() =>
                            setAgentSetIds((current) =>
                              current.includes(row.id)
                                ? current.filter((id) => id !== row.id)
                                : [...current, row.id],
                            )
                          }
                        />
                        <span>
                          <strong>{row.display_name}</strong>
                          <small>
                            {row.ownership_scope === "personal"
                              ? t("personalSet")
                              : t("groupSet")}
                          </small>
                        </span>
                      </label>
                    ))}
                  </div>
                  <button
                    className="primary-action"
                    type="submit"
                    disabled={
                      busy ||
                      (agentSetIds.length === 0 &&
                        agentKnowledge.sets.length === 0)
                    }
                  >
                    {t("saveAgentSets")}
                  </button>
                </form>
              ) : null}
            </SectionCard>
          ) : null}

          {showCreate ? (
            <SectionCard title={t("newKnowledgeSet")} className={styles.card}>
              <form className={styles.createForm} onSubmit={createSet}>
                <label className={styles.field}>
                  <span>{t("setName")}</span>
                  <input
                    autoFocus
                    value={newName}
                    onChange={(event) => setNewName(event.target.value)}
                    required
                  />
                </label>
                <label className={styles.field}>
                  <span>{t("setScope")}</span>
                  <select
                    value={newGroupId}
                    onChange={(event) => setNewGroupId(event.target.value)}
                  >
                    <option value="">{t("personalSet")}</option>
                    {groups.map((group) => (
                      <option key={group.id} value={group.id}>
                        {t("groupSet")}: {group.name}
                      </option>
                    ))}
                  </select>
                </label>
                <button
                  className="primary-action"
                  type="submit"
                  disabled={busy || !newName.trim()}
                >
                  {t("createSet")}
                </button>
              </form>
            </SectionCard>
          ) : null}

          <div className={styles.workspace}>
            <SectionCard
              title={`${t("allSets")} · ${sets.length}`}
              className={styles.listCard}
            >
              {sets.length === 0 ? (
                <EmptyCard title={t("newKnowledgeSet")}>
                  {t("knowledgeSetsIntro")}
                </EmptyCard>
              ) : (
                <ul className={styles.setList}>
                  {sets.map((row) => (
                    <li key={row.id}>
                      <button
                        type="button"
                        className={`${styles.setButton} ${row.id === selectedSetId ? styles.selected : ""}`}
                        aria-current={
                          row.id === selectedSetId ? "true" : undefined
                        }
                        onClick={() => {
                          selectSet(row.id);
                          setTab("sources");
                          setError(null);
                        }}
                      >
                        <strong>{row.display_name}</strong>
                        <span>
                          {row.ownership_scope === "personal"
                            ? t("personalSet")
                            : t("groupSet")}
                        </span>
                        <small>
                          {row.asset_count} · {row.source_count}
                        </small>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>

            <main className={styles.detail}>
              {detailLoading ? (
                <LoadingCard />
              ) : detail && currentSet ? (
                <>
                  <SectionCard className={styles.card}>
                    <div className={styles.metadataBlock}>
                      {detail.can_edit && nameEditing ? (
                        <label className={styles.nameEditor}>
                          <span>{t("setName")}</span>
                          <input
                            autoFocus
                            aria-label={t("setName")}
                            value={displayName}
                            disabled={busy}
                            onChange={(event) =>
                              setDisplayName(event.target.value)
                            }
                            onBlur={() => {
                              if (cancelNameBlur.current) {
                                cancelNameBlur.current = false;
                                return;
                              }
                              void commitSetName();
                            }}
                            onKeyDown={(event) => {
                              if (event.key === "Enter") {
                                event.preventDefault();
                                event.currentTarget.blur();
                              } else if (event.key === "Escape") {
                                event.preventDefault();
                                cancelNameBlur.current = true;
                                setDisplayName(detail.display_name);
                                setNameEditing(false);
                                event.currentTarget.blur();
                              }
                            }}
                          />
                        </label>
                      ) : (
                        <div className={styles.nameRow}>
                          <div>
                            <span className={styles.nameLabel}>
                              {t("setName")}
                            </span>
                            {detail.can_edit ? (
                              <button
                                type="button"
                                className={styles.nameButton}
                                aria-label={`${t("editSetName")}: ${detail.display_name}`}
                                onClick={() => {
                                  setDisplayName(detail.display_name);
                                  setNameEditing(true);
                                }}
                              >
                                {detail.display_name}
                              </button>
                            ) : (
                              <strong className={styles.nameValue}>
                                {detail.display_name}
                              </strong>
                            )}
                          </div>
                          {detail.can_edit ? (
                            <button
                              className="text-link danger-button"
                              type="button"
                              disabled={busy}
                              onClick={() => void revokeSet()}
                            >
                              {t("deleteSet")}
                            </button>
                          ) : null}
                        </div>
                      )}
                      {generatedByAgentId ? (
                        <Link
                          className="primary-action"
                          href={`/teacher/agents/${encodeURIComponent(generatedByAgentId)}?flow=ai-knowledge&update_set_id=${encodeURIComponent(detail.id)}`}
                        >
                          {t("updateAiKnowledge")}
                        </Link>
                      ) : null}
                      <form
                        className={styles.metadataForm}
                        onSubmit={saveMetadata}
                      >
                        <label className={styles.field}>
                          <span>{t("shareVisibility")}</span>
                          <select
                            value={visibility}
                            disabled={
                              !detail.can_edit ||
                              detail.ownership_scope !== "group" ||
                              busy
                            }
                            onChange={(event) =>
                              setVisibility(
                                event.target.value as "private" | "public",
                              )
                            }
                          >
                            <option value="private">{t("privateSet")}</option>
                            <option value="public">{t("publicSet")}</option>
                          </select>
                        </label>
                        {detail.can_edit &&
                        detail.ownership_scope === "group" ? (
                          <button
                            className="primary-action"
                            type="submit"
                            disabled={
                              busy ||
                              nameEditing ||
                              visibility === detail.visibility
                            }
                          >
                            {t("save")}
                          </button>
                        ) : null}
                      </form>
                    </div>
                  </SectionCard>
                  {detail.can_edit &&
                  detail.ownership_scope === "group" &&
                  detail.visibility === "public" &&
                  detail.asset_count > 0 ? (
                    <p className={styles.notice} role="status">
                      {t("privateVersionsShareLede")}
                    </p>
                  ) : null}

                  <SectionCard className={styles.card}>
                    <div
                      className={styles.tabs}
                      role="tablist"
                      aria-label={t("knowledgeSets")}
                    >
                      {TABS.map((item) => (
                        <button
                          key={item}
                          type="button"
                          role="tab"
                          aria-selected={tab === item}
                          className={tab === item ? styles.activeTab : ""}
                          onClick={() => {
                            setTab(item);
                            if (item === "concept") setConceptView("list");
                            startNewAsset();
                          }}
                        >
                          {labelForTab(item, t)}
                        </button>
                      ))}
                    </div>

                    {tab === "concept" ? (
                      <div
                        className={styles.conceptViews}
                        role="group"
                        aria-label={t("conceptView")}
                      >
                        <button
                          type="button"
                          aria-pressed={conceptView === "list"}
                          onClick={() => setConceptView("list")}
                        >
                          {t("conceptList")}
                        </button>
                        <button
                          type="button"
                          aria-pressed={conceptView === "graph"}
                          onClick={() => setConceptView("graph")}
                        >
                          {t("graph")}
                        </button>
                      </div>
                    ) : null}

                    {tab === "sources" ? (
                      <div className={styles.sourcePanel}>
                        <p>{t("selectSources")}</p>
                        {sourceError ? (
                          <ErrorNotice error={sourceError} />
                        ) : null}
                        {detail.sources.some((source) => !source.available) ? (
                          <p className={styles.unavailable} role="status">
                            {t("sourceUnavailable")}
                          </p>
                        ) : null}
                        {sourceDocuments.length === 0 ? (
                          <p>{t("noSetSources")}</p>
                        ) : (
                          <div className={styles.checkList}>
                            {sourceDocuments.map((document) => (
                              <label
                                className={styles.checkRow}
                                key={document.id}
                              >
                                <input
                                  type="checkbox"
                                  checked={sourceIds.includes(document.id)}
                                  disabled={!detail.can_edit || busy}
                                  onChange={() => toggleSource(document.id)}
                                />
                                <span>
                                  <strong>{document.source_filename}</strong>
                                  <small>
                                    {document.char_count} characters
                                  </small>
                                </span>
                              </label>
                            ))}
                          </div>
                        )}
                        {detail.can_edit ? (
                          <button
                            className="primary-action"
                            type="button"
                            disabled={busy}
                            onClick={() => void saveSources()}
                          >
                            {t("saveSources")}
                          </button>
                        ) : null}
                      </div>
                    ) : tab === "concept" && conceptView === "graph" ? (
                      <div className={styles.graphPanel}>
                        <p>{t("graphReadOnly")}</p>
                        {graph?.nodes.length ? (
                          <ul className={styles.graphNodes}>
                            {graph.nodes.map((node) => (
                              <li key={node.id}>
                                <button
                                  type="button"
                                  className={styles.graphNodeButton}
                                  aria-pressed={
                                    graphConceptDetail?.id === node.id ||
                                    undefined
                                  }
                                  onClick={() => void openGraphConcept(node.id)}
                                >
                                  <strong>{node.title}</strong>
                                  <span>{node.description}</span>
                                  <small>
                                    {graph.edges
                                      .filter(
                                        (edge) => edge.source_id === node.id,
                                      )
                                      .map(
                                        (edge) =>
                                          graph.nodes.find(
                                            (target) =>
                                              target.id === edge.target_id,
                                          )?.title,
                                      )
                                      .filter(Boolean)
                                      .join(" · ")}
                                  </small>
                                </button>
                              </li>
                            ))}
                          </ul>
                        ) : (
                          <EmptyCard title={t("concepts")}>
                            {t("noAssets")}
                          </EmptyCard>
                        )}
                        {graphConceptLoading ? <LoadingCard /> : null}
                        {graphConceptDetail?.audience === "full" &&
                        graphConceptDetail.current_version.content.kind ===
                          "concept" ? (
                          <article className={styles.graphDetail}>
                            <h3>
                              {graphConceptDetail.current_version.content.title}
                            </h3>
                            <p>
                              {
                                graphConceptDetail.current_version.content
                                  .description
                              }
                            </p>
                            {graphConceptDetail.current_version.content
                              .citations?.length ? (
                              <small>
                                {
                                  graphConceptDetail.current_version.content
                                    .citations.length
                                }{" "}
                                · {t("sources")}
                              </small>
                            ) : null}
                          </article>
                        ) : null}
                      </div>
                    ) : (
                      <div className={styles.assetPanel}>
                        <div className={styles.assetList}>
                          {visibleAssets.length === 0 ? (
                            <EmptyCard title={labelForTab(tab, t)}>
                              {t("noAssets")}
                            </EmptyCard>
                          ) : (
                            visibleAssets.map((asset) => {
                              const version = asset.current_version;
                              const content = version.content;
                              const title =
                                content.kind === "question"
                                  ? content.prompt
                                  : content.title;
                              const preview =
                                content.kind === "concept"
                                  ? content.description
                                  : content.kind === "note"
                                    ? content.body
                                    : "";
                              return (
                                <button
                                  className={styles.assetButton}
                                  key={asset.id}
                                  type="button"
                                  aria-current={
                                    selectedAsset?.id === asset.id
                                      ? "true"
                                      : undefined
                                  }
                                  onClick={() => startEditAsset(asset)}
                                >
                                  <strong>{title}</strong>
                                  {preview ? <span>{preview}</span> : null}
                                </button>
                              );
                            })
                          )}
                        </div>
                        {selectedAsset ? (
                          <section className={styles.assetDetails}>
                            <h3>{t("assetDetails")}</h3>
                            {!detail.can_edit ? (
                              <>
                                <strong>
                                  {selectedAsset.current_version.content
                                    .kind === "question"
                                    ? selectedAsset.current_version.content
                                        .prompt
                                    : selectedAsset.current_version.content
                                        .title}
                                </strong>
                                {selectedAsset.current_version.content.kind ===
                                "concept" ? (
                                  <p>
                                    {
                                      selectedAsset.current_version.content
                                        .description
                                    }
                                  </p>
                                ) : selectedAsset.current_version.content
                                    .kind === "note" ? (
                                  <p>
                                    {selectedAsset.current_version.content.body}
                                  </p>
                                ) : selectedAsset.audience === "full" &&
                                  selectedAsset.current_version.content
                                    .reference_answer ? (
                                  <p>
                                    {
                                      selectedAsset.current_version.content
                                        .reference_answer
                                    }
                                  </p>
                                ) : null}
                              </>
                            ) : null}
                            <button
                              type="button"
                              aria-expanded={assetHistoryOpen}
                              aria-controls={`asset-history-${selectedAsset.id}`}
                              onClick={() =>
                                void toggleAssetHistory(selectedAsset)
                              }
                            >
                              {t("history")}
                            </button>
                            {assetHistoryOpen ? (
                              <div
                                className={styles.assetHistory}
                                id={`asset-history-${selectedAsset.id}`}
                              >
                                {assetHistoryLoading ? (
                                  <p>{t("loading")}</p>
                                ) : assetHistoryError ? (
                                  <p role="alert">{t("historyLoadFailed")}</p>
                                ) : assetHistory?.versions.length ? (
                                  <ol className={styles.historyList}>
                                    {assetHistory.versions.map((version) => {
                                      const content = version.content;
                                      const citations = content.citations ?? [];
                                      const title =
                                        content.kind === "question"
                                          ? content.prompt
                                          : content.title;
                                      const sourceNames = detail.sources
                                        .filter(
                                          (source) =>
                                            source.available &&
                                            citations.some(
                                              (citation) =>
                                                citation.source_binding_id ===
                                                source.id,
                                            ),
                                        )
                                        .map((source) => source.source_filename)
                                        .filter(Boolean);
                                      return (
                                        <li key={version.id}>
                                          <strong>{title}</strong>
                                          <time dateTime={version.created_at}>
                                            {new Date(
                                              version.created_at,
                                            ).toLocaleString()}
                                          </time>
                                          {sourceNames.length ? (
                                            <small>
                                              {sourceNames.join(", ")}
                                            </small>
                                          ) : citations.length ? (
                                            <small>
                                              {t("historySources")}{" "}
                                              {citations.length}
                                            </small>
                                          ) : null}
                                        </li>
                                      );
                                    })}
                                  </ol>
                                ) : (
                                  <p>{t("noAssets")}</p>
                                )}
                              </div>
                            ) : null}
                          </section>
                        ) : null}
                        {detail.can_edit ? (
                          <div className={styles.editor}>
                            <div className={styles.editorHeader}>
                              <h3>
                                {editingAsset
                                  ? t("saveVersion")
                                  : t("addAsset")}
                              </h3>
                              {editingAsset &&
                              editingAsset.current_version_seq != null ? (
                                <span>
                                  v{editingAsset.current_version_seq} → v
                                  {editingAsset.current_version_seq + 1}
                                </span>
                              ) : null}
                            </div>
                            <form onSubmit={saveAsset}>
                              {tab === "question" ? (
                                <>
                                  <label className={styles.field}>
                                    <span>{t("prompt")}</span>
                                    <textarea
                                      value={draft.prompt}
                                      onChange={(event) =>
                                        setDraft({
                                          ...draft,
                                          prompt: event.target.value,
                                        })
                                      }
                                      required
                                      rows={4}
                                    />
                                  </label>
                                  <label className={styles.field}>
                                    <span>{t("referenceAnswer")}</span>
                                    <textarea
                                      value={draft.referenceAnswer ?? ""}
                                      onChange={(event) =>
                                        setDraft({
                                          ...draft,
                                          referenceAnswer: event.target.value,
                                        })
                                      }
                                      rows={3}
                                    />
                                  </label>
                                  <fieldset className={styles.rubric}>
                                    <legend>{t("rubric")}</legend>
                                    {draft.rubricCriteria.map(
                                      (criterion, index) => (
                                        <div
                                          className={styles.rubricCriterion}
                                          key={index}
                                        >
                                          <label className={styles.field}>
                                            <span>{t("rubricCriteria")}</span>
                                            <input
                                              value={criterion.label}
                                              onChange={(event) =>
                                                setDraft({
                                                  ...draft,
                                                  rubricCriteria:
                                                    draft.rubricCriteria.map(
                                                      (row, rowIndex) =>
                                                        rowIndex === index
                                                          ? {
                                                              ...row,
                                                              label:
                                                                event.target
                                                                  .value,
                                                            }
                                                          : row,
                                                    ),
                                                })
                                              }
                                              required
                                            />
                                          </label>
                                          <label className={styles.field}>
                                            <span>{t("description")}</span>
                                            <textarea
                                              value={criterion.guidance}
                                              onChange={(event) =>
                                                setDraft({
                                                  ...draft,
                                                  rubricCriteria:
                                                    draft.rubricCriteria.map(
                                                      (row, rowIndex) =>
                                                        rowIndex === index
                                                          ? {
                                                              ...row,
                                                              guidance:
                                                                event.target
                                                                  .value,
                                                            }
                                                          : row,
                                                    ),
                                                })
                                              }
                                              rows={3}
                                            />
                                          </label>
                                          <label className={styles.field}>
                                            <span>{t("points")}</span>
                                            <input
                                              inputMode="decimal"
                                              type="number"
                                              min="0"
                                              step="0.5"
                                              value={criterion.points}
                                              onChange={(event) =>
                                                setDraft({
                                                  ...draft,
                                                  rubricCriteria:
                                                    draft.rubricCriteria.map(
                                                      (row, rowIndex) =>
                                                        rowIndex === index
                                                          ? {
                                                              ...row,
                                                              points:
                                                                event.target
                                                                  .value,
                                                            }
                                                          : row,
                                                    ),
                                                })
                                              }
                                            />
                                          </label>
                                          {draft.rubricCriteria.length > 1 ? (
                                            <button
                                              className="text-link"
                                              type="button"
                                              onClick={() =>
                                                setDraft({
                                                  ...draft,
                                                  rubricCriteria:
                                                    draft.rubricCriteria.filter(
                                                      (_, rowIndex) =>
                                                        rowIndex !== index,
                                                    ),
                                                })
                                              }
                                            >
                                              {t("removeCriterion")}
                                            </button>
                                          ) : null}
                                        </div>
                                      ),
                                    )}
                                    <button
                                      className="text-link"
                                      type="button"
                                      onClick={() =>
                                        setDraft({
                                          ...draft,
                                          rubricCriteria: [
                                            ...draft.rubricCriteria,
                                            {
                                              label: "",
                                              guidance: "",
                                              points: "0",
                                            },
                                          ],
                                        })
                                      }
                                    >
                                      {t("addCriterion")}
                                    </button>
                                    <label className={styles.field}>
                                      <span>{t("rubricTotalPoints")}</span>
                                      <input
                                        inputMode="decimal"
                                        type="number"
                                        min="0"
                                        step="0.5"
                                        value={draft.rubricTotalPoints}
                                        onChange={(event) =>
                                          setDraft({
                                            ...draft,
                                            rubricTotalPoints:
                                              event.target.value,
                                          })
                                        }
                                      />
                                    </label>
                                  </fieldset>
                                </>
                              ) : (
                                <>
                                  <label className={styles.field}>
                                    <span>{t("assetTitle")}</span>
                                    <input
                                      value={draft.title}
                                      onChange={(event) =>
                                        setDraft({
                                          ...draft,
                                          title: event.target.value,
                                        })
                                      }
                                      required
                                    />
                                  </label>
                                  {tab === "concept" ? (
                                    <fieldset className={styles.citations}>
                                      <legend>{t("prerequisites")}</legend>
                                      {assets
                                        .filter(
                                          (asset) =>
                                            asset.kind === "concept" &&
                                            asset.id !== editingAsset?.id,
                                        )
                                        .map((asset) => {
                                          const content =
                                            asset.current_version.content;
                                          const title =
                                            content.kind === "question"
                                              ? content.prompt
                                              : content.title;
                                          return (
                                            <label
                                              className={styles.checkRow}
                                              key={asset.id}
                                            >
                                              <input
                                                type="checkbox"
                                                checked={draft.prerequisiteIds.includes(
                                                  asset.id,
                                                )}
                                                onChange={() =>
                                                  setDraft({
                                                    ...draft,
                                                    prerequisiteIds:
                                                      draft.prerequisiteIds.includes(
                                                        asset.id,
                                                      )
                                                        ? draft.prerequisiteIds.filter(
                                                            (id) =>
                                                              id !== asset.id,
                                                          )
                                                        : [
                                                            ...draft.prerequisiteIds,
                                                            asset.id,
                                                          ],
                                                  })
                                                }
                                              />
                                              <span>{title}</span>
                                            </label>
                                          );
                                        })}
                                    </fieldset>
                                  ) : null}
                                  <label className={styles.field}>
                                    <span>
                                      {tab === "note"
                                        ? t("body")
                                        : t("description")}
                                    </span>
                                    <textarea
                                      value={
                                        tab === "note"
                                          ? draft.body
                                          : draft.description
                                      }
                                      onChange={(event) =>
                                        setDraft({
                                          ...draft,
                                          [tab === "note"
                                            ? "body"
                                            : "description"]:
                                            event.target.value,
                                        })
                                      }
                                      rows={5}
                                    />
                                  </label>
                                </>
                              )}
                              {tab === "question" &&
                              assets.some(
                                (asset) => asset.kind === "concept",
                              ) ? (
                                <fieldset className={styles.citations}>
                                  <legend>{t("conceptLinks")}</legend>
                                  {assets
                                    .filter((asset) => asset.kind === "concept")
                                    .map((asset) => {
                                      const content =
                                        asset.current_version.content;
                                      const title =
                                        content.kind === "question"
                                          ? content.prompt
                                          : content.title;
                                      return (
                                        <label
                                          className={styles.checkRow}
                                          key={asset.id}
                                        >
                                          <input
                                            type="checkbox"
                                            checked={draft.conceptIds.includes(
                                              asset.id,
                                            )}
                                            onChange={() =>
                                              setDraft({
                                                ...draft,
                                                conceptIds:
                                                  draft.conceptIds.includes(
                                                    asset.id,
                                                  )
                                                    ? draft.conceptIds.filter(
                                                        (id) => id !== asset.id,
                                                      )
                                                    : [
                                                        ...draft.conceptIds,
                                                        asset.id,
                                                      ],
                                              })
                                            }
                                          />
                                          <span>{title}</span>
                                        </label>
                                      );
                                    })}
                                </fieldset>
                              ) : null}
                              {detail.sources.some(
                                (source) => source.available,
                              ) ? (
                                <fieldset className={styles.citations}>
                                  <legend>{t("sources")}</legend>
                                  {detail.sources
                                    .filter((source) => source.available)
                                    .map((source) => (
                                      <label
                                        className={styles.checkRow}
                                        key={source.id}
                                      >
                                        <input
                                          type="checkbox"
                                          checked={assetCitations.some(
                                            (citation) =>
                                              citation.source_binding_id ===
                                              source.id,
                                          )}
                                          onChange={() =>
                                            toggleCitation(source.id)
                                          }
                                        />
                                        <span>{source.source_filename}</span>
                                      </label>
                                    ))}
                                </fieldset>
                              ) : null}
                              <button
                                className="primary-action"
                                type="submit"
                                disabled={busy || !currentContent()}
                              >
                                {editingAsset
                                  ? t("saveVersion")
                                  : t("addAsset")}
                              </button>
                            </form>
                          </div>
                        ) : null}
                      </div>
                    )}
                  </SectionCard>
                </>
              ) : (
                <EmptyCard title={t("selectSet")}>
                  {t("knowledgeSetsIntro")}
                </EmptyCard>
              )}
            </main>
          </div>
        </>
      )}
    </div>
  );
}
