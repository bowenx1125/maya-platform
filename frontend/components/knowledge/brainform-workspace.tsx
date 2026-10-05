"use client";

import { useRouter } from "next/navigation";
import Link from "next/link";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";

import {
  isAmbiguousMutationFailure,
  isConflict,
  type BrainformKnowledge,
  type ChatAgent,
  type Group,
  type KnowledgeDocument,
  type KnowledgeGenerationStatus,
  type KnowledgeMarkdown,
  type MemoryEntrySource,
  type MayaTeamDirectoryDto,
  type TeamSummaryDto,
} from "../../lib/api";
import { useIdempotencyStore } from "../../lib/idempotency";
import { useT } from "../locale";
import { useSession } from "../session-provider";
import { WorkspaceAction } from "../workspace-actions";
import { ErrorNotice, LoadingCard } from "../ui";
import { ReportMarkdown } from "../report/report-markdown";
import {
  IconArrowRight,
  IconClose,
  IconEdit,
  IconEye,
  IconRefresh,
} from "../quiet-icons";

import styles from "./brainform-workspace.module.css";

type BrainformRole = "teacher" | "student";

type RagDraft = {
  filename: string;
  markdown: string;
  isNew: boolean;
  documentId?: string;
  groupId?: string;
  expectedContentHash?: string;
  expectedIndexRevision?: number;
  originalFilename?: string;
  originalMarkdown?: string;
  canEdit?: boolean;
};

type KnowledgeDraft = { markdown: string; expectedVersionSeq: number };

type BrainformMemoryItem = {
  source: MemoryEntrySource;
  name: string;
  detail: string;
  label:
    "brainformMemoryAgent" | "brainformMemoryTeam" | "brainformMemoryMayaTeam";
};

type Pane =
  | { kind: "rag-edit"; draftKey: string }
  | { kind: "rag-view"; documentId: string; markdown: string; filename: string }
  | { kind: "knowledge-view"; documentId: string }
  | { kind: "knowledge-edit"; documentId: string };

type PendingGeneration = {
  documentId: string;
  actionId: string;
};

type KnowledgeGraphEdge = { from: string; to: string };
type ParsedKnowledgeGraph = {
  edges: KnowledgeGraphEdge[];
  nodes: string[];
  markdownWithoutGraph: string;
};

function parseKnowledgeGraph(markdown: string): ParsedKnowledgeGraph | null {
  const lines = markdown.split("\n");
  const headings: Array<{ index: number; level: number; title: string }> = [];
  let fence: { marker: string; size: number } | null = null;
  lines.forEach((line, index) => {
    const fenceMatch = line.match(/^\s{0,3}(`{3,}|~{3,})/);
    if (fence) {
      if (
        fenceMatch &&
        fenceMatch[1][0] === fence.marker &&
        fenceMatch[1].length >= fence.size &&
        line.slice(fenceMatch[0].length).trim() === ""
      ) {
        fence = null;
      }
      return;
    }
    if (fenceMatch) {
      fence = { marker: fenceMatch[1][0], size: fenceMatch[1].length };
      return;
    }
    const heading = line.match(/^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$/);
    if (heading) {
      headings.push({
        index,
        level: heading[1].length,
        title: heading[2].trim(),
      });
    }
  });
  const graphSections = headings.filter(
    (heading) => heading.level === 2 && heading.title.toLowerCase() === "graph",
  );
  if (graphSections.length !== 1) return null;
  const start = graphSections[0].index;
  const end =
    headings.find((heading) => heading.index > start && heading.level === 2)
      ?.index ?? lines.length;
  const edges: KnowledgeGraphEdge[] = [];
  const nodeSet = new Set<string>();
  for (const line of lines.slice(start + 1, end)) {
    const value = line.trim();
    if (!value) continue;
    const edge = value.match(/^-\s+(.+?)\s+→\s+(.+?)\s*$/);
    if (!edge || edges.length >= 80) return null;
    const from = edge[1].trim();
    const to = edge[2].trim();
    if (!from || !to || from.length > 100 || to.length > 100) return null;
    edges.push({ from, to });
    nodeSet.add(from);
    nodeSet.add(to);
    if (nodeSet.size > 40) return null;
  }
  if (edges.length === 0) return null;
  const updatedLines = [...lines.slice(0, start), ...lines.slice(end)];
  return {
    edges,
    nodes: [...nodeSet],
    markdownWithoutGraph: updatedLines.join("\n").trim(),
  };
}

function KnowledgeMarkdownView({
  markdown,
  graphLabel,
}: {
  markdown: string;
  graphLabel: string;
}) {
  const graph = parseKnowledgeGraph(markdown);
  const titleId = useId();
  const descriptionId = useId();
  if (!graph) return <ReportMarkdown>{markdown}</ReportMarkdown>;

  const columns = 3;
  const nodeWidth = 190;
  const rowHeight = 94;
  const columnGap = 42;
  const nodePositions = new Map(
    graph.nodes.map((node, index) => [
      node,
      {
        x: 20 + (index % columns) * (nodeWidth + columnGap),
        y: 22 + Math.floor(index / columns) * rowHeight,
      },
    ]),
  );
  const rows = Math.ceil(graph.nodes.length / columns);
  const width = columns * nodeWidth + (columns - 1) * columnGap + 40;
  const height = rows * rowHeight + 14;
  return (
    <>
      {graph.markdownWithoutGraph ? (
        <ReportMarkdown>{graph.markdownWithoutGraph}</ReportMarkdown>
      ) : null}
      <figure className={styles.graphFigure}>
        <div className={styles.graphScroll}>
          <svg
            className={styles.graphSvg}
            role="img"
            aria-labelledby={`${titleId} ${descriptionId}`}
            viewBox={`0 0 ${width} ${height}`}
          >
            <title id={titleId}>{graphLabel}</title>
            <desc id={descriptionId}>
              {graph.edges
                .map((edge) => `${edge.from} → ${edge.to}`)
                .join(". ")}
            </desc>
            <defs>
              <marker
                id="brainform-graph-arrow"
                markerWidth="9"
                markerHeight="8"
                refX="8"
                refY="4"
                orient="auto"
                markerUnits="strokeWidth"
              >
                <path d="M0,0 L9,4 L0,8 z" fill="#806b45" />
              </marker>
            </defs>
            {graph.edges.map((edge, index) => {
              const from = nodePositions.get(edge.from);
              const to = nodePositions.get(edge.to);
              if (!from || !to) return null;
              const fromX = from.x + nodeWidth;
              const fromY = from.y + 29;
              const toX = to.x;
              const toY = to.y + 29;
              return (
                <path
                  key={`${edge.from}-${edge.to}-${index}`}
                  className={styles.graphEdge}
                  d={`M ${fromX} ${fromY} C ${fromX + 30} ${fromY}, ${toX - 30} ${toY}, ${toX} ${toY}`}
                  markerEnd="url(#brainform-graph-arrow)"
                />
              );
            })}
            {graph.nodes.map((node) => {
              const position = nodePositions.get(node);
              if (!position) return null;
              return (
                <g key={node}>
                  <rect
                    className={styles.graphNode}
                    x={position.x}
                    y={position.y}
                    width={nodeWidth}
                    height="58"
                    rx="12"
                  />
                  <text
                    className={styles.graphLabel}
                    x={position.x + nodeWidth / 2}
                    y={position.y + 29}
                    textAnchor="middle"
                    dominantBaseline="middle"
                  >
                    {node}
                  </text>
                </g>
              );
            })}
          </svg>
        </div>
      </figure>
    </>
  );
}

const ragDraftsByScope = new Map<string, Record<string, RagDraft>>();
const knowledgeDraftsByScope = new Map<
  string,
  Record<string, KnowledgeDraft>
>();
const generationJobsByScope = new Map<string, Record<string, string>>();

function createUuid(): string {
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.randomUUID === "function"
  ) {
    return crypto.randomUUID();
  }
  const bytes = new Uint8Array(16);
  if (
    typeof crypto !== "undefined" &&
    typeof crypto.getRandomValues === "function"
  ) {
    crypto.getRandomValues(bytes);
  } else {
    bytes.forEach((_, index) => {
      bytes[index] = Math.floor(Math.random() * 256);
    });
  }
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = [...bytes].map((byte) => byte.toString(16).padStart(2, "0"));
  return `${hex.slice(0, 4).join("")}-${hex.slice(4, 6).join("")}-${hex.slice(6, 8).join("")}-${hex.slice(8, 10).join("")}-${hex.slice(10).join("")}`;
}

function getRagDrafts(scope: string): Record<string, RagDraft> {
  return ragDraftsByScope.get(scope) ?? {};
}

function rememberRagDrafts(scope: string, drafts: Record<string, RagDraft>) {
  ragDraftsByScope.set(scope, drafts);
}

function getKnowledgeDrafts(scope: string): Record<string, KnowledgeDraft> {
  return knowledgeDraftsByScope.get(scope) ?? {};
}

function rememberKnowledgeDrafts(
  scope: string,
  drafts: Record<string, KnowledgeDraft>,
) {
  knowledgeDraftsByScope.set(scope, drafts);
}

function generationStorageKey(scope: string, setId: string): string {
  let stableScope = scope;
  try {
    const parsed: unknown = JSON.parse(scope);
    if (Array.isArray(parsed) && parsed.length >= 3) {
      stableScope = JSON.stringify(parsed.slice(0, 3));
    }
  } catch {
    // Keep the opaque scope key if it is not the workspace tuple.
  }
  return `maya:brainform-generation-job:${stableScope}:${setId}`;
}

function getGenerationJobs(scope: string): Record<string, string> {
  return generationJobsByScope.get(scope) ?? {};
}

function rememberGenerationJobs(scope: string, jobs: Record<string, string>) {
  generationJobsByScope.set(scope, jobs);
  for (const [setId, jobId] of Object.entries(jobs)) {
    try {
      window.sessionStorage.setItem(generationStorageKey(scope, setId), jobId);
    } catch {
      // The owner-only Job route remains available for the current page session.
    }
  }
}

function readStoredGenerationJob(scope: string, setId: string): string | null {
  const inMemory = getGenerationJobs(scope)[setId];
  if (inMemory) return inMemory;
  try {
    return window.sessionStorage.getItem(generationStorageKey(scope, setId));
  } catch {
    return null;
  }
}

function isGenerationActive(
  state: BrainformKnowledge["generation_state"],
): boolean {
  return state === "pending" || state === "running";
}

function indexStatusText(
  document: KnowledgeDocument,
  t: ReturnType<typeof useT>,
) {
  if (
    document.index_status === "pending" ||
    document.index_status === "indexing"
  ) {
    return t("brainformRagIndexing");
  }
  if (document.index_status === "failed") {
    return t("brainformRagIndexFailed");
  }
  return "";
}

export function BrainformWorkspace({
  role,
  initialAgentId,
  initialSetId,
  initialCourseId,
  initialJobId,
}: {
  role: BrainformRole;
  initialAgentId?: string;
  initialSetId?: string;
  initialCourseId?: string;
  initialJobId?: string;
}) {
  const { api, identityGeneration, user } = useSession();
  const roleCourseIds = useMemo(
    () =>
      (user?.courses ?? [])
        .filter((membership) => membership.role === role)
        .map((membership) => membership.course_id),
    [role, user?.courses],
  );
  const defaultCourseId =
    (initialCourseId && roleCourseIds.includes(initialCourseId)
      ? initialCourseId
      : undefined) ?? roleCourseIds[0];
  const [selectedCourseId, setSelectedCourseId] = useState(
    defaultCourseId ?? "",
  );
  const courseId =
    selectedCourseId && roleCourseIds.includes(selectedCourseId)
      ? selectedCourseId
      : (defaultCourseId ?? "");
  const dataScope = JSON.stringify([
    user?.id ?? null,
    role,
    courseId,
    identityGeneration,
  ]);

  return (
    <BrainformWorkspaceBody
      key={dataScope}
      role={role}
      courseIds={roleCourseIds}
      courseId={courseId}
      onCourseChange={setSelectedCourseId}
      initialAgentId={initialAgentId}
      initialSetId={initialSetId}
      initialJobId={initialJobId}
      identityScope={dataScope}
      ragDraftScope={JSON.stringify([user?.id ?? null, role, selectedCourseId])}
    />
  );
}

function BrainformWorkspaceBody({
  role,
  courseIds,
  courseId,
  onCourseChange,
  initialAgentId,
  initialSetId,
  initialJobId,
  identityScope,
  ragDraftScope,
}: {
  role: BrainformRole;
  courseIds: string[];
  courseId: string;
  onCourseChange: (courseId: string) => void;
  initialAgentId?: string;
  initialSetId?: string;
  initialJobId?: string;
  identityScope: string;
  ragDraftScope: string;
}) {
  const t = useT();
  const router = useRouter();
  const { api, user } = useSession();
  const mutationStore = useIdempotencyStore();
  const [courseNames, setCourseNames] = useState<Record<string, string>>({});
  const [ragDocuments, setRagDocuments] = useState<KnowledgeDocument[]>([]);
  const [knowledgeRows, setKnowledgeRows] = useState<BrainformKnowledge[]>([]);
  const [chatAgents, setChatAgents] = useState<ChatAgent[]>([]);
  const [teams, setTeams] = useState<TeamSummaryDto[]>([]);
  const [mayaTeams, setMayaTeams] = useState<MayaTeamDirectoryDto[]>([]);
  const [groups, setGroups] = useState<Group[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<unknown>(null);
  const [notice, setNotice] = useState("");
  const [pane, setPane] = useState<Pane | null>(null);
  const [ragDrafts, setRagDrafts] = useState<Record<string, RagDraft>>(() =>
    getRagDrafts(ragDraftScope),
  );
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [markdown, setMarkdown] = useState<KnowledgeMarkdown | null>(null);
  const [markdownDraft, setMarkdownDraft] = useState("");
  const [knowledgeDrafts, setKnowledgeDrafts] = useState<
    Record<string, KnowledgeDraft>
  >(() => getKnowledgeDrafts(identityScope));
  const [generationJobs, setGenerationJobs] = useState<Record<string, string>>(
    () => getGenerationJobs(identityScope),
  );
  const [generationStatuses, setGenerationStatuses] = useState<
    Record<string, KnowledgeGenerationStatus>
  >({});
  const [generationRetry, setGenerationRetry] =
    useState<PendingGeneration | null>(null);
  const [renameSetId, setRenameSetId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const currentScope = useRef(identityScope);
  const loadSequence = useRef(0);
  const operationSequence = useRef(0);
  const renameInputRef = useRef<HTMLInputElement>(null);
  const initialKnowledgeOpened = useRef(false);
  const initialJobRead = useRef<string | null>(null);

  useEffect(() => {
    currentScope.current = identityScope;
    return () => {
      currentScope.current = "";
    };
  }, [identityScope]);

  const scopeIsCurrent = useCallback(
    (scope = identityScope) => currentScope.current === scope,
    [identityScope],
  );

  const loadRagDocuments = useCallback(
    async (activeCourseId: string) => {
      if (role === "teacher") return api.workspaceDocuments(activeCourseId);
      const joinedGroupIds = [
        ...new Set((user?.groups ?? []).map((group) => group.group_id)),
      ];
      const groupRows = await Promise.allSettled(
        joinedGroupIds.map((groupId) => api.group(groupId)),
      );
      const currentCourseGroups = groupRows.flatMap((result) =>
        result.status === "fulfilled" &&
        result.value.course_id === activeCourseId
          ? [result.value]
          : [],
      );
      const documentRows = await Promise.allSettled(
        currentCourseGroups.map((group) => api.knowledge(group.id)),
      );
      const byId = new Map<string, KnowledgeDocument>();
      for (const result of documentRows) {
        if (result.status !== "fulfilled") continue;
        for (const document of result.value) byId.set(document.id, document);
      }
      return [...byId.values()];
    },
    [api, role, user?.groups],
  );

  const loadGroups = useCallback(
    async (activeCourseId: string) => {
      if (role === "teacher") return api.groups(activeCourseId);
      const groupIds = [
        ...new Set((user?.groups ?? []).map((group) => group.group_id)),
      ];
      const results = await Promise.allSettled(
        groupIds.map((groupId) => api.group(groupId)),
      );
      return results.flatMap((result) =>
        result.status === "fulfilled" &&
        result.value.course_id === activeCourseId
          ? [result.value]
          : [],
      );
    },
    [api, role, user?.groups],
  );

  const loadWorkspace = useCallback(async () => {
    const scope = identityScope;
    const sequence = ++loadSequence.current;
    if (!courseId) {
      setRagDocuments([]);
      setKnowledgeRows([]);
      setChatAgents([]);
      setGroups([]);
      setLoading(false);
      setLoadError(null);
      return;
    }
    setLoading(true);
    setLoadError(null);
    try {
      const [
        courseRows,
        nextRag,
        nextKnowledge,
        nextAgents,
        nextGroups,
        nextTeams,
        nextMayaTeams,
      ] = await Promise.all([
        api.courses(),
        loadRagDocuments(courseId),
        api.brainformKnowledge(courseId),
        api.chatAgents(courseId),
        loadGroups(courseId),
        typeof api.teams === "function"
          ? api.teams(courseId).catch(() => [])
          : Promise.resolve([]),
        typeof api.mayaTeams === "function"
          ? api.mayaTeams(courseId).catch(() => [])
          : Promise.resolve([]),
      ]);
      if (!scopeIsCurrent(scope) || sequence !== loadSequence.current) return;
      const accessibleCourseNames = Object.fromEntries(
        courseRows
          .filter((course) => courseIds.includes(course.id))
          .map((course) => [course.id, course.name]),
      );
      setCourseNames(accessibleCourseNames);
      setRagDocuments(nextRag);
      setKnowledgeRows(nextKnowledge);
      setChatAgents(nextAgents);
      setGroups(nextGroups);
      setTeams(nextTeams);
      setMayaTeams(nextMayaTeams);
      const restoredJobs = { ...getGenerationJobs(scope) };
      for (const row of nextKnowledge) {
        if (!row.can_edit || restoredJobs[row.canonical_set_id]) continue;
        const jobId = readStoredGenerationJob(scope, row.canonical_set_id);
        if (jobId) restoredJobs[row.canonical_set_id] = jobId;
      }
      const previousJobs = getGenerationJobs(scope);
      const jobsChanged = Object.entries(restoredJobs).some(
        ([setId, jobId]) => previousJobs[setId] !== jobId,
      );
      if (jobsChanged) {
        rememberGenerationJobs(scope, restoredJobs);
        setGenerationJobs(restoredJobs);
      }
      setNotice("");
    } catch (cause) {
      if (scopeIsCurrent(scope) && sequence === loadSequence.current) {
        setLoadError(cause);
      }
    } finally {
      if (scopeIsCurrent(scope) && sequence === loadSequence.current) {
        setLoading(false);
      }
    }
  }, [
    api,
    courseId,
    courseIds,
    identityScope,
    loadGroups,
    loadRagDocuments,
    scopeIsCurrent,
  ]);

  useEffect(() => {
    const timer = window.setTimeout(() => void loadWorkspace(), 0);
    return () => window.clearTimeout(timer);
  }, [loadWorkspace]);

  useEffect(() => {
    if (!knowledgeRows.some((row) => isGenerationActive(row.generation_state)))
      return;
    const scope = identityScope;
    const timer = window.setTimeout(() => {
      if (scopeIsCurrent(scope)) void loadWorkspace();
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [identityScope, knowledgeRows, loadWorkspace, scopeIsCurrent]);

  useEffect(() => {
    if (!renameSetId) return;
    renameInputRef.current?.focus();
    renameInputRef.current?.select();
  }, [renameSetId]);

  useEffect(() => {
    if (loading || initialKnowledgeOpened.current) return;
    const row = initialSetId
      ? knowledgeRows.find((item) => item.canonical_set_id === initialSetId)
      : initialAgentId
        ? knowledgeRows.find((item) => item.agent_id === initialAgentId)
        : undefined;
    if (!row || row.version_seq == null) return;
    initialKnowledgeOpened.current = true;
    void openKnowledge(row, "view");
    // Opening is intentionally one-shot for a routed canonical document.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [initialAgentId, initialSetId, knowledgeRows, loading]);

  useEffect(() => {
    if (
      role !== "teacher" ||
      !initialJobId ||
      initialJobRead.current === initialJobId
    )
      return;
    initialJobRead.current = initialJobId;
    const scope = identityScope;
    void api
      .knowledgeGenerationJob(initialJobId)
      .then((status) => {
        if (!scopeIsCurrent(scope)) return;
        setGenerationStatuses((current) => ({
          ...current,
          [status.knowledge_set_id]: status,
        }));
        setGenerationJobs((current) => {
          const next = { ...current, [status.knowledge_set_id]: status.job_id };
          rememberGenerationJobs(scope, next);
          return next;
        });
      })
      .catch(() => {
        // The owner-only Job endpoint decides whether a routed job is visible.
      });
  }, [api, identityScope, initialJobId, role, scopeIsCurrent]);

  useEffect(() => {
    if (role !== "teacher") return;
    let active = true;
    const timers = new Set<number>();
    const poll = async (setId: string, jobId: string) => {
      try {
        const status = await api.knowledgeGenerationJob(jobId);
        if (!active || !scopeIsCurrent()) return;
        setGenerationStatuses((current) => ({ ...current, [setId]: status }));
        if (status.state === "pending" || status.state === "running") {
          const timer = window.setTimeout(() => {
            timers.delete(timer);
            void poll(setId, jobId);
          }, 1500);
          timers.add(timer);
        }
      } catch {
        // No manifest or foreign Job status is inferred from an unreadable Job.
      }
    };
    for (const [setId, jobId] of Object.entries(generationJobs))
      void poll(setId, jobId);
    return () => {
      active = false;
      for (const timer of timers) window.clearTimeout(timer);
    };
  }, [api, generationJobs, role, scopeIsCurrent]);

  const closePane = useCallback(() => {
    operationSequence.current += 1;
    setBusyKey((current) => (current?.startsWith("import:") ? null : current));
    setPane(null);
    setMarkdown(null);
    setNotice("");
  }, []);

  function saveRagDrafts(next: Record<string, RagDraft>) {
    rememberRagDrafts(ragDraftScope, next);
    setRagDrafts(next);
  }

  function startNewRag() {
    operationSequence.current += 1;
    setBusyKey((current) => (current?.startsWith("import:") ? null : current));
    const draftKey = `new:${createUuid()}`;
    saveRagDrafts({
      ...ragDrafts,
      [draftKey]: {
        filename: "notes.md",
        markdown: "",
        isNew: true,
        groupId: role === "student" ? groups[0]?.id : undefined,
      },
    });
    setPane({ kind: "rag-edit", draftKey });
    setNotice("");
  }

  async function importRag(draftKey: string, file: File) {
    const draft = ragDrafts[draftKey];
    if (!draft?.isNew || busyKey) return;
    if (!file.name.toLowerCase().endsWith(".md")) {
      setNotice(t("brainformMarkdownRequired"));
      return;
    }
    const scope = identityScope;
    const sequence = ++operationSequence.current;
    setBusyKey(`import:${draftKey}`);
    setLoadError(null);
    setNotice("");
    try {
      const content = new TextDecoder("utf-8", { fatal: true }).decode(
        await file.arrayBuffer(),
      );
      if (!scopeIsCurrent(scope) || sequence !== operationSequence.current)
        return;
      if (!content.trim()) {
        setNotice(t("brainformMarkdownRequired"));
        return;
      }
      saveRagDrafts({
        ...ragDrafts,
        [draftKey]: { ...draft, filename: file.name, markdown: content },
      });
    } catch {
      if (scopeIsCurrent(scope) && sequence === operationSequence.current) {
        setNotice(t("brainformMarkdownRequired"));
      }
    } finally {
      if (scopeIsCurrent(scope) && sequence === operationSequence.current) {
        setBusyKey(null);
      }
    }
  }

  async function editRag(document: KnowledgeDocument) {
    const draftKey = `document:${document.id}`;
    const existing = ragDrafts[draftKey];
    if (existing) {
      setPane({ kind: "rag-edit", draftKey });
      setNotice("");
      return;
    }
    const scope = identityScope;
    const sequence = ++operationSequence.current;
    setBusyKey(`read:${document.id}`);
    setNotice("");
    try {
      const downloaded = await api.downloadKnowledge(document.id);
      if (!scopeIsCurrent(scope) || sequence !== operationSequence.current)
        return;
      const draft: RagDraft = {
        filename: document.source_filename,
        markdown: downloaded.content,
        isNew: false,
        documentId: document.id,
        groupId: document.group_id ?? undefined,
        expectedContentHash: document.content_hash,
        expectedIndexRevision: document.index_revision,
        originalFilename: downloaded.filename || document.source_filename,
        originalMarkdown: downloaded.content,
        canEdit: document.can_manage_visibility,
      };
      saveRagDrafts({ ...ragDrafts, [draftKey]: draft });
      setPane({ kind: "rag-edit", draftKey });
    } catch (cause) {
      if (scopeIsCurrent(scope) && sequence === operationSequence.current) {
        setLoadError(cause);
      }
    } finally {
      if (scopeIsCurrent(scope) && sequence === operationSequence.current) {
        setBusyKey(null);
      }
    }
  }

  async function viewRag(document: KnowledgeDocument) {
    const scope = identityScope;
    const sequence = ++operationSequence.current;
    setBusyKey(`view:${document.id}`);
    setLoadError(null);
    setNotice("");
    try {
      const downloaded = await api.downloadKnowledge(document.id);
      if (!scopeIsCurrent(scope) || sequence !== operationSequence.current)
        return;
      setPane({
        kind: "rag-view",
        documentId: document.id,
        markdown: downloaded.content,
        filename: downloaded.filename || document.source_filename,
      });
    } catch (cause) {
      if (scopeIsCurrent(scope) && sequence === operationSequence.current) {
        setLoadError(cause);
      }
    } finally {
      if (scopeIsCurrent(scope) && sequence === operationSequence.current) {
        setBusyKey(null);
      }
    }
  }

  async function createRag(draftKey: string) {
    const draft = ragDrafts[draftKey];
    if (!draft || !courseId || busyKey) return;
    const filename = draft.filename.trim();
    if (!filename.toLowerCase().endsWith(".md") || !draft.markdown.trim()) {
      setNotice(t("brainformMarkdownRequired"));
      return;
    }
    const intent = `brainform-create:${ragDraftScope}:${draftKey}`;
    const handle = mutationStore.handleFor(intent);
    setBusyKey(draftKey);
    setLoadError(null);
    setNotice("");
    try {
      const file = new File([draft.markdown], filename, {
        type: "text/markdown",
      });
      const mutation =
        role === "teacher"
          ? await api.createWorkspaceKnowledge(courseId, file, {
              idempotency: handle,
            })
          : draft.groupId
            ? await api.createLibraryKnowledge(draft.groupId, file, {
                idempotency: handle,
              })
            : (() => {
                throw new Error(t("brainformChooseGroup"));
              })();
      mutationStore.finish(intent, handle);
      if (!scopeIsCurrent()) return;
      const nextDrafts = { ...ragDrafts };
      delete nextDrafts[draftKey];
      saveRagDrafts(nextDrafts);
      setRagDocuments((current) => [...current, mutation.document]);
      setPane(null);
      setNotice(t("brainformRagSaved"));
      void loadWorkspace();
    } catch (cause) {
      if (isAmbiguousMutationFailure(cause)) {
        setNotice(t("brainformRetrySameSave"));
      } else {
        mutationStore.abandon(intent, handle);
      }
      if (scopeIsCurrent()) setLoadError(cause);
    } finally {
      if (scopeIsCurrent()) setBusyKey(null);
    }
  }

  async function saveRag(draftKey: string) {
    const draft = ragDrafts[draftKey];
    if (
      !draft ||
      draft.isNew ||
      !draft.documentId ||
      !draft.canEdit ||
      !draft.expectedContentHash ||
      draft.expectedIndexRevision === undefined ||
      busyKey
    )
      return;
    const filename = draft.filename.trim();
    const contentChanged = draft.markdown !== draft.originalMarkdown;
    const filenameChanged = filename !== draft.originalFilename;
    if (filenameChanged && !filename.toLowerCase().endsWith(".md")) {
      setNotice(t("brainformMarkdownRequired"));
      return;
    }
    if (contentChanged && !draft.markdown.trim()) {
      setNotice(t("brainformMarkdownRequired"));
      return;
    }
    if (!filenameChanged && !contentChanged) {
      setNotice(t("brainformRagSaved"));
      return;
    }
    const renameOnly = filenameChanged && !contentChanged;
    const intent = renameOnly
      ? `brainform-rename:${draft.documentId}:${draft.originalFilename}:${filename}`
      : `brainform-replace:${draft.documentId}:${draft.expectedContentHash}:${draft.expectedIndexRevision}`;
    const handle = mutationStore.handleFor(intent);
    setBusyKey(draftKey);
    setLoadError(null);
    setNotice("");
    try {
      const next = renameOnly
        ? await api.renameKnowledgeDocument(
            draft.documentId,
            {
              expected_filename: draft.originalFilename ?? draft.filename,
              filename,
            },
            { idempotency: handle },
          )
        : await api.replaceKnowledgeDocument(
            draft.documentId,
            new File([draft.markdown], filename, { type: "text/markdown" }),
            draft.expectedContentHash,
            draft.expectedIndexRevision,
            { idempotency: handle },
          );
      mutationStore.finish(intent, handle);
      if (!scopeIsCurrent()) return;
      saveRagDrafts({
        ...ragDrafts,
        [draftKey]: {
          ...draft,
          filename: next.source_filename,
          originalFilename: next.source_filename,
          originalMarkdown: draft.markdown,
          expectedContentHash: next.content_hash,
          expectedIndexRevision: next.index_revision,
        },
      });
      setRagDocuments((current) =>
        current.map((document) => (document.id === next.id ? next : document)),
      );
      setNotice(renameOnly ? t("brainformRagRenamed") : t("brainformRagSaved"));
      void loadWorkspace();
    } catch (cause) {
      if (isConflict(cause)) {
        mutationStore.abandon(intent, handle);
        setNotice(t("brainformRagConflictDraftKept"));
        void loadWorkspace();
      } else if (isAmbiguousMutationFailure(cause)) {
        setNotice(t("brainformRetrySameSave"));
      } else {
        mutationStore.abandon(intent, handle);
      }
      if (scopeIsCurrent()) setLoadError(cause);
    } finally {
      if (scopeIsCurrent()) setBusyKey(null);
    }
  }

  async function openKnowledge(row: BrainformKnowledge, mode: "view" | "edit") {
    const scope = identityScope;
    const sequence = ++operationSequence.current;
    setBusyKey(`knowledge:${row.canonical_set_id}`);
    setLoadError(null);
    setNotice("");
    try {
      const next = await api.knowledgeMarkdown(row.canonical_set_id);
      if (!scopeIsCurrent(scope) || sequence !== operationSequence.current)
        return;
      setMarkdown(next);
      if (mode === "edit") {
        const draft = knowledgeDrafts[row.canonical_set_id] ?? {
          markdown: next.markdown,
          expectedVersionSeq: next.version_seq,
        };
        if (!knowledgeDrafts[row.canonical_set_id]) {
          const nextDrafts = {
            ...knowledgeDrafts,
            [row.canonical_set_id]: draft,
          };
          rememberKnowledgeDrafts(identityScope, nextDrafts);
          setKnowledgeDrafts(nextDrafts);
        }
        setMarkdownDraft(draft.markdown);
      }
      setPane({
        kind: mode === "view" ? "knowledge-view" : "knowledge-edit",
        documentId: row.canonical_set_id,
      });
    } catch (cause) {
      if (scopeIsCurrent(scope) && sequence === operationSequence.current) {
        setLoadError(cause);
      }
    } finally {
      if (scopeIsCurrent(scope) && sequence === operationSequence.current) {
        setBusyKey(null);
      }
    }
  }

  async function saveKnowledge() {
    if (!markdown?.can_edit || busyKey) return;
    const setId = markdown.canonical_set_id;
    const draft = knowledgeDrafts[setId] ?? {
      markdown: markdownDraft,
      expectedVersionSeq: markdown.version_seq,
    };
    const intent = `brainform-markdown:${setId}:${draft.expectedVersionSeq}`;
    const handle = mutationStore.handleFor(intent);
    setBusyKey(`knowledge-save:${setId}`);
    setLoadError(null);
    setNotice("");
    try {
      const next = await api.saveKnowledgeMarkdown(
        setId,
        {
          expected_version_seq: draft.expectedVersionSeq,
          markdown: markdownDraft,
        },
        { idempotency: handle },
      );
      mutationStore.finish(intent, handle);
      if (!scopeIsCurrent()) return;
      setMarkdown(next);
      setMarkdownDraft(next.markdown);
      const nextDrafts = {
        ...knowledgeDrafts,
        [setId]: {
          markdown: next.markdown,
          expectedVersionSeq: next.version_seq,
        },
      };
      rememberKnowledgeDrafts(identityScope, nextDrafts);
      setKnowledgeDrafts(nextDrafts);
      setKnowledgeRows((current) =>
        current.map((row) =>
          row.canonical_set_id === setId
            ? {
                ...row,
                version_seq: next.version_seq,
                content_hash: next.content_hash,
                knowledge_display_name: next.knowledge_display_name,
              }
            : row,
        ),
      );
      setNotice(t("brainformKnowledgeSaved"));
    } catch (cause) {
      if (isConflict(cause)) {
        mutationStore.abandon(intent, handle);
        setNotice(t("brainformKnowledgeConflictDraftKept"));
        try {
          const latest = await api.knowledgeMarkdown(setId);
          if (scopeIsCurrent()) setMarkdown(latest);
        } catch {
          // The user's draft remains in the editor and the inline conflict is enough.
        }
      } else if (isAmbiguousMutationFailure(cause)) {
        setNotice(t("brainformRetrySameSave"));
      } else {
        mutationStore.abandon(intent, handle);
      }
      if (scopeIsCurrent()) setLoadError(cause);
    } finally {
      if (scopeIsCurrent()) setBusyKey(null);
    }
  }

  async function regenerateKnowledge(row: BrainformKnowledge, retry = false) {
    if (!row.can_edit || busyKey) return;
    const pending =
      retry && generationRetry?.documentId === row.canonical_set_id
        ? generationRetry
        : { documentId: row.canonical_set_id, actionId: createUuid() };
    const intent = `brainform-regenerate:${pending.documentId}:${pending.actionId}`;
    const handle = mutationStore.handleFor(intent);
    setBusyKey(`regenerate:${pending.documentId}`);
    setLoadError(null);
    setNotice("");
    try {
      const regeneration = await api.regenerateKnowledgeMarkdown(
        pending.documentId,
        pending.actionId,
        { idempotency: handle },
      );
      mutationStore.finish(intent, handle);
      if (!scopeIsCurrent()) return;
      if (role === "teacher") {
        const nextJobs = {
          ...generationJobs,
          [pending.documentId]: regeneration.job_id,
        };
        rememberGenerationJobs(identityScope, nextJobs);
        setGenerationJobs(nextJobs);
        setGenerationStatuses((current) => {
          const next = { ...current };
          delete next[pending.documentId];
          return next;
        });
      }
      setGenerationRetry(null);
      setKnowledgeRows((current) =>
        current.map((item) =>
          item.canonical_set_id === pending.documentId
            ? { ...item, generation_state: "pending", safe_error_code: null }
            : item,
        ),
      );
      setNotice(t("brainformGenerating"));
      void loadWorkspace();
    } catch (cause) {
      if (isAmbiguousMutationFailure(cause)) {
        setGenerationRetry(pending);
        setNotice(t("brainformRetrySameGeneration"));
      } else {
        mutationStore.abandon(intent, handle);
        setGenerationRetry(null);
      }
      if (scopeIsCurrent()) setLoadError(cause);
    } finally {
      if (scopeIsCurrent()) setBusyKey(null);
    }
  }

  async function saveSetName(setId: string) {
    const value = renameValue.trim();
    setRenameSetId(null);
    if (!value || busyKey) return;
    const current = knowledgeRows.find((row) => row.canonical_set_id === setId);
    if (!current || value === current.knowledge_display_name) return;
    const intent = `brainform-set-name:${setId}:${value}`;
    const handle = mutationStore.handleFor(intent);
    setBusyKey(`rename:${setId}`);
    setLoadError(null);
    setNotice("");
    try {
      const detail = await api.knowledgeSet(setId);
      if (!scopeIsCurrent()) return;
      if (detail.metadata_revision == null)
        throw new Error(t("brainformSetNameUnavailable"));
      const next = await api.updateKnowledgeSet(
        setId,
        {
          expected_metadata_revision: detail.metadata_revision,
          display_name: value,
        },
        { idempotency: handle },
      );
      mutationStore.finish(intent, handle);
      if (!scopeIsCurrent()) return;
      setKnowledgeRows((rows) =>
        rows.map((row) =>
          row.canonical_set_id === setId
            ? { ...row, knowledge_display_name: next.display_name }
            : row,
        ),
      );
      setMarkdown((currentMarkdown) =>
        currentMarkdown?.canonical_set_id === setId
          ? { ...currentMarkdown, knowledge_display_name: next.display_name }
          : currentMarkdown,
      );
    } catch (cause) {
      mutationStore.abandon(intent, handle);
      if (scopeIsCurrent()) setLoadError(cause);
    } finally {
      if (scopeIsCurrent()) setBusyKey(null);
    }
  }

  const generationActive = knowledgeRows.some((row) =>
    isGenerationActive(row.generation_state),
  );
  const selectedDraft =
    pane?.kind === "rag-edit" ? ragDrafts[pane.draftKey] : null;
  const accessibleAgents = useMemo(() => {
    const agentIds = new Set(knowledgeRows.map((row) => row.agent_id));
    const rows = chatAgents.filter((agent) =>
      agentIds.size ? agentIds.has(agent.agent_id) : true,
    );
    return initialAgentId
      ? [...rows].sort(
          (left, right) =>
            Number(right.agent_id === initialAgentId) -
            Number(left.agent_id === initialAgentId),
        )
      : rows;
  }, [chatAgents, initialAgentId, knowledgeRows]);
  const displayedKnowledgeRows = useMemo(() => {
    if (!initialAgentId) return knowledgeRows;
    return [...knowledgeRows].sort(
      (left, right) =>
        Number(right.agent_id === initialAgentId) -
        Number(left.agent_id === initialAgentId),
    );
  }, [initialAgentId, knowledgeRows]);
  const memoryItems = useMemo<BrainformMemoryItem[]>(
    () => [
      ...accessibleAgents.map((agent) => ({
        source: { kind: "agent" as const, agent_id: agent.agent_id },
        name: agent.name,
        detail: agent.version_label,
        label: "brainformMemoryAgent" as const,
      })),
      ...teams
        .filter((team) => team.course_id === courseId)
        .map((team) => ({
          source: { kind: "team" as const, team_id: team.id },
          name: team.display_name,
          detail: "",
          label: "brainformMemoryTeam" as const,
        })),
      ...mayaTeams
        .filter((team) => team.course_id === courseId)
        .map((team) => ({
          source: { kind: "maya_team" as const, team_id: team.id },
          name: team.display_name,
          detail: team.leader_display_name,
          label: "brainformMemoryMayaTeam" as const,
        })),
    ],
    [accessibleAgents, courseId, mayaTeams, teams],
  );

  function memoryHref(source: MemoryEntrySource): string {
    const params = new URLSearchParams({
      memory_action_id: createUuid(),
      memory_actor_id: user?.id ?? "",
      memory_course_id: courseId,
      memory_source_kind: source.kind,
    });
    const sourceId =
      source.kind === "agent"
        ? source.agent_id
        : source.kind === "conversation"
          ? source.id
          : source.team_id;
    params.set("memory_source_id", sourceId);
    return `/${role}/chat?${params.toString()}`;
  }

  return (
    <main className={styles.page}>
      <WorkspaceAction name="new" onClick={startNewRag} disabled={!courseId} />
      <header className={styles.pageHeader}>
        <div>
          <p className={styles.eyebrow}>{t("brainformEyebrow")}</p>
          <h1>{t("brainformTitle")}</h1>
        </div>
        {courseIds.length > 1 ? (
          <label className={styles.coursePicker}>
            <span>{t("selectCourse")}</span>
            <select
              value={courseId}
              onChange={(event) => {
                setPane(null);
                setMarkdown(null);
                onCourseChange(event.target.value);
              }}
            >
              {courseIds.map((id) => (
                <option key={id} value={id}>
                  {courseNames[id] ?? id}
                </option>
              ))}
            </select>
          </label>
        ) : null}
      </header>

      {loadError ? (
        <ErrorNotice error={loadError} onRetry={() => void loadWorkspace()} />
      ) : null}
      {notice ? (
        <p className={styles.notice} role="status">
          {notice}
        </p>
      ) : null}
      {!courseId ? (
        <p className={styles.empty}>{t("brainformUnavailable")}</p>
      ) : null}
      {loading && courseId ? <LoadingCard /> : null}

      {!loading && !loadError && courseId ? (
        <div className={styles.sections}>
          <section
            className={styles.section}
            aria-labelledby="brainform-rag-heading"
          >
            <div className={styles.sectionHeading}>
              <div>
                <h2 id="brainform-rag-heading">RAG</h2>
                <p>{t("brainformRagIntro")}</p>
              </div>
              <span className={styles.count}>{ragDocuments.length}</span>
            </div>
            {ragDocuments.length ? (
              <ul className={styles.list}>
                {ragDocuments.map((document) => {
                  const canEdit = document.can_manage_visibility;
                  const status = indexStatusText(document, t);
                  return (
                    <li className={styles.row} key={document.id}>
                      <div className={styles.rowCopy}>
                        <button
                          type="button"
                          className={styles.titleButton}
                          onClick={() =>
                            void (canEdit
                              ? editRag(document)
                              : viewRag(document))
                          }
                          aria-label={t(
                            canEdit
                              ? "brainformEditRagNamed"
                              : "brainformViewRagNamed",
                            { name: document.source_filename },
                          )}
                        >
                          {document.source_filename}
                        </button>
                        {status ? (
                          <span
                            className={styles.rowStatus}
                            role={
                              document.index_status === "failed"
                                ? "alert"
                                : "status"
                            }
                          >
                            {status}
                          </span>
                        ) : null}
                      </div>
                      <div className={styles.actions}>
                        <button
                          type="button"
                          className={styles.iconButton}
                          aria-label={t("brainformViewRagNamed", {
                            name: document.source_filename,
                          })}
                          title={t("brainformViewRag")}
                          disabled={busyKey === `view:${document.id}`}
                          onClick={() => void viewRag(document)}
                        >
                          <IconEye />
                        </button>
                        {canEdit ? (
                          <button
                            type="button"
                            className={styles.iconButton}
                            aria-label={t("brainformEditRagNamed", {
                              name: document.source_filename,
                            })}
                            title={t("edit")}
                            disabled={busyKey === `read:${document.id}`}
                            onClick={() => void editRag(document)}
                          >
                            <IconEdit />
                          </button>
                        ) : null}
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className={styles.empty}>{t("brainformRagEmpty")}</p>
            )}
          </section>

          <section
            className={styles.section}
            aria-labelledby="brainform-knowledge-heading"
          >
            <div className={styles.sectionHeading}>
              <div>
                <h2 id="brainform-knowledge-heading">
                  {t("brainformKnowledgeHeading")}
                </h2>
                <p>{t("brainformKnowledgeIntro")}</p>
              </div>
              <span className={styles.count}>
                {displayedKnowledgeRows.length}
              </span>
            </div>
            {displayedKnowledgeRows.length ? (
              <ul className={styles.list}>
                {displayedKnowledgeRows.map((row) => {
                  const currentDoc = row.version_seq != null;
                  const canGenerate = row.can_edit;
                  const isGenerating = isGenerationActive(row.generation_state);
                  const generationStatus =
                    generationStatuses[row.canonical_set_id];
                  const providerConfirmationRequired =
                    row.safe_error_code === "provider_confirmation_required";
                  const disclosureHash =
                    role === "teacher" &&
                    generationStatus !== undefined &&
                    generationStatus.job_id ===
                      generationJobs[row.canonical_set_id] &&
                    generationStatus.safe_error_code ===
                      "provider_confirmation_required"
                      ? generationStatus.provider_manifest_hash
                      : null;
                  return (
                    <li
                      className={styles.row}
                      key={`${row.agent_id}:${row.canonical_set_id}`}
                    >
                      <div className={styles.rowCopy}>
                        {renameSetId === row.canonical_set_id ? (
                          <input
                            ref={renameInputRef}
                            className={styles.inlineNameInput}
                            aria-label={t("brainformSetName")}
                            value={renameValue}
                            onChange={(event) =>
                              setRenameValue(event.target.value)
                            }
                            onBlur={() =>
                              void saveSetName(row.canonical_set_id)
                            }
                            onKeyDown={(event) => {
                              if (event.key === "Enter") {
                                event.preventDefault();
                                event.currentTarget.blur();
                              }
                              if (event.key === "Escape") setRenameSetId(null);
                            }}
                          />
                        ) : (
                          <button
                            type="button"
                            className={styles.titleButton}
                            disabled={!row.can_edit}
                            onClick={() => {
                              setRenameSetId(row.canonical_set_id);
                              setRenameValue(row.knowledge_display_name);
                            }}
                            aria-label={
                              row.can_edit
                                ? t("brainformRenameSetNamed", {
                                    name: row.knowledge_display_name,
                                  })
                                : row.knowledge_display_name
                            }
                          >
                            {row.knowledge_display_name}
                          </button>
                        )}
                        <span className={styles.rowMeta}>
                          {row.source_agent_display_name}
                        </span>
                        {isGenerating ? (
                          <span className={styles.rowStatus} role="status">
                            <span className="spinner" aria-hidden="true" />
                            Generating AI Knowledge
                          </span>
                        ) : null}
                        {!isGenerating &&
                        row.generation_state &&
                        row.generation_state !== "completed" ? (
                          <span className={styles.rowStatus} role="alert">
                            {row.safe_error_code
                              ? t("brainformGenerationFailedReason", {
                                  reason: row.safe_error_code.replaceAll(
                                    "_",
                                    " ",
                                  ),
                                })
                              : t("brainformGenerationFailed")}
                          </span>
                        ) : null}
                        {!currentDoc && !row.generation_state ? (
                          <span className={styles.rowStatus} role="status">
                            {t("brainformNoKnowledgeDocument")}
                          </span>
                        ) : null}
                        {disclosureHash ? (
                          <>
                            <span className={styles.rowStatus} role="status">
                              {t("aiKnowledgeProviderConfirmationRecovery")}
                            </span>
                            <Link
                              className={styles.textAction}
                              href={`/teacher/provider-disclosures/${encodeURIComponent(disclosureHash)}`}
                            >
                              {t("reviewProviderDisclosure")}
                            </Link>
                          </>
                        ) : null}
                      </div>
                      <div className={styles.actions}>
                        {currentDoc ? (
                          <>
                            <button
                              type="button"
                              className={styles.iconButton}
                              aria-label={t("brainformViewKnowledgeNamed", {
                                name: row.knowledge_display_name,
                              })}
                              title={t("brainformViewKnowledge")}
                              onClick={() => void openKnowledge(row, "view")}
                            >
                              <IconEye />
                            </button>
                            {row.can_edit ? (
                              <button
                                type="button"
                                className={styles.iconButton}
                                aria-label={t("brainformEditKnowledgeNamed", {
                                  name: row.knowledge_display_name,
                                })}
                                title={t("edit")}
                                onClick={() => void openKnowledge(row, "edit")}
                              >
                                <IconEdit />
                              </button>
                            ) : null}
                          </>
                        ) : null}
                        {canGenerate ? (
                          <button
                            type="button"
                            className={styles.iconButton}
                            aria-label={t("brainformRegenerateNamed", {
                              name: row.knowledge_display_name,
                            })}
                            title={t("brainformRegenerate")}
                            disabled={
                              isGenerating ||
                              providerConfirmationRequired ||
                              busyKey === `regenerate:${row.canonical_set_id}`
                            }
                            onClick={() => void regenerateKnowledge(row)}
                          >
                            <IconRefresh />
                          </button>
                        ) : null}
                        {generationRetry?.documentId ===
                        row.canonical_set_id ? (
                          <button
                            className={styles.textAction}
                            type="button"
                            onClick={() => void regenerateKnowledge(row, true)}
                            disabled={
                              busyKey === `regenerate:${row.canonical_set_id}`
                            }
                          >
                            {t("retry")}
                          </button>
                        ) : null}
                      </div>
                    </li>
                  );
                })}
              </ul>
            ) : (
              <p className={styles.empty}>{t("brainformKnowledgeEmpty")}</p>
            )}
            {generationActive ? (
              <p className={styles.generationNote} role="status">
                Generating AI Knowledge
              </p>
            ) : null}
          </section>

          <section
            className={styles.section}
            aria-labelledby="brainform-memory-heading"
          >
            <div className={styles.sectionHeading}>
              <div>
                <h2 id="brainform-memory-heading">Memory</h2>
                <p>{t("brainformMemoryIntro")}</p>
              </div>
              <span className={styles.count}>{memoryItems.length}</span>
            </div>
            {memoryItems.length ? (
              <ul className={styles.list}>
                {memoryItems.map((item) => (
                  <li
                    className={styles.row}
                    key={`${item.source.kind}:${item.name}:${item.detail}`}
                  >
                    <div className={styles.rowCopy}>
                      <span className={styles.staticTitle}>{item.name}</span>
                      <span className={styles.rowMeta}>
                        {t(item.label)}
                        {item.detail ? ` · ${item.detail}` : ""}
                      </span>
                    </div>
                    <div className={styles.actions}>
                      <button
                        type="button"
                        className={styles.iconButton}
                        aria-label={t("brainformMemoryOpenNamed", {
                          name: item.name,
                        })}
                        title={t("brainformMemoryOpen")}
                        onClick={() => router.push(memoryHref(item.source))}
                      >
                        <IconArrowRight />
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            ) : (
              <p className={styles.empty}>{t("brainformMemoryEmpty")}</p>
            )}
          </section>
        </div>
      ) : null}

      {pane ? (
        <section
          className={styles.editorPanel}
          aria-labelledby="brainform-editor-heading"
        >
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.eyebrow}>
                {pane.kind.startsWith("rag")
                  ? "RAG"
                  : t("brainformKnowledgeHeading")}
              </p>
              <h2 id="brainform-editor-heading">
                {pane.kind === "rag-edit"
                  ? (selectedDraft?.filename ?? t("loading"))
                  : pane.kind === "rag-view"
                    ? pane.filename
                    : (markdown?.knowledge_display_name ?? t("loading"))}
              </h2>
            </div>
            <button
              className={styles.iconButton}
              type="button"
              aria-label={t("brainformClose")}
              onClick={closePane}
            >
              <IconClose />
            </button>
          </div>

          {pane.kind === "rag-edit" && selectedDraft ? (
            <div className={styles.editorForm}>
              {selectedDraft.isNew ? (
                <label
                  className="secondary-action file-button"
                  aria-busy={busyKey === `import:${pane.draftKey}`}
                >
                  {busyKey === `import:${pane.draftKey}`
                    ? t("working")
                    : t("knowledgeImportFile")}
                  <input
                    type="file"
                    accept=".md,text/markdown"
                    disabled={Boolean(busyKey)}
                    onChange={(event) => {
                      const file = event.currentTarget.files?.[0];
                      event.currentTarget.value = "";
                      if (file) void importRag(pane.draftKey, file);
                    }}
                  />
                </label>
              ) : null}
              <label className={styles.field}>
                <span>{t("knowledgeFilename")}</span>
                <input
                  value={selectedDraft.filename}
                  disabled={busyKey === `import:${pane.draftKey}`}
                  readOnly={!selectedDraft.isNew && !selectedDraft.canEdit}
                  aria-describedby={
                    !selectedDraft.isNew && selectedDraft.canEdit
                      ? "brainform-rag-name-note"
                      : undefined
                  }
                  onChange={(event) => {
                    if (!selectedDraft.isNew && !selectedDraft.canEdit) return;
                    saveRagDrafts({
                      ...ragDrafts,
                      [pane.draftKey]: {
                        ...selectedDraft,
                        filename: event.target.value,
                      },
                    });
                  }}
                />
              </label>
              {!selectedDraft.isNew && selectedDraft.canEdit ? (
                <small id="brainform-rag-name-note">
                  {t("brainformRagRenameNote")}
                </small>
              ) : null}
              <label className={styles.field}>
                <span>{t("knowledgeContent")}</span>
                <textarea
                  value={selectedDraft.markdown}
                  disabled={busyKey === `import:${pane.draftKey}`}
                  rows={16}
                  readOnly={!selectedDraft.isNew && !selectedDraft.canEdit}
                  onChange={(event) =>
                    saveRagDrafts({
                      ...ragDrafts,
                      [pane.draftKey]: {
                        ...selectedDraft,
                        markdown: event.target.value,
                      },
                    })
                  }
                />
              </label>
              <div className={styles.panelActions}>
                {selectedDraft.isNew ? (
                  role === "student" && !selectedDraft.groupId ? (
                    <label className={styles.coursePicker}>
                      <span>{t("groupWorkspace")}</span>
                      <select
                        value={selectedDraft.groupId ?? ""}
                        onChange={(event) =>
                          saveRagDrafts({
                            ...ragDrafts,
                            [pane.draftKey]: {
                              ...selectedDraft,
                              groupId: event.target.value || undefined,
                            },
                          })
                        }
                      >
                        <option value="">{t("brainformChooseGroup")}</option>
                        {groups
                          .filter((group) =>
                            (user?.groups ?? []).some(
                              (membership) => membership.group_id === group.id,
                            ),
                          )
                          .map((group) => (
                            <option key={group.id} value={group.id}>
                              {group.name}
                            </option>
                          ))}
                      </select>
                    </label>
                  ) : null
                ) : null}
                <button
                  className="primary-action"
                  type="button"
                  disabled={
                    Boolean(busyKey) ||
                    (!selectedDraft.isNew && !selectedDraft.canEdit) ||
                    (role === "student" &&
                      selectedDraft.isNew &&
                      !selectedDraft.groupId)
                  }
                  onClick={() =>
                    void (selectedDraft.isNew
                      ? createRag(pane.draftKey)
                      : saveRag(pane.draftKey))
                  }
                >
                  {busyKey === pane.draftKey ? t("knowledgeSaving") : t("save")}
                </button>
                <button
                  className="secondary-action"
                  type="button"
                  onClick={closePane}
                >
                  {t("brainformClose")}
                </button>
              </div>
            </div>
          ) : null}

          {pane.kind === "rag-view" ? (
            <ReportMarkdown>{pane.markdown}</ReportMarkdown>
          ) : null}

          {(pane.kind === "knowledge-view" || pane.kind === "knowledge-edit") &&
          markdown ? (
            <>
              {pane.kind === "knowledge-edit" ? (
                <label className={styles.field}>
                  <span>{t("knowledgeContent")}</span>
                  <textarea
                    value={markdownDraft}
                    rows={18}
                    readOnly={
                      !markdown.can_edit || markdown.audience !== "full"
                    }
                    onChange={(event) => {
                      const value = event.target.value;
                      setMarkdownDraft(value);
                      const current = knowledgeDrafts[
                        markdown.canonical_set_id
                      ] ?? {
                        markdown: markdown.markdown,
                        expectedVersionSeq: markdown.version_seq,
                      };
                      const nextDrafts = {
                        ...knowledgeDrafts,
                        [markdown.canonical_set_id]: {
                          ...current,
                          markdown: value,
                        },
                      };
                      rememberKnowledgeDrafts(identityScope, nextDrafts);
                      setKnowledgeDrafts(nextDrafts);
                    }}
                  />
                </label>
              ) : markdown.projection_available ? (
                <KnowledgeMarkdownView
                  markdown={markdown.markdown}
                  graphLabel={t("brainformGraphAccessibleLabel")}
                />
              ) : (
                <p className={styles.empty} role="status">
                  {t("brainformProjectionUnavailable")}
                </p>
              )}
              {pane.kind === "knowledge-edit" &&
              markdown.can_edit &&
              markdown.audience === "full" ? (
                <div className={styles.panelActions}>
                  <button
                    className="primary-action"
                    type="button"
                    disabled={Boolean(busyKey)}
                    onClick={() => void saveKnowledge()}
                  >
                    {busyKey === `knowledge-save:${markdown.canonical_set_id}`
                      ? t("knowledgeSaving")
                      : t("save")}
                  </button>
                  <button
                    className="secondary-action"
                    type="button"
                    onClick={closePane}
                  >
                    {t("brainformClose")}
                  </button>
                </div>
              ) : null}
            </>
          ) : null}
        </section>
      ) : null}
    </main>
  );
}
