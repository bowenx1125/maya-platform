"use client";

import { deleteConfirmText } from "../../lib/affected-agents";
import { usePathname, useRouter } from "next/navigation";
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";

import { FitTitle } from "../fit-title";
import { DismissibleAlert } from "../dismissible-alert";
import {
  isAmbiguousMutationFailure,
  isConflict,
  PlatformApiError,
  type BrainformKnowledge,
  type ChatAgent,
  type Group,
  type KnowledgeDocument,
  type KnowledgeGenerationStatus,
  type KnowledgeMarkdown,
  type PlatformApi,
} from "../../lib/api";
import { useIdempotencyStore } from "../../lib/idempotency";
import {
  cachedCall,
  forgetRequestCache,
  isBusyResponse,
  peekRequestCache,
  rememberRequestCache,
  requestCacheGeneration,
  requestCacheIdentity,
} from "../../lib/request-cache";
import {
  buildMarkdownFile,
  downloadKnowledgeMarkdown,
  KnowledgeFilenameField,
  KnowledgeMarkdownField,
} from "./markdown-editor";
import { runKnowledgeMutation } from "./knowledge-mutation";
import { republishAgentsUsingDocument } from "./republish";
import { localizeError, useT } from "../../lib/i18n";
import { useSession } from "../session-provider";
import { PageAction } from "../page-action";
import { WorkspaceAction } from "../workspace-actions";
import { ModulePlus } from "../studyform-layout";
import { ErrorNotice, isNotFound, LoadingCard } from "../ui";
import { RetryPill } from "../ui/error-kit";
import { ReportMarkdown } from "../report/report-markdown";
import {
  IconClose,
  IconDownload,
  IconRefresh,
  IconUpload,
} from "../quiet-icons";

import styles from "./brainform-workspace.module.css";
import {
  AlbumIcon,
  AlbumIconButton,
  AlbumPlus,
  AlbumRings,
  albumStyles as album,
  fileExt,
  RagCard,
  ragAlbumClass,
  ragAgents,
} from "./rag-album";
import {
  KnowledgeCard,
  KnowledgeIcon,
  KnowledgeArt,
  KnowledgeRings,
  knowledgeAlbum as kAlbum,
} from "./knowledge-album";
import { Button } from "../ui/button";
import { useFileDrop } from "../ui/use-file-drop";
import { cn } from "../../lib/utils";

/**
 * A Brainform row title that enters exactly like an Agent tile's title: the
 * title itself is the button (the same ``agent-tile-name text-link`` classes
 * and styles), so it turns into a pressable button on hover or keyboard
 * focus and a click on it enters. The rest of the row does not enter. A
 * double-click renames in place, so a single click waits out a double-click.
 */
function TitleButton({
  title,
  enterLabel,
  onEnter,
  onRename,
  editable,
  className,
}: {
  className?: string;
  title: string;
  enterLabel: string;
  onEnter?: () => void;
  onRename?: () => void;
  editable: boolean;
}) {
  const clickTimer = useRef<number | null>(null);
  useEffect(
    () => () => {
      if (clickTimer.current !== null) window.clearTimeout(clickTimer.current);
    },
    [],
  );
  function clearTimer() {
    if (clickTimer.current !== null) {
      window.clearTimeout(clickTimer.current);
      clickTimer.current = null;
    }
  }
  return (
    <button
      type="button"
      className={className ?? `agent-tile-name text-link ${styles.titleLink}`}
      aria-label={enterLabel}
      aria-disabled={onEnter ? undefined : true}
      data-ui-guide={editable ? "knowledge.edit" : "knowledge.view"}
      onClick={() => {
        if (!onEnter) return;
        if (!onRename) {
          onEnter();
          return;
        }
        clearTimer();
        clickTimer.current = window.setTimeout(() => {
          clickTimer.current = null;
          onEnter();
        }, 220);
      }}
      onDoubleClick={() => {
        if (!onRename) return;
        clearTimer();
        onRename();
      }}
    >
      <FitTitle text={title} />
    </button>
  );
}

type BrainformRole = "teacher" | "student";

type RagDraft = {
  filename: string;
  markdown: string;
  documentId?: string;
  expectedContentHash?: string;
  expectedIndexRevision?: number;
  originalFilename?: string;
  originalMarkdown?: string;
  canEdit?: boolean;
};

type StagedRagFile = { file: File; fingerprint: string };

type KnowledgeDraft = { markdown: string; expectedVersionSeq: number };
type BrainformKnowledgeAssetRow = BrainformKnowledge & {
  agent_ids: string[];
};

type Pane =
  | { kind: "rag-edit"; draftKey: string }
  | { kind: "rag-view"; documentId: string; markdown: string; filename: string }
  | { kind: "knowledge-view"; documentId: string }
  | { kind: "knowledge-edit"; documentId: string }
  | { kind: "knowledge-new" }
  | { kind: "rag-new" };

type PendingRagAction = { kind: "hide" | "reindex"; documentId: string };

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

function getRagDrafts(scope: string): Record<string, RagDraft> {
  return ragDraftsByScope.get(scope) ?? {};
}

function rememberRagDrafts(scope: string, drafts: Record<string, RagDraft>) {
  ragDraftsByScope.set(scope, drafts);
}

async function fingerprintRagFile(file: File): Promise<string> {
  // jsdom's File#arrayBuffer can return a Node Buffer, which SubtleCrypto rejects.
  const bytes = new Uint8Array(await file.arrayBuffer());
  const subtle = globalThis.crypto?.subtle;
  if (subtle) {
    const digest = new Uint8Array(await subtle.digest("SHA-256", bytes));
    return `sha256:${Array.from(digest, (byte) =>
      byte.toString(16).padStart(2, "0"),
    ).join("")}`;
  }
  return `bytes:${Array.from(new Uint8Array(bytes), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("")}`;
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
  return "";
}

function ragIndexFailureReason(
  document: KnowledgeDocument,
  t: ReturnType<typeof useT>,
) {
  if (document.safe_error_code) {
    return t("brainformRagIndexFailedReason", {
      reason: document.safe_error_code.replaceAll("_", " "),
    });
  }
  return t("brainformRagIndexFailed");
}

/** Idle reload of the Brainform lists (a generation run polls at 1.5 s). */
const IDLE_WORKSPACE_REFRESH_MS = 30_000;

export function BrainformWorkspace({
  role,
  initialAgentId,
  initialSetId,
  initialCourseId,
  initialJobId,
  initialGroupId,
  initialMode,
  initialDocumentId,
  embedded = false,
  ragPage = false,
  knowledgePage = false,
  onPaneChange,
}: {
  /** Rendered inside Studyform: RAG joins Studyform's grid. */
  embedded?: boolean;
  /** The dedicated RAG page (/student/rag, /teacher/rag): RAG only. */
  ragPage?: boolean;
  /** The teacher Knowledge album (/teacher/knowledge): Knowledge only. */
  knowledgePage?: boolean;
  /** Embedded only: a RAG page opened (true) or closed (false). */
  onPaneChange?: (open: boolean) => void;
  role: BrainformRole;
  initialAgentId?: string;
  initialSetId?: string;
  initialCourseId?: string;
  initialJobId?: string;
  initialGroupId?: string;
  initialMode?: string;
  initialDocumentId?: string;
}) {
  const { api, identityGeneration, user } = useSession();
  const [effectiveRole, setEffectiveRole] = useState(role);
  const roleCourseIds = useMemo(
    () =>
      (user?.courses ?? [])
        .filter((membership) => membership.role === effectiveRole)
        .map((membership) => membership.course_id),
    [effectiveRole, user?.courses],
  );
  const usePageCourse = effectiveRole === "student" || Boolean(initialGroupId);
  const defaultCourseId =
    (usePageCourse && initialCourseId && roleCourseIds.includes(initialCourseId)
      ? initialCourseId
      : undefined) ?? roleCourseIds[0];
  const [selectedCourseId, setSelectedCourseId] = useState(
    defaultCourseId ?? "",
  );
  const [groupContextResolved, setGroupContextResolved] =
    useState(!initialGroupId);
  const [groupContextError, setGroupContextError] = useState<unknown>(null);
  const courseId =
    usePageCourse &&
    selectedCourseId &&
    roleCourseIds.includes(selectedCourseId)
      ? selectedCourseId
      : (defaultCourseId ?? "");

  useEffect(() => {
    if (!initialGroupId) {
      const timer = window.setTimeout(() => {
        setEffectiveRole(role);
        setGroupContextResolved(true);
        setGroupContextError(null);
      }, 0);
      return () => window.clearTimeout(timer);
    }
    let active = true;
    const timer = window.setTimeout(() => {
      setGroupContextResolved(false);
      setGroupContextError(null);
      void api
        .group(initialGroupId)
        .then((group) => {
          if (!active) return;
          const member = (user?.groups ?? []).some(
            (membership) => membership.group_id === initialGroupId,
          );
          const groupMemberships = (user?.courses ?? []).filter(
            (membership) => membership.course_id === group.course_id,
          );
          const groupRole = groupMemberships.some(
            (membership) => membership.role === role,
          )
            ? role
            : role === "student" &&
                groupMemberships.some(
                  (membership) => membership.role === "teacher",
                )
              ? "teacher"
              : role;
          const hasGroupCourseRole = groupMemberships.some(
            (membership) => membership.role === groupRole,
          );
          if (!hasGroupCourseRole || (role === "student" && !member))
            throw new Error("group scope unavailable");
          setEffectiveRole(groupRole);
          setSelectedCourseId(group.course_id);
          setGroupContextResolved(true);
        })
        .catch((cause) => {
          if (!active) return;
          setGroupContextError(cause);
          setGroupContextResolved(true);
        });
    }, 0);
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [api, initialGroupId, role, user?.courses, user?.groups]);

  if (!groupContextResolved) return <LoadingCard />;
  if (groupContextError)
    return (
      <ErrorNotice inline notFound="groupNotFound" error={groupContextError} />
    );
  const dataScope = JSON.stringify([
    user?.id ?? null,
    effectiveRole,
    courseId,
    initialGroupId,
    identityGeneration,
  ]);

  return (
    <BrainformWorkspaceBody
      key={dataScope}
      role={effectiveRole}
      courseIds={roleCourseIds}
      courseId={courseId}
      onCourseChange={setSelectedCourseId}
      initialAgentId={initialAgentId}
      initialSetId={initialSetId}
      initialJobId={initialJobId}
      initialGroupId={initialGroupId}
      initialMode={initialMode}
      initialDocumentId={initialDocumentId}
      embedded={embedded}
      ragPage={ragPage}
      knowledgePage={knowledgePage}
      onPaneChange={onPaneChange}
      identityScope={dataScope}
      ragDraftScope={JSON.stringify([
        user?.id ?? null,
        effectiveRole,
        courseId,
      ])}
    />
  );
}

function accessibleCourseNames(
  courseRows: BrainformSnapshot["courseRows"],
  courseIds: string[],
): Record<string, string> {
  return Object.fromEntries(
    courseRows
      .filter((course) => courseIds.includes(course.id))
      .map((course) => [course.id, course.name]),
  );
}

type BrainformSnapshot = {
  courseRows: Awaited<ReturnType<PlatformApi["courses"]>>;
  nextRag: KnowledgeDocument[];
  nextKnowledge: BrainformKnowledge[];
  nextAgents: ChatAgent[];
  nextGroups: Group[];
};

function BrainformWorkspaceBody({
  role,
  courseIds,
  courseId,
  onCourseChange,
  initialAgentId,
  initialSetId,
  initialJobId,
  initialGroupId,
  initialMode,
  initialDocumentId,
  embedded = false,
  ragPage = false,
  knowledgePage: knowledgePageProp = false,
  onPaneChange,
  identityScope,
  ragDraftScope,
}: {
  embedded?: boolean;
  ragPage?: boolean;
  knowledgePage?: boolean;
  onPaneChange?: (open: boolean) => void;
  role: BrainformRole;
  courseIds: string[];
  courseId: string;
  onCourseChange: (courseId: string) => void;
  initialAgentId?: string;
  initialSetId?: string;
  initialJobId?: string;
  initialGroupId?: string;
  initialMode?: string;
  initialDocumentId?: string;
  identityScope: string;
  ragDraftScope: string;
}) {
  const t = useT();
  const router = useRouter();
  const pathname = usePathname();
  const { api, identityGeneration, user } = useSession();
  const cacheIdentity = requestCacheIdentity(user?.id, identityGeneration);
  const snapshotKey = `page:brainform:${identityScope}`;
  // A return visit paints the last lists this identity saw, then refreshes.
  const [snapshot] = useState(() =>
    courseId
      ? peekRequestCache<BrainformSnapshot>(api, cacheIdentity, snapshotKey)
      : undefined,
  );
  const mutationStore = useIdempotencyStore();
  const [courseNames, setCourseNames] = useState<Record<string, string>>(() =>
    snapshot ? accessibleCourseNames(snapshot.courseRows, courseIds) : {},
  );
  const [ragDocuments, setRagDocuments] = useState<KnowledgeDocument[]>(
    snapshot?.nextRag ?? [],
  );
  const [knowledgeRows, setKnowledgeRows] = useState<BrainformKnowledge[]>(
    snapshot?.nextKnowledge ?? [],
  );
  const [chatAgents, setChatAgents] = useState<ChatAgent[]>(
    snapshot?.nextAgents ?? [],
  );
  const [groups, setGroups] = useState<Group[]>(snapshot?.nextGroups ?? []);
  const [loading, setLoading] = useState(!snapshot);
  const [loadError, setLoadError] = useState<unknown>(null);
  // U3: a refused filename wears the file sticker, on the line and the field.
  const filenameError = isFilenameError(loadError);
  const [notice, setNotice] = useState("");
  const [pendingRagAction, setPendingRagAction] =
    useState<PendingRagAction | null>(null);
  const [pane, setPane] = useState<Pane | null>(null);
  const handledUrlMode = useRef("");
  const [ragDrafts, setRagDrafts] = useState<Record<string, RagDraft>>(() =>
    getRagDrafts(ragDraftScope),
  );
  const [ragFiles, setRagFiles] = useState<Record<string, StagedRagFile>>({});
  const [busyKey, setBusyKey] = useState<string | null>(null);
  const [markdown, setMarkdown] = useState<KnowledgeMarkdown | null>(null);
  const [markdownDraft, setMarkdownDraft] = useState("");
  const [knowledgeNameDraft, setKnowledgeNameDraft] = useState("");
  const [knowledgeDrafts, setKnowledgeDrafts] = useState<
    Record<string, KnowledgeDraft>
  >(() => getKnowledgeDrafts(identityScope));
  const [generationJobs, setGenerationJobs] = useState<Record<string, string>>(
    () => getGenerationJobs(identityScope),
  );
  const [generationStatuses, setGenerationStatuses] = useState<
    Record<string, KnowledgeGenerationStatus>
  >({});
  const [renameSetId, setRenameSetId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const currentScope = useRef(identityScope);
  const ragActionPane = useRef<Pane | null>(pane);
  const ragActionDrafts = useRef(ragDrafts);
  const ragActionFiles = useRef(ragFiles);
  const busyKeyRef = useRef(busyKey);
  const saveRagAction = useRef<(draftKey: string) => void>(() => {});
  function commitBusy(
    next: string | null | ((current: string | null) => string | null),
  ) {
    const resolved =
      typeof next === "function" ? next(busyKeyRef.current) : next;
    busyKeyRef.current = resolved;
    setBusyKey(resolved);
  }
  useLayoutEffect(() => {
    ragActionPane.current = pane;
    saveRagAction.current = (draftKey) => {
      void saveRag(draftKey);
    };
  });
  const loadSequence = useRef(0);
  const operationSequence = useRef(0);
  const fileSelectionSequence = useRef(0);
  const renameInputRef = useRef<HTMLInputElement>(null);
  const [renameDocumentId, setRenameDocumentId] = useState<string | null>(null);
  // New opens this draft; a picked Markdown file fills it, Done saves it.
  const [newKnowledge, setNewKnowledge] = useState({ name: "", markdown: "" });
  // RAG + opens this draft: typed Markdown, or a picked file (a .md fills
  // the text; a PDF or DOCX is imported by the server on Done).
  const [newRag, setNewRag] = useState<{
    name: string;
    markdown: string;
    file: File | null;
    groupId: string;
  }>({ name: "", markdown: "", file: null, groupId: "" });
  const initialKnowledgeOpened = useRef(false);
  const initialJobRead = useRef<string | null>(null);
  const latestGenerationJobs = useRef<{
    scope: string;
    jobs: Record<string, string | null>;
  } | null>(null);

  const syncModeUrl = useCallback(
    (mode: string | null, documentId?: string) => {
      if (typeof window === "undefined") return;
      const params = new URLSearchParams(window.location.search);
      if (mode) {
        params.set("mode", mode);
        if (documentId) params.set("document_id", documentId);
        else params.delete("document_id");
        handledUrlMode.current = `${mode}:${documentId ?? ""}`;
      } else {
        params.delete("mode");
        params.delete("document_id");
        handledUrlMode.current =
          handledUrlMode.current ||
          (initialMode
            ? `${initialMode}:${initialDocumentId ?? initialSetId ?? ""}`
            : "closed");
      }
      const query = params.toString();
      router.push(`${pathname}${query ? `?${query}` : ""}`, { scroll: false });
    },
    [initialDocumentId, initialMode, initialSetId, pathname, router],
  );

  useEffect(() => {
    const onPopState = () => {
      if (new URLSearchParams(window.location.search).has("mode")) return;
      handledUrlMode.current = "";
      setPane(null);
      setMarkdown(null);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

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

  const generationJobIsCurrent = useCallback(
    (scope: string, setId: string, jobId: string) => {
      const latest = latestGenerationJobs.current;
      return (
        latest?.scope !== scope ||
        !Object.prototype.hasOwnProperty.call(latest.jobs, setId) ||
        latest.jobs[setId] === jobId
      );
    },
    [],
  );

  // Page-load reads go through the shared cache: identical reads in flight
  // are sent once (both lists below read each group), and a quiet refresh
  // asks the server again.
  const read = useCallback(
    <T,>(
      name: string,
      args: unknown[],
      run: () => Promise<T>,
      refresh = false,
    ): Promise<T> =>
      cachedCall(api, cacheIdentity, name, args, run, { refresh }),
    [api, cacheIdentity],
  );

  const loadRagDocuments = useCallback(
    async (
      activeCourseId: string,
      refresh: boolean,
      startedReads: Promise<unknown>[],
    ) => {
      if (initialGroupId) {
        if (
          role === "student" &&
          !(user?.groups ?? []).some(
            (membership) => membership.group_id === initialGroupId,
          )
        )
          throw new Error(t("groupNotFound"));
        // The group and its files together; the files count only when the
        // group belongs to this course.
        const documents = read(
          "knowledge",
          [initialGroupId],
          () => api.knowledge(initialGroupId),
          refresh,
        ).catch((cause: unknown) => {
          // A teacher who has not Entered the group gets a 404 here. That is
          // not a deleted item: say they are not in the group.
          if (role === "teacher" && isNotFound(cause))
            throw new Error(t("groupNotFound"));
          throw cause;
        });
        // A group refusal can finish this loader before its file read settles.
        startedReads.push(documents);
        const group = await read(
          "group",
          [initialGroupId],
          () => api.group(initialGroupId),
          refresh,
        );
        if (group.course_id !== activeCourseId)
          throw new Error(t("groupNotFound"));
        return documents;
      }
      if (role === "teacher")
        return read(
          "workspaceDocuments",
          [activeCourseId],
          () => api.workspaceDocuments(activeCourseId),
          refresh,
        );
      const joinedGroupIds = [
        ...new Set((user?.groups ?? []).map((group) => group.group_id)),
      ];
      // One round trip: each joined group and its files at once; files of a
      // group in another course are dropped.
      const rows = await Promise.all(
        joinedGroupIds.map(async (groupId) => {
          const [group, documents] = await Promise.allSettled([
            read("group", [groupId], () => api.group(groupId), refresh),
            read("knowledge", [groupId], () => api.knowledge(groupId), refresh),
          ]);
          return group.status === "fulfilled" &&
            group.value.course_id === activeCourseId &&
            documents.status === "fulfilled"
            ? documents.value
            : [];
        }),
      );
      const byId = new Map<string, KnowledgeDocument>();
      for (const documents of rows) {
        for (const document of documents) byId.set(document.id, document);
      }
      return [...byId.values()];
    },
    [api, initialGroupId, read, role, t, user?.groups],
  );

  const loadGroups = useCallback(
    async (activeCourseId: string, refresh = false) => {
      if (role === "teacher")
        return read(
          "groups",
          [activeCourseId],
          () => api.groups(activeCourseId),
          refresh,
        );
      const groupIds = [
        ...new Set((user?.groups ?? []).map((group) => group.group_id)),
      ];
      const results = await Promise.allSettled(
        groupIds.map((groupId) =>
          read("group", [groupId], () => api.group(groupId), refresh),
        ),
      );
      return results.flatMap((result) =>
        result.status === "fulfilled" &&
        result.value.course_id === activeCourseId
          ? [result.value]
          : [],
      );
    },
    [api, read, role, user?.groups],
  );

  const applyWorkspace = useCallback(
    (scope: string, data: BrainformSnapshot) => {
      const { courseRows, nextRag, nextKnowledge, nextAgents, nextGroups } =
        data;
      setCourseNames(accessibleCourseNames(courseRows, courseIds));
      setRagDocuments(nextRag);
      setKnowledgeRows(nextKnowledge);
      setChatAgents(nextAgents);
      setGroups(nextGroups);
      const latestJobs: Record<string, string | null> = {};
      for (const row of nextKnowledge) {
        const setId = row.canonical_set_id;
        if (!Object.prototype.hasOwnProperty.call(latestJobs, setId)) {
          latestJobs[setId] = null;
        }
        if (role === "teacher" && row.can_edit && row.generation_job_id) {
          latestJobs[setId] = row.generation_job_id;
        }
      }
      latestGenerationJobs.current = { scope, jobs: latestJobs };
      const restoredJobs = Object.fromEntries(
        Object.entries(latestJobs).filter(
          (entry): entry is [string, string] => entry[1] !== null,
        ),
      );
      const previousJobs = getGenerationJobs(scope);
      const jobsChanged =
        Object.keys(previousJobs).length !== Object.keys(restoredJobs).length ||
        Object.entries(restoredJobs).some(
          ([setId, jobId]) => previousJobs[setId] !== jobId,
        );
      if (jobsChanged) {
        rememberGenerationJobs(scope, restoredJobs);
      }
      setGenerationJobs((current) => {
        const currentEntries = Object.entries(current);
        return currentEntries.length === Object.keys(restoredJobs).length &&
          currentEntries.every(
            ([setId, jobId]) => restoredJobs[setId] === jobId,
          )
          ? current
          : restoredJobs;
      });
      setGenerationStatuses((current) => {
        const retained = Object.entries(current).filter(
          ([setId, status]) => restoredJobs[setId] === status.job_id,
        );
        return retained.length === Object.keys(current).length
          ? current
          : Object.fromEntries(retained);
      });
    },
    [courseIds, role],
  );

  const refreshingSnapshot = useRef(Boolean(snapshot));
  const pendingWorkspaceLoad = useRef<number | null>(null);
  // Every reload (after a change, the polling below) asks the server; only
  // the first load of a visit reuses reads under FRESH_MS old or in flight.
  const loadWorkspace = useCallback(
    async (background = false, refresh = true) => {
      const scope = identityScope;
      const sequence = ++loadSequence.current;
      if (!courseId) {
        setRagDocuments([]);
        setKnowledgeRows([]);
        setChatAgents([]);
        setGroups([]);
        latestGenerationJobs.current = { scope, jobs: {} };
        rememberGenerationJobs(scope, {});
        setGenerationJobs({});
        setGenerationStatuses({});
        setLoading(false);
        setLoadError(null);
        return;
      }
      if (!background) {
        setLoading(true);
        setLoadError(null);
      }
      const generation = requestCacheGeneration(api);
      pendingWorkspaceLoad.current = sequence;
      let settledReads: Promise<unknown> | undefined;
      try {
        const ragReads: Promise<unknown>[] = [];
        const reads = [
          read("courses", [], () => api.courses(), refresh),
          // A private Agent's files live only inside that Agent; Brainform is
          // the group's shared library of public Agents' RAG.
          loadRagDocuments(courseId, refresh, ragReads).then((documents) =>
            documents.filter((document) => document.visibility !== "private"),
          ),
          // Students no longer see Knowledge (owner request 2026-10-20);
          // its list is the slowest read here, so they skip it.
          embedded && role === "student"
            ? Promise.resolve<BrainformKnowledge[]>([])
            : read(
                "brainformKnowledge",
                [courseId],
                () => api.brainformKnowledge(courseId),
                refresh,
              ),
          read(
            "chatAgents",
            [courseId],
            () => api.chatAgents(courseId),
            refresh,
          ),
          loadGroups(courseId, refresh),
        ] as const;
        settledReads = Promise.allSettled([...reads, ...ragReads]);
        const [courseRows, nextRag, nextKnowledge, nextAgents, nextGroups] =
          await Promise.all(reads);
        if (!scopeIsCurrent(scope) || sequence !== loadSequence.current) return;
        const data: BrainformSnapshot = {
          courseRows,
          nextRag,
          nextKnowledge,
          nextAgents,
          nextGroups,
        };
        applyWorkspace(scope, data);
        rememberRequestCache(api, cacheIdentity, snapshotKey, data, generation);
        refreshingSnapshot.current = false;
        if (!background) setNotice("");
      } catch (cause) {
        // The first quiet refresh of a painted snapshot must not leave lists
        // on screen that the server now refuses; a busy server keeps them.
        const refusedSnapshot =
          background && refreshingSnapshot.current && !isBusyResponse(cause);
        if (refusedSnapshot) {
          refreshingSnapshot.current = false;
          forgetRequestCache(api, cacheIdentity, snapshotKey);
        }
        if (
          (!background || refusedSnapshot) &&
          scopeIsCurrent(scope) &&
          sequence === loadSequence.current
        ) {
          setLoadError(cause);
        }
      } finally {
        if (scopeIsCurrent(scope) && sequence === loadSequence.current) {
          setLoading(false);
        }
        // A refused list must not restart polling while sibling reads still
        // hold cache slots; their fetch deadlines settle this batch as well.
        await settledReads;
        if (pendingWorkspaceLoad.current === sequence)
          pendingWorkspaceLoad.current = null;
      }
    },
    [
      api,
      applyWorkspace,
      cacheIdentity,
      courseId,
      identityScope,
      loadGroups,
      loadRagDocuments,
      read,
      scopeIsCurrent,
      snapshotKey,
    ],
  );

  useEffect(() => {
    const timer = window.setTimeout(
      () => void loadWorkspace(refreshingSnapshot.current, false),
      0,
    );
    return () => window.clearTimeout(timer);
  }, [loadWorkspace]);

  const generationActive = knowledgeRows.some((row) =>
    isGenerationActive(row.generation_state),
  );
  // Knowledge can also be produced by an Agent's tool outside this page, so
  // the list keeps refreshing quietly: quickly while a run is in progress,
  // every 30 s otherwise (was 10 s), and at once when the page comes back.
  useEffect(() => {
    if (!courseId) return;
    const scope = identityScope;
    const refresh = () => {
      // Explicit saves may supersede a slow read; only the latest load
      // blocks automatic refreshes, so an old hung request cannot stall them.
      if (
        document.visibilityState === "hidden" ||
        !scopeIsCurrent(scope) ||
        pendingWorkspaceLoad.current !== null
      )
        return;
      void loadWorkspace(true);
    };
    const timer = window.setInterval(
      refresh,
      generationActive ? 1500 : IDLE_WORKSPACE_REFRESH_MS,
    );
    document.addEventListener("visibilitychange", refresh);
    window.addEventListener("focus", refresh);
    return () => {
      window.clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
      window.removeEventListener("focus", refresh);
    };
  }, [
    courseId,
    generationActive,
    identityScope,
    loadWorkspace,
    scopeIsCurrent,
  ]);

  useEffect(() => {
    if (!renameSetId && !renameDocumentId) return;
    renameInputRef.current?.focus();
    renameInputRef.current?.select();
  }, [renameSetId, renameDocumentId]);

  useEffect(() => {
    if (initialMode || loading || initialKnowledgeOpened.current) return;
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
  }, [initialAgentId, initialMode, initialSetId, knowledgeRows, loading]);

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
        if (
          !scopeIsCurrent(scope) ||
          status.job_id !== initialJobId ||
          !generationJobIsCurrent(scope, status.knowledge_set_id, status.job_id)
        )
          return;
        setGenerationStatuses((current) => {
          if (
            !scopeIsCurrent(scope) ||
            !generationJobIsCurrent(
              scope,
              status.knowledge_set_id,
              status.job_id,
            )
          )
            return current;
          return { ...current, [status.knowledge_set_id]: status };
        });
        setGenerationJobs((current) => {
          if (
            !scopeIsCurrent(scope) ||
            !generationJobIsCurrent(
              scope,
              status.knowledge_set_id,
              status.job_id,
            )
          )
            return current;
          const next = {
            ...getGenerationJobs(scope),
            [status.knowledge_set_id]: status.job_id,
          };
          rememberGenerationJobs(scope, next);
          return next;
        });
        const latest = latestGenerationJobs.current;
        latestGenerationJobs.current = {
          scope,
          jobs: {
            ...(latest?.scope === scope ? latest.jobs : {}),
            [status.knowledge_set_id]: status.job_id,
          },
        };
      })
      .catch(() => {
        // The owner-only Job endpoint decides whether a routed job is visible.
      });
  }, [
    api,
    generationJobIsCurrent,
    identityScope,
    initialJobId,
    role,
    scopeIsCurrent,
  ]);

  useEffect(() => {
    if (role !== "teacher") return;
    let active = true;
    const timers = new Set<number>();
    const scope = identityScope;
    const poll = async (setId: string, jobId: string) => {
      try {
        const status = await api.knowledgeGenerationJob(jobId);
        if (
          !active ||
          !scopeIsCurrent(scope) ||
          status.job_id !== jobId ||
          getGenerationJobs(scope)[setId] !== jobId ||
          !generationJobIsCurrent(scope, setId, jobId)
        )
          return;
        setGenerationStatuses((current) => {
          if (
            getGenerationJobs(scope)[setId] !== jobId ||
            !generationJobIsCurrent(scope, setId, jobId)
          )
            return current;
          return { ...current, [setId]: status };
        });
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
  }, [
    api,
    generationJobs,
    generationJobIsCurrent,
    identityScope,
    role,
    scopeIsCurrent,
  ]);

  // Inside Studyform, an open RAG or Record pane is its own page: Studyform
  // hides its other cards while it is open, as Brainform did.
  const paneOpen = Boolean(pane || initialMode);
  useEffect(() => {
    if (!embedded) return;
    onPaneChange?.(paneOpen);
    if (paneOpen) window.scrollTo?.({ top: 0 });
  }, [embedded, onPaneChange, paneOpen]);

  const closePane = useCallback(() => {
    operationSequence.current += 1;
    commitBusy((current) => (current?.startsWith("import:") ? null : current));
    setPane(null);
    setMarkdown(null);
    setNotice("");
    syncModeUrl(null);
  }, [syncModeUrl]);

  function saveRagDrafts(next: Record<string, RagDraft>) {
    ragActionDrafts.current = next;
    rememberRagDrafts(ragDraftScope, next);
    setRagDrafts(next);
  }

  function abandonRagDraftMutation(draftKey: string, draft: RagDraft) {
    if (!draft.documentId) return;
    if (
      draft.expectedContentHash &&
      draft.expectedIndexRevision !== undefined
    ) {
      mutationStore.abandon(
        `brainform-replace:${draft.documentId}:${draft.expectedContentHash}:${draft.expectedIndexRevision}`,
      );
    }
    mutationStore.abandon(
      `brainform-rename:${draft.documentId}:${draft.originalFilename ?? draft.filename}:${draft.filename.trim()}`,
    );
  }

  function sameRagFile(
    left: StagedRagFile | null | undefined,
    right: StagedRagFile | null | undefined,
  ) {
    if (left === right) return true;
    return Boolean(
      left &&
      right &&
      left.file.name === right.file.name &&
      left.file.size === right.file.size &&
      left.file.type === right.file.type &&
      left.fingerprint === right.fingerprint,
    );
  }

  function updateRagDraft(
    draftKey: string,
    next: RagDraft,
    stagedFile?: StagedRagFile | null,
  ) {
    const current = ragActionDrafts.current[draftKey];
    const currentFile = ragActionFiles.current[draftKey];
    const nextFile = stagedFile === undefined ? currentFile : stagedFile;
    if (
      current &&
      (current.filename !== next.filename ||
        current.markdown !== next.markdown ||
        !sameRagFile(currentFile, nextFile))
    ) {
      abandonRagDraftMutation(draftKey, current);
    }
    saveRagDrafts({ ...ragActionDrafts.current, [draftKey]: next });
    if (stagedFile !== undefined) {
      const updated = { ...ragActionFiles.current };
      if (stagedFile) updated[draftKey] = stagedFile;
      else delete updated[draftKey];
      ragActionFiles.current = updated;
      setRagFiles(updated);
    }
  }

  async function importRag(draftKey: string, file: File) {
    const draft = ragActionDrafts.current[draftKey];
    if (!draft || busyKeyRef.current || !draft.canEdit) return;
    const extension = file.name.split(".").at(-1)?.toLowerCase();
    if (!extension || !["md", "pdf", "docx"].includes(extension)) {
      setNotice(t("brainformMarkdownRequired"));
      return;
    }
    const scope = identityScope;
    const selection = ++fileSelectionSequence.current;
    const sequence = ++operationSequence.current;
    const selectionIsCurrent = () =>
      scopeIsCurrent(scope) &&
      selection === fileSelectionSequence.current &&
      sequence === operationSequence.current;
    commitBusy(`import:${draftKey}`);
    setLoadError(null);
    setNotice("");
    if (extension !== "md") {
      try {
        const stagedFile = {
          file,
          fingerprint: await fingerprintRagFile(file),
        };
        if (!selectionIsCurrent()) return;
        updateRagDraft(draftKey, { ...draft, filename: file.name }, stagedFile);
        setNotice(t("brainformRagFileStaged", { filename: file.name }));
      } catch (cause) {
        if (selectionIsCurrent()) setLoadError(cause);
      } finally {
        if (selectionIsCurrent()) commitBusy(null);
      }
      return;
    }
    try {
      const content = new TextDecoder("utf-8", { fatal: true }).decode(
        await file.arrayBuffer(),
      );
      if (!selectionIsCurrent()) return;
      if (!content.trim()) {
        setNotice(t("brainformMarkdownRequired"));
        return;
      }
      updateRagDraft(
        draftKey,
        { ...draft, filename: file.name, markdown: content },
        null,
      );
    } catch {
      if (selectionIsCurrent()) {
        setNotice(t("brainformMarkdownRequired"));
      }
    } finally {
      if (selectionIsCurrent()) commitBusy(null);
    }
  }

  async function editRag(document: KnowledgeDocument, syncUrl = true) {
    const draftKey = `document:${document.id}`;
    const existing = ragDrafts[draftKey];
    if (existing) {
      setPane({ kind: "rag-edit", draftKey });
      setNotice("");
      if (syncUrl) syncModeUrl("rag-edit", document.id);
      return;
    }
    const scope = identityScope;
    const sequence = ++operationSequence.current;
    commitBusy(`read:${document.id}`);
    setNotice("");
    try {
      const downloaded = await api.downloadKnowledge(document.id);
      if (!scopeIsCurrent(scope) || sequence !== operationSequence.current)
        return;
      const draft: RagDraft = {
        filename: document.source_filename,
        markdown: downloaded.content,
        documentId: document.id,
        expectedContentHash: document.content_hash,
        expectedIndexRevision: document.index_revision,
        originalFilename: downloaded.filename || document.source_filename,
        originalMarkdown: downloaded.content,
        canEdit: document.can_manage_visibility,
      };
      saveRagDrafts({ ...ragDrafts, [draftKey]: draft });
      setPane({ kind: "rag-edit", draftKey });
      if (syncUrl) syncModeUrl("rag-edit", document.id);
    } catch (cause) {
      if (scopeIsCurrent(scope) && sequence === operationSequence.current) {
        setLoadError(cause);
      }
    } finally {
      if (scopeIsCurrent(scope) && sequence === operationSequence.current) {
        commitBusy(null);
      }
    }
  }

  async function viewRag(document: KnowledgeDocument, syncUrl = true) {
    const scope = identityScope;
    const sequence = ++operationSequence.current;
    commitBusy(`view:${document.id}`);
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
      if (syncUrl) syncModeUrl("rag-view", document.id);
    } catch (cause) {
      if (scopeIsCurrent(scope) && sequence === operationSequence.current) {
        setLoadError(cause);
      }
    } finally {
      if (scopeIsCurrent(scope) && sequence === operationSequence.current) {
        commitBusy(null);
      }
    }
  }

  async function saveRag(draftKey: string) {
    const draft = ragActionDrafts.current[draftKey];
    const stagedFile = ragActionFiles.current[draftKey]?.file;
    if (
      !draft ||
      !draft.documentId ||
      !draft.canEdit ||
      !draft.expectedContentHash ||
      draft.expectedIndexRevision === undefined ||
      busyKeyRef.current
    )
      return;
    const filename = draft.filename.trim();
    const extension = filename.split(".").at(-1)?.toLowerCase();
    const contentChanged = draft.markdown !== draft.originalMarkdown;
    const filenameChanged = filename !== draft.originalFilename;
    if (!extension || !["md", "pdf", "docx"].includes(extension)) {
      setNotice(t("brainformMarkdownRequired"));
      return;
    }
    if (
      contentChanged &&
      !stagedFile &&
      (extension !== "md" || !draft.markdown.trim())
    ) {
      setNotice(t("brainformMarkdownRequired"));
      return;
    }
    if (!filenameChanged && !contentChanged && !stagedFile) return;
    const renameOnly = filenameChanged && !contentChanged && !stagedFile;
    const intent = renameOnly
      ? `brainform-rename:${draft.documentId}:${draft.originalFilename}:${filename}`
      : `brainform-replace:${draft.documentId}:${draft.expectedContentHash}:${draft.expectedIndexRevision}`;
    commitBusy(draftKey);
    setLoadError(null);
    setNotice("");
    try {
      const next = await runKnowledgeMutation(
        mutationStore,
        intent,
        (idempotency) =>
          renameOnly
            ? api.renameKnowledgeDocument(
                draft.documentId as string,
                {
                  expected_filename: draft.originalFilename ?? draft.filename,
                  filename,
                },
                { idempotency },
              )
            : api.replaceKnowledgeDocument(
                draft.documentId as string,
                stagedFile
                  ? new File([stagedFile], filename, { type: stagedFile.type })
                  : buildMarkdownFile(filename, draft.markdown),
                draft.expectedContentHash as string,
                draft.expectedIndexRevision as number,
                { idempotency },
              ),
      );
      if (!scopeIsCurrent()) return;
      saveRagDrafts({
        ...ragActionDrafts.current,
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
      const nextFiles = { ...ragActionFiles.current };
      delete nextFiles[draftKey];
      ragActionFiles.current = nextFiles;
      setRagFiles(nextFiles);
      if (!renameOnly) {
        // The Agents reading this file publish a new version with its new
        // text; the server then moves their Teams to it.
        await republishAgentsUsingDocument(api, chatAgents, next.id);
        if (!scopeIsCurrent()) return;
      }
      closePane();
      void loadWorkspace(true);
    } catch (cause) {
      if (isConflict(cause)) {
        await loadWorkspace();
        if (scopeIsCurrent()) setNotice(t("brainformRagConflictDraftKept"));
      } else if (isAmbiguousMutationFailure(cause)) {
        setNotice(t("brainformRetrySameSave"));
      }
      if (scopeIsCurrent()) setLoadError(cause);
    } finally {
      if (scopeIsCurrent()) commitBusy(null);
    }
  }

  async function downloadRag(document: KnowledgeDocument) {
    commitBusy(`download:${document.id}`);
    setLoadError(null);
    setNotice("");
    try {
      const downloaded = await api.downloadKnowledge(document.id);
      if (!scopeIsCurrent()) return;
      downloadKnowledgeMarkdown(downloaded.content, downloaded.filename);
    } catch (cause) {
      if (scopeIsCurrent()) setLoadError(cause);
    } finally {
      if (scopeIsCurrent()) commitBusy(null);
    }
  }

  async function hideRag(document: KnowledgeDocument, retry = false) {
    if (!document.can_manage_visibility) return;
    if (!retry) {
      const message = await deleteConfirmText(
        t("brainformRagHideConfirm", { filename: document.source_filename }),
        () => api.knowledgeAffectedAgents(document.id),
        (names) => t("deleteAffectsAgents", { names }),
        ", ",
      );
      if (!window.confirm(message)) return;
    }
    const intent = `knowledge-hide:${document.id}`;
    commitBusy(`hide:${document.id}`);
    setPendingRagAction(null);
    setLoadError(null);
    setNotice("");
    try {
      await runKnowledgeMutation(mutationStore, intent, (idempotency) =>
        api.hideKnowledge(document.id, { idempotency }),
      );
      if (!scopeIsCurrent()) return;
      setRagDocuments((current) =>
        current.filter((item) => item.id !== document.id),
      );
      setNotice(t("knowledgeHidden"));
      void loadWorkspace();
    } catch (cause) {
      if (isAmbiguousMutationFailure(cause)) {
        setPendingRagAction({ kind: "hide", documentId: document.id });
        setNotice(t("brainformRetrySameSave"));
      }
      if (scopeIsCurrent()) setLoadError(cause);
    } finally {
      if (scopeIsCurrent()) commitBusy(null);
    }
  }

  function beginNewKnowledge() {
    setNewKnowledge({ name: "", markdown: "" });
    setPane({ kind: "knowledge-new" });
    setNotice("");
    setLoadError(null);
  }

  function beginNewRag() {
    setNewRag({
      name: "",
      markdown: "",
      file: null,
      groupId: ragGroupIds[0] ?? "",
    });
    setPane({ kind: "rag-new" });
    setNotice("");
    setLoadError(null);
  }

  async function importNewRag(file: File) {
    const extension = file.name.match(/\.[^.]+$/)?.[0]?.toLowerCase() ?? "";
    const fileName = file.name.replace(/\.[^.]+$/, "").trim() || file.name;
    if (extension === ".pdf" || extension === ".docx") {
      setNotice("");
      setNewRag((current) => ({
        ...current,
        name: current.name.trim() ? current.name : fileName,
        markdown: "",
        file,
      }));
      return;
    }
    if (extension !== ".md") {
      setNotice(t("brainformMarkdownRequired"));
      return;
    }
    let content: string;
    try {
      content = new TextDecoder("utf-8", { fatal: true }).decode(
        await file.arrayBuffer(),
      );
    } catch {
      setNotice(t("brainformMarkdownRequired"));
      return;
    }
    if (!content.trim()) {
      setNotice(t("brainformMarkdownRequired"));
      return;
    }
    setNotice("");
    setNewRag((current) => ({
      ...current,
      name: current.name.trim() ? current.name : fileName,
      markdown: content,
      file: null,
    }));
  }

  function selectRagFile(file: File) {
    if (pane?.kind === "rag-new") void importNewRag(file);
    else if (pane?.kind === "rag-edit") void importRag(pane.draftKey, file);
  }

  const ragFileDrop = useFileDrop({
    disabled: Boolean(busyKey),
    onFile: selectRagFile,
  });

  function selectKnowledgeFile(file: File) {
    if (pane?.kind === "knowledge-new") void importNewKnowledge(file);
    else if (pane?.kind === "knowledge-edit") void importKnowledgeEdit(file);
  }

  const knowledgeFileDrop = useFileDrop({
    disabled: Boolean(busyKey),
    onFile: selectKnowledgeFile,
  });

  async function saveNewRag() {
    const draft = newRag;
    const name = draft.name.trim().replace(/\.(md|pdf|docx)$/i, "");
    if (busyKeyRef.current || !courseId || !name) return;
    if (!draft.file && !draft.markdown.trim()) return;
    const groupId = initialGroupId ?? draft.groupId;
    const target =
      role === "teacher" ? { courseId } : groupId ? { groupId } : null;
    if (!target) return;
    const extension = draft.file
      ? (draft.file.name.match(/\.[^.]+$/)?.[0]?.toLowerCase() ?? "")
      : ".md";
    const upload = draft.file
      ? new File([draft.file], `${name}${extension}`, { type: draft.file.type })
      : new File([draft.markdown], `${name}.md`, { type: "text/markdown" });
    // Done returns to the list at once; the RAG + shows the work.
    commitBusy("rag-new");
    setPane(null);
    setLoadError(null);
    setNotice("");
    try {
      // Keyed by the exact draft, so a retried Done after a lost reply
      // replays the same upload instead of adding a second RAG.
      const draftKey = `${JSON.stringify(target)}:${upload.name}:${await fingerprintRagFile(upload)}`;
      await runKnowledgeMutation(
        mutationStore,
        `rag-new:${draftKey}`,
        (idempotency) =>
          api.uploadRagLibraryDocument(target, upload, { idempotency }),
      );
      if (!scopeIsCurrent()) return;
      setNewRag({ name: "", markdown: "", file: null, groupId: "" });
      await loadWorkspace(true);
    } catch (cause) {
      if (!scopeIsCurrent()) return;
      // The draft is kept: reopen it beside the error so Done can retry.
      setPane({ kind: "rag-new" });
      setLoadError(cause);
    } finally {
      if (scopeIsCurrent()) commitBusy(null);
    }
  }

  // A picked Markdown file fills the new Knowledge, named after the file
  // unless a name was typed. Its question sections are recognised on save
  // the same way as an edit in Brainform.
  async function importNewKnowledge(file: File) {
    if (!/\.md$/i.test(file.name)) {
      setNotice(t("brainformMarkdownRequired"));
      return;
    }
    let content: string;
    try {
      content = new TextDecoder("utf-8", { fatal: true }).decode(
        await file.arrayBuffer(),
      );
    } catch {
      setNotice(t("brainformMarkdownRequired"));
      return;
    }
    if (!content.trim()) {
      setNotice(t("brainformMarkdownRequired"));
      return;
    }
    const fileName = file.name.replace(/\.md$/i, "").trim() || file.name;
    setNotice("");
    setNewKnowledge((current) => ({
      name: current.name.trim() ? current.name : fileName,
      markdown: content,
    }));
  }

  async function importKnowledgeEdit(file: File) {
    if (!markdown?.can_edit || markdown.audience !== "full") return;
    if (!/\.md$/i.test(file.name)) {
      setNotice(t("brainformMarkdownRequired"));
      return;
    }
    let content: string;
    try {
      content = new TextDecoder("utf-8", { fatal: true }).decode(
        await file.arrayBuffer(),
      );
    } catch {
      setNotice(t("brainformMarkdownRequired"));
      return;
    }
    if (!content.trim()) {
      setNotice(t("brainformMarkdownRequired"));
      return;
    }
    const setId = markdown.canonical_set_id;
    const current = knowledgeDrafts[setId] ?? {
      markdown: markdown.markdown,
      expectedVersionSeq: markdown.version_seq,
    };
    if (content !== markdownDraft) {
      mutationStore.abandon(
        `brainform-markdown:${setId}:${current.expectedVersionSeq}`,
      );
    }
    setNotice("");
    setMarkdownDraft(content);
    const nextDrafts = {
      ...knowledgeDrafts,
      [setId]: { ...current, markdown: content },
    };
    rememberKnowledgeDrafts(identityScope, nextDrafts);
    setKnowledgeDrafts(nextDrafts);
  }

  async function saveNewKnowledge() {
    const name = newKnowledge.name.trim();
    const content = newKnowledge.markdown;
    if (busyKeyRef.current || !courseId || !name || !content.trim()) return;
    // Done returns to the list at once; New shows the work until it lands.
    commitBusy("knowledge-new");
    setPane(null);
    setLoadError(null);
    setNotice("");
    try {
      // Keyed by the exact draft, so a retried Done after a lost reply
      // replays the same create instead of making a second Knowledge.
      const draftKey = `${courseId}:${name}:${await fingerprintRagFile(
        new File([content], "knowledge.md"),
      )}`;
      const created = await runKnowledgeMutation(
        mutationStore,
        `knowledge-new:${draftKey}`,
        (idempotency) =>
          api.createKnowledgeSet(
            courseId,
            { display_name: name },
            { idempotency },
          ),
      );
      await runKnowledgeMutation(
        mutationStore,
        `knowledge-new-save:${created.id}`,
        (idempotency) =>
          api.saveKnowledgeMarkdown(
            created.id,
            { expected_version_seq: 0, markdown: content },
            { idempotency },
          ),
      );
      if (!scopeIsCurrent()) return;
      setNewKnowledge({ name: "", markdown: "" });
      await loadWorkspace(true);
    } catch (cause) {
      if (!scopeIsCurrent()) return;
      // The draft is kept: reopen it beside the error so Done can retry.
      setPane({ kind: "knowledge-new" });
      setLoadError(cause);
    } finally {
      if (scopeIsCurrent()) commitBusy(null);
    }
  }

  async function deleteKnowledge(row: BrainformKnowledge) {
    if (
      !row.can_edit ||
      !window.confirm(
        t("brainformDeleteKnowledgeConfirm", {
          name: row.knowledge_display_name,
        }),
      )
    )
      return;
    const intent = `knowledge-set-delete:${row.canonical_set_id}`;
    commitBusy(`delete-set:${row.canonical_set_id}`);
    setLoadError(null);
    setNotice("");
    try {
      // The delete is fenced by the Set's current revisions, read just now.
      const detail = await api.knowledgeSet(row.canonical_set_id);
      await runKnowledgeMutation(mutationStore, intent, (idempotency) =>
        api.deleteKnowledgeSet(
          row.canonical_set_id,
          {
            expected_metadata_revision: detail.metadata_revision ?? 0,
            expected_content_revision: detail.content_revision ?? 0,
          },
          { idempotency },
        ),
      );
      if (!scopeIsCurrent()) return;
      setNotice(t("brainformKnowledgeDeleted"));
      void loadWorkspace();
    } catch (cause) {
      if (scopeIsCurrent()) setLoadError(cause);
    } finally {
      if (scopeIsCurrent()) commitBusy(null);
    }
  }

  async function reindexRag(document: KnowledgeDocument, retry = false) {
    if (!document.can_manage_visibility || document.index_status !== "failed")
      return;
    const intent = `knowledge-reindex:${document.id}`;
    commitBusy(`reindex:${document.id}`);
    setPendingRagAction(null);
    setLoadError(null);
    setNotice("");
    try {
      await runKnowledgeMutation(mutationStore, intent, (idempotency) =>
        api.reindex(document.id, { idempotency }),
      );
      if (!scopeIsCurrent()) return;
      void loadWorkspace();
    } catch (cause) {
      if (isAmbiguousMutationFailure(cause)) {
        setPendingRagAction({ kind: "reindex", documentId: document.id });
        setNotice(t("brainformRetrySameSave"));
      }
      if (scopeIsCurrent()) setLoadError(cause);
    } finally {
      if (scopeIsCurrent()) commitBusy(null);
    }
  }

  function retryRagAction() {
    if (!pendingRagAction) return;
    const document = ragDocuments.find(
      (item) => item.id === pendingRagAction.documentId,
    );
    if (!document) return;
    if (pendingRagAction.kind === "hide") void hideRag(document, true);
    else void reindexRag(document, true);
  }

  function beginKnowledgeEdit(current: KnowledgeMarkdown, syncUrl = true) {
    const setId = current.canonical_set_id;
    const draft = knowledgeDrafts[setId] ?? {
      markdown: current.markdown,
      expectedVersionSeq: current.version_seq,
    };
    if (!knowledgeDrafts[setId]) {
      const nextDrafts = { ...knowledgeDrafts, [setId]: draft };
      rememberKnowledgeDrafts(identityScope, nextDrafts);
      setKnowledgeDrafts(nextDrafts);
    }
    setMarkdownDraft(draft.markdown);
    setKnowledgeNameDraft(current.knowledge_display_name);
    setPane({ kind: "knowledge-edit", documentId: setId });
    if (syncUrl) syncModeUrl("knowledge-edit", setId);
  }

  async function downloadKnowledgeSet(row: BrainformKnowledge) {
    if ((row.version_seq ?? 0) <= 0 || busyKey) return;
    commitBusy(`download-knowledge:${row.canonical_set_id}`);
    setLoadError(null);
    setNotice("");
    try {
      const next = await api.knowledgeMarkdown(row.canonical_set_id);
      if (!scopeIsCurrent()) return;
      downloadKnowledgeMarkdown(
        next.markdown,
        `${next.knowledge_display_name || row.knowledge_display_name}.md`,
      );
    } catch (cause) {
      if (scopeIsCurrent()) setLoadError(cause);
    } finally {
      if (scopeIsCurrent()) commitBusy(null);
    }
  }

  async function openKnowledge(
    row: BrainformKnowledge,
    mode: "view" | "edit",
    syncUrl = true,
  ) {
    const scope = identityScope;
    const sequence = ++operationSequence.current;
    commitBusy(`knowledge:${row.canonical_set_id}`);
    setLoadError(null);
    setNotice("");
    try {
      const next = await api.knowledgeMarkdown(row.canonical_set_id);
      if (!scopeIsCurrent(scope) || sequence !== operationSequence.current)
        return;
      setMarkdown(next);
      if (mode === "edit") {
        beginKnowledgeEdit(next, syncUrl);
        return;
      }
      setPane({ kind: "knowledge-view", documentId: row.canonical_set_id });
      if (syncUrl) syncModeUrl("knowledge-view", row.canonical_set_id);
    } catch (cause) {
      if (scopeIsCurrent(scope) && sequence === operationSequence.current) {
        if (
          mode === "edit" &&
          row.can_edit &&
          (row.version_seq == null || row.version_seq === 0) &&
          cause instanceof PlatformApiError &&
          cause.status === 404
        ) {
          const emptyDraft = {
            markdown: knowledgeDrafts[row.canonical_set_id]?.markdown ?? "",
            expectedVersionSeq: 0,
          };
          const emptyMarkdown: KnowledgeMarkdown = {
            audience: "full",
            agent_id: row.agent_id,
            canonical_set_id: row.canonical_set_id,
            source_agent_display_name: row.source_agent_display_name,
            knowledge_display_name: row.knowledge_display_name,
            version_seq: 0,
            content_hash: "",
            markdown: "",
            projection_available: true,
            can_read: true,
            can_edit: true,
            created_at: "",
          };
          const nextDrafts = {
            ...knowledgeDrafts,
            [row.canonical_set_id]: emptyDraft,
          };
          rememberKnowledgeDrafts(identityScope, nextDrafts);
          setKnowledgeDrafts(nextDrafts);
          setMarkdown(emptyMarkdown);
          setMarkdownDraft(emptyDraft.markdown);
          setKnowledgeNameDraft(row.knowledge_display_name);
          setPane({
            kind: "knowledge-edit",
            documentId: row.canonical_set_id,
          });
          if (syncUrl) syncModeUrl("knowledge-edit", row.canonical_set_id);
          return;
        }
        setLoadError(cause);
      }
    } finally {
      if (scopeIsCurrent(scope) && sequence === operationSequence.current) {
        commitBusy(null);
      }
    }
  }

  useEffect(() => {
    if (!initialMode) {
      return;
    }
    const documentId = initialDocumentId ?? initialSetId;
    const modeKey = `${initialMode}:${documentId ?? ""}`;
    if (handledUrlMode.current === modeKey || loading || !courseId) return;
    const timer = window.setTimeout(() => {
      if (handledUrlMode.current === modeKey) return;
      // The Guide's "Add the RAG" step lands here: open the RAG create form,
      // as the page's own New does, once the groups that may hold it are known.
      if (initialMode === "rag-new") {
        handledUrlMode.current = modeKey;
        if (canAddRag) beginNewRag();
        return;
      }
      if (initialMode === "rag-view" || initialMode === "rag-edit") {
        if (!documentId) {
          handledUrlMode.current = modeKey;
          setLoadError(new Error(t("brainformRagEmpty")));
          return;
        }
        const document = ragDocuments.find((item) => item.id === documentId);
        if (!document) {
          handledUrlMode.current = modeKey;
          setLoadError(new Error(t("brainformRagEmpty")));
          return;
        }
        handledUrlMode.current = modeKey;
        if (initialMode === "rag-view") void viewRag(document, false);
        else if (document.can_manage_visibility) void editRag(document, false);
        else void viewRag(document, false);
        return;
      }
      if (
        initialMode === "knowledge-view" ||
        initialMode === "knowledge-edit"
      ) {
        if (!documentId) {
          handledUrlMode.current = modeKey;
          setLoadError(new Error(t("brainformKnowledgeEmpty")));
          return;
        }
        const row = knowledgeRows.find(
          (item) => item.canonical_set_id === documentId,
        );
        if (!row) {
          handledUrlMode.current = modeKey;
          setLoadError(new Error(t("brainformKnowledgeEmpty")));
          return;
        }
        handledUrlMode.current = modeKey;
        void openKnowledge(
          row,
          initialMode === "knowledge-view" || !row.can_edit ? "view" : "edit",
          false,
        );
      }
    }, 0);
    return () => window.clearTimeout(timer);
    // The routed operation is dispatched once after its context is loaded.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    courseId,
    initialDocumentId,
    initialMode,
    initialSetId,
    knowledgeRows,
    loading,
    ragDocuments,
    t,
  ]);

  async function saveKnowledge() {
    if (!markdown?.can_edit || busyKey) return;
    const setId = markdown.canonical_set_id;
    const nextName = knowledgeNameDraft.trim();
    if (!nextName) {
      setNotice(t("brainformSetNameUnavailable"));
      return;
    }
    const draft = knowledgeDrafts[setId] ?? {
      markdown: markdownDraft,
      expectedVersionSeq: markdown.version_seq,
    };
    const nameChanged = nextName !== markdown.knowledge_display_name;
    const contentChanged = markdownDraft !== markdown.markdown;
    if (!nameChanged && !contentChanged) return;
    const nameIntent = `brainform-set-name:${setId}:${nextName}`;
    const contentIntent = `brainform-markdown:${setId}:${draft.expectedVersionSeq}`;
    const nameHandle = nameChanged ? mutationStore.handleFor(nameIntent) : null;
    const contentHandle =
      contentChanged || markdown.version_seq === 0
        ? mutationStore.handleFor(contentIntent)
        : null;
    commitBusy(`knowledge-save:${setId}`);
    setLoadError(null);
    setNotice("");
    try {
      let displayName = markdown.knowledge_display_name;
      if (nameChanged && nameHandle) {
        const detail = await api.knowledgeSet(setId);
        if (!scopeIsCurrent()) return;
        if (detail.metadata_revision == null)
          throw new Error(t("brainformSetNameUnavailable"));
        const renamed = await api.updateKnowledgeSet(
          setId,
          {
            expected_metadata_revision: detail.metadata_revision,
            display_name: nextName,
          },
          { idempotency: nameHandle },
        );
        mutationStore.finish(nameIntent, nameHandle);
        displayName = renamed.display_name;
      }
      let next = { ...markdown, knowledge_display_name: displayName };
      if (contentHandle) {
        next = await api.saveKnowledgeMarkdown(
          setId,
          {
            expected_version_seq: draft.expectedVersionSeq,
            markdown: markdownDraft,
          },
          { idempotency: contentHandle },
        );
        mutationStore.finish(contentIntent, contentHandle);
        next = { ...next, knowledge_display_name: displayName };
      }
      if (!scopeIsCurrent()) return;
      setMarkdown(next);
      setMarkdownDraft(next.markdown);
      setKnowledgeNameDraft(displayName);
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
                knowledge_display_name: displayName,
              }
            : row,
        ),
      );
      closePane();
      void loadWorkspace(true);
    } catch (cause) {
      if (isConflict(cause)) {
        if (nameHandle) mutationStore.abandon(nameIntent, nameHandle);
        if (contentHandle) mutationStore.abandon(contentIntent, contentHandle);
        setNotice(t("brainformKnowledgeConflictDraftKept"));
        try {
          const latest = await api.knowledgeMarkdown(setId);
          if (scopeIsCurrent()) {
            setMarkdown(latest);
            setKnowledgeNameDraft(latest.knowledge_display_name);
          }
        } catch {
          // The user's draft remains in the editor and the inline conflict is enough.
        }
      } else if (isAmbiguousMutationFailure(cause)) {
        setNotice(t("brainformRetrySameSave"));
      } else {
        if (nameHandle) mutationStore.abandon(nameIntent, nameHandle);
        if (contentHandle) mutationStore.abandon(contentIntent, contentHandle);
      }
      if (scopeIsCurrent()) setLoadError(cause);
    } finally {
      if (scopeIsCurrent()) commitBusy(null);
    }
  }

  async function saveDocumentName(document: KnowledgeDocument) {
    const base = renameValue.trim();
    setRenameDocumentId(null);
    if (!base || busyKeyRef.current) return;
    const extension = document.source_filename.match(/\.[^.]+$/)?.[0] ?? "";
    const filename = base.toLowerCase().endsWith(extension.toLowerCase())
      ? base
      : `${base}${extension}`;
    if (filename === document.source_filename) return;
    const intent = `brainform-rename:${document.id}:${document.source_filename}:${filename}`;
    commitBusy(`rename-document:${document.id}`);
    setLoadError(null);
    setNotice("");
    try {
      const next = await runKnowledgeMutation(
        mutationStore,
        intent,
        (idempotency) =>
          api.renameKnowledgeDocument(
            document.id,
            { expected_filename: document.source_filename, filename },
            { idempotency },
          ),
      );
      if (!scopeIsCurrent()) return;
      setRagDocuments((current) =>
        current.map((row) => (row.id === next.id ? next : row)),
      );
      setNotice(t("brainformRagRenamed"));
    } catch (cause) {
      if (scopeIsCurrent()) setLoadError(cause);
    } finally {
      if (scopeIsCurrent()) commitBusy(null);
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
    commitBusy(`rename:${setId}`);
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
      if (scopeIsCurrent()) commitBusy(null);
    }
  }

  const selectedDraft =
    pane?.kind === "rag-edit" ? ragDrafts[pane.draftKey] : null;
  const selectedRagFile =
    pane?.kind === "rag-edit" ? (ragFiles[pane.draftKey]?.file ?? null) : null;
  const ragDirty = Boolean(
    selectedDraft?.canEdit &&
    (selectedDraft.filename.trim() !==
      (selectedDraft.originalFilename ?? selectedDraft.filename) ||
      selectedDraft.markdown !== selectedDraft.originalMarkdown ||
      Boolean(selectedRagFile)),
  );
  const knowledgeDirty = Boolean(
    pane?.kind === "knowledge-edit" &&
    markdown?.can_edit &&
    markdown.audience === "full" &&
    (knowledgeNameDraft.trim() !== markdown.knowledge_display_name ||
      markdownDraft !== markdown.markdown),
  );
  // The groups a student's new RAG can go to: the open group, else each
  // joined group of this course.
  const ragGroupIds =
    role === "teacher"
      ? []
      : initialGroupId
        ? [initialGroupId]
        : groups.map((group) => group.id);
  const displayedKnowledgeRows = useMemo(() => {
    const bySet = new Map<string, BrainformKnowledge[]>();
    for (const row of knowledgeRows) {
      const rows = bySet.get(row.canonical_set_id) ?? [];
      rows.push(row);
      bySet.set(row.canonical_set_id, rows);
    }
    const assets: BrainformKnowledgeAssetRow[] = [...bySet.values()].flatMap(
      (rows) => {
        const representative = rows[0];
        if (!representative) return [];
        return [
          {
            ...representative,
            can_edit: rows.some((row) => row.can_edit),
            generation_job_id:
              rows.find((row) => row.generation_job_id)?.generation_job_id ??
              representative.generation_job_id,
            generation_state:
              rows.find((row) => isGenerationActive(row.generation_state))
                ?.generation_state ?? representative.generation_state,
            safe_error_code:
              rows.find((row) => row.safe_error_code)?.safe_error_code ??
              representative.safe_error_code,
            version_seq:
              rows.find((row) => row.version_seq != null)?.version_seq ??
              representative.version_seq,
            agent_ids: [
              ...new Set(
                rows.flatMap((row) => (row.agent_id ? [row.agent_id] : [])),
              ),
            ],
          },
        ];
      },
    );
    if (!initialAgentId) return assets;
    return assets.sort(
      (left, right) =>
        Number(right.agent_ids.includes(initialAgentId)) -
        Number(left.agent_ids.includes(initialAgentId)),
    );
  }, [initialAgentId, knowledgeRows]);
  // Owner request (2026-10-19): the sidebar New is gone; RAG and Knowledge
  // each add from a + at their top right, the same + as Studyform's Agents
  // and Teams. Only a teacher adds Knowledge. Inside a group the teacher
  // entered, that group's library is editable until they leave.
  const teacherGroupView = role === "teacher" && Boolean(initialGroupId);
  const visitingGroupLibrary =
    teacherGroupView &&
    (user?.groups ?? []).some(
      (membership) => membership.group_id === initialGroupId,
    );
  const canAddKnowledge =
    role === "teacher" && (!teacherGroupView || visitingGroupLibrary);
  const canAddRag =
    (!teacherGroupView || visitingGroupLibrary) &&
    (role === "teacher" || ragGroupIds.length > 0);

  const knowledgePage = knowledgePageProp && role === "teacher";
  const knowledgeEditor =
    knowledgePage &&
    (pane?.kind === "knowledge-new" || pane?.kind === "knowledge-edit");
  const knowledgeNameError = filenameError ? localizeError(loadError) : null;

  return (
    <div
      className={
        ragPage
          ? ragAlbumClass
          : knowledgePage
            ? cn(kAlbum.alb, knowledgeEditor && kAlbum.albEd)
            : embedded
              ? styles.embeddedPage
              : styles.page
      }
      data-studyform-embedded={embedded || undefined}
    >
      {ragPage ? <AlbumRings /> : null}
      {knowledgePage ? <KnowledgeRings editor={knowledgeEditor} /> : null}
      {pane?.kind === "rag-new" && !ragPage ? (
        <WorkspaceAction
          name="done"
          onClick={() => void saveNewRag()}
          disabled={
            Boolean(busyKey) ||
            !newRag.name.trim() ||
            (!newRag.file && !newRag.markdown.trim()) ||
            (role !== "teacher" && !(initialGroupId ?? newRag.groupId))
          }
        />
      ) : null}
      {pane?.kind === "knowledge-new" && !knowledgePage ? (
        <WorkspaceAction
          name="done"
          onClick={() => void saveNewKnowledge()}
          disabled={
            Boolean(busyKey) ||
            !newKnowledge.name.trim() ||
            !newKnowledge.markdown.trim()
          }
        />
      ) : null}
      {(pane || initialMode) &&
      !knowledgeEditor &&
      !(
        ragPage &&
        (pane?.kind.startsWith("rag") ||
          initialMode === "rag-view" ||
          initialMode === "rag-edit" ||
          initialMode === "rag-new")
      ) ? (
        <WorkspaceAction
          name="back"
          onClick={closePane}
          disabled={Boolean(busyKey)}
        />
      ) : null}
      {pane?.kind === "knowledge-view" &&
      markdown?.can_edit &&
      markdown.audience === "full" ? (
        <WorkspaceAction
          name="new"
          onClick={() => beginKnowledgeEdit(markdown)}
          disabled={Boolean(busyKey)}
        />
      ) : null}
      {pane?.kind === "rag-edit" && selectedDraft && !ragPage ? (
        <WorkspaceAction
          name="done"
          onClick={() => {
            const current = ragActionPane.current;
            if (current?.kind !== "rag-edit") return;
            const draft = ragActionDrafts.current[current.draftKey];
            if (!draft) return;
            saveRagAction.current(current.draftKey);
          }}
          disabled={Boolean(busyKey) || !selectedDraft.canEdit || !ragDirty}
        />
      ) : null}
      {pane?.kind === "knowledge-edit" && markdown && !knowledgePage ? (
        <WorkspaceAction
          name="done"
          onClick={() => void saveKnowledge()}
          disabled={
            Boolean(busyKey) ||
            !markdown.can_edit ||
            markdown.audience !== "full" ||
            !knowledgeDirty
          }
        />
      ) : null}
      {role === "student" && courseIds.length > 1 && !initialGroupId ? (
        <header className={styles.pageHeader}>
          <label className={styles.coursePicker}>
            <span>{t("selectCourse")}</span>
            <select
              value={courseId}
              onChange={(event) => {
                setPane(null);
                setMarkdown(null);
                syncModeUrl(null);
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
        </header>
      ) : null}

      {loadError ? (
        <ErrorNotice
          error={loadError}
          badge={filenameError ? 1 : undefined}
          onRetry={() =>
            pendingRagAction ? retryRagAction() : void loadWorkspace()
          }
        />
      ) : null}
      {notice ? (
        <p className={styles.notice} role="status">
          {notice}
        </p>
      ) : null}
      {!courseId ? (
        <p className={styles.empty}>{t("brainformUnavailable")}</p>
      ) : null}
      {loading && courseId && !embedded ? <LoadingCard /> : null}

      {/* Embedded in Studyform each card paints on its own: RAG shows a
          loading line while its list arrives, Record never waits for it. */}
      {ragPage &&
      !pane &&
      !initialMode &&
      !loading &&
      !loadError &&
      courseId ? (
        <section aria-labelledby="brainform-rag-heading">
          <div className={album.top}>
            <h2
              id="brainform-rag-heading"
              data-ui-guide="knowledge.files"
              data-ui-guide-text={t("brainformRagIntro")}
              tabIndex={0}
            >
              RAG
            </h2>
            <span className={album.tape} aria-hidden="true" />
            <span className={album.sp} />
            {canAddRag ? (
              <AlbumPlus
                label={t("brainformNewRag")}
                onClick={beginNewRag}
                disabled={Boolean(busyKey)}
                busy={busyKey === "rag-new"}
              />
            ) : (
              <span className={album.count}>{ragDocuments.length}</span>
            )}
          </div>
          {ragDocuments.length ? (
            <ul className={album.grid}>
              {ragDocuments.map((document, index) => {
                const canEdit = document.can_manage_visibility;
                const status = indexStatusText(document, t);
                const failed = document.index_status === "failed";
                return (
                  <RagCard
                    key={document.id}
                    index={index}
                    document={document}
                    agents={ragAgents(document)}
                    tone={failed ? "failed" : status ? "pending" : ""}
                    openLabel={t(
                      canEdit
                        ? "brainformEditRagNamed"
                        : "brainformViewRagNamed",
                      { name: document.source_filename },
                    )}
                    onOpen={() =>
                      void (canEdit ? editRag(document) : viewRag(document))
                    }
                    title={
                      renameDocumentId === document.id ? (
                        <input
                          ref={renameInputRef}
                          className={album.renameInput}
                          aria-label={t("brainformRagName")}
                          value={renameValue}
                          onChange={(event) =>
                            setRenameValue(event.target.value)
                          }
                          onBlur={() => void saveDocumentName(document)}
                          onKeyDown={(event) => {
                            if (event.key === "Enter") {
                              event.preventDefault();
                              event.currentTarget.blur();
                            }
                            if (event.key === "Escape")
                              setRenameDocumentId(null);
                          }}
                        />
                      ) : (
                        <TitleButton
                          className={album.fn}
                          title={document.source_filename}
                          editable={canEdit}
                          enterLabel={t(
                            canEdit
                              ? "brainformEditRagNamed"
                              : "brainformViewRagNamed",
                            { name: document.source_filename },
                          )}
                          onEnter={() =>
                            void (canEdit
                              ? editRag(document)
                              : viewRag(document))
                          }
                          onRename={
                            canEdit
                              ? () => {
                                  setRenameDocumentId(document.id);
                                  setRenameValue(
                                    document.source_filename.replace(
                                      /\.[^.]+$/,
                                      "",
                                    ),
                                  );
                                }
                              : undefined
                          }
                        />
                      )
                    }
                    status={
                      status ? (
                        <p className={album.stkWarn} role="status">
                          <i className={album.spin} aria-hidden="true" />
                          {status}
                        </p>
                      ) : failed ? (
                        <p className={album.stkBad} role="status">
                          {ragIndexFailureReason(document, t)}
                        </p>
                      ) : null
                    }
                    footer={
                      <>
                        <AlbumIconButton
                          icon="download"
                          label={t("brainformDownloadRagNamed", {
                            name: document.source_filename,
                          })}
                          guide="knowledge.download"
                          disabled={busyKey === `download:${document.id}`}
                          onClick={() => void downloadRag(document)}
                        />
                        {canEdit && failed ? (
                          <AlbumIconButton
                            icon="refresh"
                            label={t("brainformReindexRagNamed", {
                              name: document.source_filename,
                            })}
                            guide="knowledge.reindex"
                            disabled={busyKey === `reindex:${document.id}`}
                            onClick={() => void reindexRag(document)}
                          />
                        ) : null}
                        {pendingRagAction?.documentId === document.id ? (
                          <RetryPill
                            className="ml-0"
                            disabled={Boolean(busyKey)}
                            onClick={retryRagAction}
                          >
                            {t("retry")}
                          </RetryPill>
                        ) : null}
                        <span className={album.sp} />
                        {canEdit ? (
                          <AlbumIconButton
                            icon="close"
                            danger
                            label={t("brainformHideRagNamed", {
                              name: document.source_filename,
                            })}
                            guide="knowledge.hide"
                            disabled={busyKey === `hide:${document.id}`}
                            onClick={() => void hideRag(document)}
                          />
                        ) : null}
                      </>
                    }
                    badge={
                      failed ? (
                        <span
                          className={`status-badge status-bad ${album.fb}`}
                          data-ui-guide="knowledge.indexFailed"
                          data-ui-guide-text={ragIndexFailureReason(
                            document,
                            t,
                          )}
                          tabIndex={0}
                        >
                          <span aria-hidden="true" />
                          failed
                        </span>
                      ) : null
                    }
                  />
                );
              })}
            </ul>
          ) : (
            <div className={album.grid}>
              <div className={album.ghostFirst}>
                <svg
                  width="64"
                  height="64"
                  viewBox="0 0 24 24"
                  fill="#67E8F9"
                  stroke="#111"
                  strokeWidth="1.6"
                  aria-hidden="true"
                >
                  <path d="M6 3h9l4 4v14H6zM14 3v5h5" />
                </svg>
                <p>{t("brainformRagEmpty")}</p>
              </div>
              <div className={album.ghost} aria-hidden="true">
                <AlbumIcon name="plus" size={40} />
              </div>
              <div className={album.ghost} aria-hidden="true">
                <AlbumIcon name="plus" size={40} />
              </div>
            </div>
          )}
        </section>
      ) : null}
      {knowledgePage &&
      !pane &&
      !initialMode &&
      !loading &&
      !loadError &&
      courseId ? (
        <section aria-labelledby="brainform-knowledge-heading">
          <div className={kAlbum.top}>
            <h2
              id="brainform-knowledge-heading"
              className={kAlbum.title}
              data-ui-guide="knowledge.files"
              data-ui-guide-text={t("brainformKnowledgeIntro")}
              tabIndex={0}
            >
              {t("brainformKnowledgeHeading")}
            </h2>
            <span className={kAlbum.tape} aria-hidden="true" />
            <span className={kAlbum.sp} />
            {canAddKnowledge ? (
              <Button
                className={cn(kAlbum.btn, kAlbum.pink)}
                aria-label={t("brainformNewKnowledge")}
                busy={busyKey === "knowledge-new"}
                disabled={Boolean(busyKey)}
                onClick={beginNewKnowledge}
              >
                {busyKey === "knowledge-new" ? (
                  <span className="spinner" aria-hidden="true" />
                ) : (
                  <KnowledgeIcon name="plus" stroke={3} />
                )}
                <span aria-hidden="true">New</span>
              </Button>
            ) : (
              <span>{displayedKnowledgeRows.length}</span>
            )}
          </div>
          {displayedKnowledgeRows.length ? (
            <ul className={kAlbum.grid}>
              {displayedKnowledgeRows.map((row) => {
                const currentDoc = (row.version_seq ?? 0) > 0;
                const isGenerating = isGenerationActive(row.generation_state);
                const jobStatus = generationStatuses[row.canonical_set_id];
                const generationErrorCode =
                  jobStatus &&
                  jobStatus.job_id === generationJobs[row.canonical_set_id]
                    ? jobStatus.safe_error_code
                    : row.safe_error_code;
                const failed =
                  !isGenerating &&
                  Boolean(row.generation_state) &&
                  row.generation_state !== "completed";
                return (
                  <KnowledgeCard
                    key={row.canonical_set_id}
                    artId={`kart-${row.canonical_set_id}`}
                    tone={isGenerating ? "running" : failed ? "failed" : ""}
                    openLabel={
                      row.can_edit
                        ? t("brainformEditKnowledgeNamed", {
                            name: row.knowledge_display_name,
                          })
                        : t("brainformViewKnowledgeNamed", {
                            name: row.knowledge_display_name,
                          })
                    }
                    onOpen={
                      isGenerating || (!currentDoc && !row.can_edit)
                        ? undefined
                        : () =>
                            void openKnowledge(
                              row,
                              row.can_edit ? "edit" : "view",
                            )
                    }
                    footer={
                      <>
                        {isGenerating ? (
                          <button
                            type="button"
                            className={kAlbum.ib}
                            aria-label={t("brainformGeneratingNamed", {
                              name: row.knowledge_display_name,
                            })}
                            aria-busy="true"
                            disabled
                          >
                            <span className="spinner" aria-hidden="true" />
                          </button>
                        ) : null}
                        {currentDoc && !isGenerating ? (
                          <Button
                            variant="neutral"
                            className={kAlbum.btn}
                            aria-label={t("brainformDownloadKnowledgeNamed", {
                              name: row.knowledge_display_name,
                            })}
                            data-ui-guide="knowledge.download"
                            busy={
                              busyKey ===
                              `download-knowledge:${row.canonical_set_id}`
                            }
                            disabled={Boolean(busyKey)}
                            onClick={() => void downloadKnowledgeSet(row)}
                          >
                            {busyKey ===
                            `download-knowledge:${row.canonical_set_id}` ? (
                              <span className="spinner" aria-hidden="true" />
                            ) : (
                              <KnowledgeIcon name="download" />
                            )}
                            <span aria-hidden="true">Download</span>
                          </Button>
                        ) : null}
                        {row.can_edit && !isGenerating ? (
                          <Button
                            variant="neutral"
                            className={cn(kAlbum.btn, kAlbum.del)}
                            aria-label={t("brainformDeleteKnowledgeNamed", {
                              name: row.knowledge_display_name,
                            })}
                            data-ui-guide="knowledge.hide"
                            busy={
                              busyKey === `delete-set:${row.canonical_set_id}`
                            }
                            disabled={Boolean(busyKey)}
                            onClick={() => void deleteKnowledge(row)}
                          >
                            {busyKey ===
                            `delete-set:${row.canonical_set_id}` ? (
                              <span className="spinner" aria-hidden="true" />
                            ) : (
                              <KnowledgeIcon name="trash" />
                            )}
                            <span aria-hidden="true">Delete</span>
                          </Button>
                        ) : null}
                      </>
                    }
                  >
                    {renameSetId === row.canonical_set_id ? (
                      <input
                        ref={renameInputRef}
                        className={kAlbum.renameInput}
                        aria-label={t("brainformSetName")}
                        value={renameValue}
                        onChange={(event) => setRenameValue(event.target.value)}
                        onBlur={() => void saveSetName(row.canonical_set_id)}
                        onKeyDown={(event) => {
                          if (event.key === "Enter") {
                            event.preventDefault();
                            event.currentTarget.blur();
                          }
                          if (event.key === "Escape") setRenameSetId(null);
                        }}
                      />
                    ) : (
                      <TitleButton
                        className={kAlbum.fn}
                        title={row.knowledge_display_name}
                        editable={row.can_edit}
                        enterLabel={
                          row.can_edit
                            ? t("brainformEditKnowledgeNamed", {
                                name: row.knowledge_display_name,
                              })
                            : t("brainformViewKnowledgeNamed", {
                                name: row.knowledge_display_name,
                              })
                        }
                        onEnter={
                          isGenerating || (!currentDoc && !row.can_edit)
                            ? undefined
                            : () =>
                                void openKnowledge(
                                  row,
                                  row.can_edit ? "edit" : "view",
                                )
                        }
                        onRename={
                          row.can_edit
                            ? () => {
                                setRenameSetId(row.canonical_set_id);
                                setRenameValue(row.knowledge_display_name);
                              }
                            : undefined
                        }
                      />
                    )}
                    {failed ? (
                      <DismissibleAlert
                        as="span"
                        className={kAlbum.bad}
                        resetKey={`${row.generation_state}:${generationErrorCode ?? ""}`}
                      >
                        {generationErrorCode &&
                        generationErrorCode !==
                          "provider_confirmation_unavailable"
                          ? t("brainformGenerationFailedReason", {
                              reason: generationErrorCode.replaceAll("_", " "),
                            })
                          : t("brainformGenerationFailed")}
                      </DismissibleAlert>
                    ) : null}
                    {!currentDoc && !row.generation_state ? (
                      <span className={kAlbum.bad} role="status">
                        {t("brainformNoKnowledgeDocument")}
                      </span>
                    ) : null}
                    {row.source_agent_display_name ? (
                      <span className={kAlbum.ag}>
                        {row.source_agent_display_name}
                      </span>
                    ) : null}
                  </KnowledgeCard>
                );
              })}
            </ul>
          ) : (
            <div className={kAlbum.grid}>
              <div className={kAlbum.ghostFirst}>
                <div className={kAlbum.ghostArt} aria-hidden="true">
                  <KnowledgeArt id="kart-empty" />
                </div>
                <p>{t("brainformKnowledgeEmpty")}</p>
              </div>
              <div className={kAlbum.ghost} aria-hidden="true">
                <KnowledgeIcon name="plus" size={36} stroke={2.4} />
              </div>
            </div>
          )}
        </section>
      ) : null}
      {!ragPage &&
      !knowledgePage &&
      !pane &&
      !initialMode &&
      (!loading || embedded) &&
      !loadError &&
      courseId ? (
        <div className={embedded ? styles.embeddedSections : styles.sections}>
          <section
            className={styles.section}
            data-studyform-slot="rag"
            aria-labelledby="brainform-rag-heading"
          >
            <div className={styles.sectionHeading}>
              <div>
                <h2
                  id="brainform-rag-heading"
                  data-ui-guide="knowledge.files"
                  data-ui-guide-text={t("brainformRagIntro")}
                  tabIndex={0}
                >
                  RAG
                </h2>
              </div>
              {canAddRag ? (
                <ModulePlus
                  label={t("brainformNewRag")}
                  onClick={beginNewRag}
                  disabled={Boolean(busyKey)}
                  busy={busyKey === "rag-new"}
                />
              ) : (
                <span className={styles.count}>{ragDocuments.length}</span>
              )}
            </div>
            {loading && !ragDocuments.length ? (
              <LoadingCard size="sm" />
            ) : ragDocuments.length ? (
              <ul className={styles.list}>
                {ragDocuments.map((document) => {
                  const canEdit = document.can_manage_visibility;
                  const status = indexStatusText(document, t);
                  const failed = document.index_status === "failed";
                  return (
                    <li className={styles.row} key={document.id}>
                      <div className={styles.rowCopy}>
                        <div className={styles.titleRow}>
                          {renameDocumentId === document.id ? (
                            <input
                              ref={renameInputRef}
                              className={styles.inlineNameInput}
                              aria-label={t("brainformRagName")}
                              value={renameValue}
                              onChange={(event) =>
                                setRenameValue(event.target.value)
                              }
                              onBlur={() => void saveDocumentName(document)}
                              onKeyDown={(event) => {
                                if (event.key === "Enter") {
                                  event.preventDefault();
                                  event.currentTarget.blur();
                                }
                                if (event.key === "Escape")
                                  setRenameDocumentId(null);
                              }}
                            />
                          ) : (
                            <TitleButton
                              title={document.source_filename}
                              editable={canEdit}
                              enterLabel={t(
                                canEdit
                                  ? "brainformEditRagNamed"
                                  : "brainformViewRagNamed",
                                { name: document.source_filename },
                              )}
                              onEnter={() =>
                                void (canEdit
                                  ? editRag(document)
                                  : viewRag(document))
                              }
                              onRename={
                                canEdit
                                  ? () => {
                                      setRenameDocumentId(document.id);
                                      setRenameValue(
                                        document.source_filename.replace(
                                          /\.[^.]+$/,
                                          "",
                                        ),
                                      );
                                    }
                                  : undefined
                              }
                            />
                          )}
                          {failed ? (
                            <span
                              className={`status-badge status-bad ${styles.failedBadge}`}
                              data-ui-guide="knowledge.indexFailed"
                              data-ui-guide-text={ragIndexFailureReason(
                                document,
                                t,
                              )}
                              tabIndex={0}
                            >
                              <span aria-hidden="true" />
                              failed
                            </span>
                          ) : null}
                        </div>
                        {status ? (
                          <span className={styles.rowStatus} role="status">
                            {status}
                          </span>
                        ) : null}
                      </div>
                      <div className={styles.actions}>
                        <button
                          type="button"
                          className={styles.iconButton}
                          aria-label={t("brainformDownloadRagNamed", {
                            name: document.source_filename,
                          })}
                          data-ui-guide="knowledge.download"
                          disabled={busyKey === `download:${document.id}`}
                          onClick={() => void downloadRag(document)}
                        >
                          <IconDownload />
                        </button>
                        {canEdit ? (
                          <button
                            type="button"
                            className={styles.iconButton}
                            aria-label={t("brainformHideRagNamed", {
                              name: document.source_filename,
                            })}
                            data-ui-guide="knowledge.hide"
                            disabled={busyKey === `hide:${document.id}`}
                            onClick={() => void hideRag(document)}
                          >
                            <IconClose />
                          </button>
                        ) : null}
                        {canEdit && failed ? (
                          <button
                            type="button"
                            className={styles.iconButton}
                            aria-label={t("brainformReindexRagNamed", {
                              name: document.source_filename,
                            })}
                            data-ui-guide="knowledge.reindex"
                            disabled={busyKey === `reindex:${document.id}`}
                            onClick={() => void reindexRag(document)}
                          >
                            <IconRefresh />
                          </button>
                        ) : null}
                        {pendingRagAction?.documentId === document.id ? (
                          <RetryPill
                            className="ml-0"
                            disabled={Boolean(busyKey)}
                            onClick={retryRagAction}
                          >
                            {t("retry")}
                          </RetryPill>
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

          {/* Owner request (2026-10-20): students no longer see the
              Knowledge card; teachers keep it. Data and APIs are untouched. */}
          {role === "teacher" ? (
            <section
              className={styles.section}
              data-studyform-slot="knowledge"
              aria-labelledby="brainform-knowledge-heading"
            >
              <div className={styles.sectionHeading}>
                <div>
                  <h2
                    id="brainform-knowledge-heading"
                    data-ui-guide="knowledge.files"
                    data-ui-guide-text={t("brainformKnowledgeIntro")}
                    tabIndex={0}
                  >
                    {t("brainformKnowledgeHeading")}
                  </h2>
                </div>
                {canAddKnowledge ? (
                  <ModulePlus
                    label={t("brainformNewKnowledge")}
                    onClick={beginNewKnowledge}
                    disabled={Boolean(busyKey)}
                    busy={busyKey === "knowledge-new"}
                  />
                ) : (
                  <span className={styles.count}>
                    {displayedKnowledgeRows.length}
                  </span>
                )}
              </div>
              {displayedKnowledgeRows.length ? (
                <ul className={styles.list}>
                  {displayedKnowledgeRows.map((row) => {
                    const currentDoc = (row.version_seq ?? 0) > 0;
                    const isGenerating = isGenerationActive(
                      row.generation_state,
                    );
                    const jobStatus = generationStatuses[row.canonical_set_id];
                    const generationErrorCode =
                      jobStatus &&
                      jobStatus.job_id === generationJobs[row.canonical_set_id]
                        ? jobStatus.safe_error_code
                        : row.safe_error_code;
                    return (
                      <li className={styles.row} key={row.canonical_set_id}>
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
                                if (event.key === "Escape")
                                  setRenameSetId(null);
                              }}
                            />
                          ) : (
                            // Like a RAG row and a Team or Agent tile: the
                            // enter button shows on hover over the title and
                            // opens the editor, whose Done saves a version
                            // every user reads; a double-click renames.
                            <TitleButton
                              title={row.knowledge_display_name}
                              editable={row.can_edit}
                              enterLabel={
                                row.can_edit
                                  ? t("brainformEditKnowledgeNamed", {
                                      name: row.knowledge_display_name,
                                    })
                                  : t("brainformViewKnowledgeNamed", {
                                      name: row.knowledge_display_name,
                                    })
                              }
                              onEnter={
                                isGenerating || (!currentDoc && !row.can_edit)
                                  ? undefined
                                  : () =>
                                      void openKnowledge(
                                        row,
                                        row.can_edit ? "edit" : "view",
                                      )
                              }
                              onRename={
                                row.can_edit
                                  ? () => {
                                      setRenameSetId(row.canonical_set_id);
                                      setRenameValue(
                                        row.knowledge_display_name,
                                      );
                                    }
                                  : undefined
                              }
                            />
                          )}
                          {!isGenerating &&
                          row.generation_state &&
                          row.generation_state !== "completed" ? (
                            <DismissibleAlert
                              as="span"
                              className={styles.rowStatus}
                              resetKey={`${row.generation_state}:${generationErrorCode ?? ""}`}
                            >
                              {generationErrorCode &&
                              generationErrorCode !==
                                "provider_confirmation_unavailable"
                                ? t("brainformGenerationFailedReason", {
                                    reason: generationErrorCode.replaceAll(
                                      "_",
                                      " ",
                                    ),
                                  })
                                : t("brainformGenerationFailed")}
                            </DismissibleAlert>
                          ) : null}
                          {!currentDoc && !row.generation_state ? (
                            <span className={styles.rowStatus} role="status">
                              {t("brainformNoKnowledgeDocument")}
                            </span>
                          ) : null}
                        </div>
                        <div className={styles.actions}>
                          {isGenerating ? (
                            <button
                              type="button"
                              className={styles.iconButton}
                              aria-label={t("brainformGeneratingNamed", {
                                name: row.knowledge_display_name,
                              })}
                              aria-busy="true"
                              disabled
                            >
                              <span className="spinner" aria-hidden="true" />
                            </button>
                          ) : null}
                          {currentDoc && !isGenerating ? (
                            <button
                              type="button"
                              className={styles.iconButton}
                              aria-label={t("brainformDownloadKnowledgeNamed", {
                                name: row.knowledge_display_name,
                              })}
                              data-ui-guide="knowledge.download"
                              disabled={
                                busyKey ===
                                `download-knowledge:${row.canonical_set_id}`
                              }
                              onClick={() => void downloadKnowledgeSet(row)}
                            >
                              <IconDownload />
                            </button>
                          ) : null}
                          {row.can_edit && !isGenerating ? (
                            <button
                              type="button"
                              className={styles.iconButton}
                              aria-label={t("brainformDeleteKnowledgeNamed", {
                                name: row.knowledge_display_name,
                              })}
                              data-ui-guide="knowledge.hide"
                              disabled={
                                busyKey === `delete-set:${row.canonical_set_id}`
                              }
                              onClick={() => void deleteKnowledge(row)}
                            >
                              <IconClose />
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
            </section>
          ) : null}
        </div>
      ) : null}

      {ragPage && pane?.kind.startsWith("rag") ? (
        <>
          <div className={album.top}>
            <h2 id="brainform-rag-heading">RAG</h2>
            <span className={album.tape} aria-hidden="true" />
            <span className={album.sp} />
            <PageAction
              name="back"
              placement="page"
              onClick={closePane}
              disabled={Boolean(busyKey)}
            />
            {pane.kind === "rag-new" ? (
              <PageAction
                name="done"
                placement="page"
                onClick={() => void saveNewRag()}
                disabled={
                  Boolean(busyKey) ||
                  !newRag.name.trim() ||
                  (!newRag.file && !newRag.markdown.trim()) ||
                  (role !== "teacher" && !(initialGroupId ?? newRag.groupId))
                }
              />
            ) : null}
            {pane.kind === "rag-edit" && selectedDraft ? (
              <PageAction
                name="done"
                placement="page"
                onClick={() => {
                  const current = ragActionPane.current;
                  if (current?.kind !== "rag-edit") return;
                  const draft = ragActionDrafts.current[current.draftKey];
                  if (!draft) return;
                  saveRagAction.current(current.draftKey);
                }}
                disabled={
                  Boolean(busyKey) || !selectedDraft.canEdit || !ragDirty
                }
              />
            ) : null}
          </div>
          <div className={album.spread}>
            {pane.kind === "rag-view" ? (
              <div className={album.cardBig}>
                <div className={album.artBig}>
                  <span className={album.no} aria-hidden="true">
                    #
                    {String(
                      Math.max(
                        0,
                        ragDocuments.findIndex(
                          (item) => item.id === pane.documentId,
                        ),
                      ) + 1,
                    ).padStart(2, "0")}
                  </span>
                  <span className={album.tyBig} aria-hidden="true">
                    {fileExt(
                      ragDocuments.find((item) => item.id === pane.documentId)
                        ?.source_filename ?? pane.filename,
                    )}
                  </span>
                </div>
                <div className={album.plate}>
                  <h2 className={album.nmBig} id="brainform-editor-heading">
                    {pane.filename}
                  </h2>
                </div>
              </div>
            ) : pane.kind === "rag-edit" && !selectedDraft?.canEdit ? (
              <div />
            ) : (
              <label
                className={album.pack}
                data-kind="rag"
                {...ragFileDrop}
                aria-busy={
                  pane.kind === "rag-new"
                    ? busyKey === "rag-new"
                    : busyKey ===
                      `import:${pane.kind === "rag-edit" ? pane.draftKey : ""}`
                }
              >
                <span className={album.disc}>
                  <AlbumIcon name="upload" size={56} stroke={3} />
                </span>
                <span className={album.types} aria-hidden="true">
                  <i>MD</i>
                  <i>PDF</i>
                  <i>DOCX</i>
                </span>
                <input
                  className="sr-only"
                  type="file"
                  aria-label={
                    pane.kind === "rag-new"
                      ? t("uploadRag")
                      : t("knowledgeImportFile")
                  }
                  accept=".md,.pdf,.docx,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  disabled={Boolean(busyKey)}
                  onChange={(event) => {
                    const file = event.currentTarget.files?.[0];
                    event.currentTarget.value = "";
                    if (!file) return;
                    selectRagFile(file);
                  }}
                />
              </label>
            )}
            {pane.kind === "rag-view" ? (
              <div className={album.page2}>
                <ReportMarkdown>{pane.markdown}</ReportMarkdown>
              </div>
            ) : pane.kind === "rag-new" ? (
              <div className={album.blank}>
                <div className={album.in}>
                  <h2 className="sr-only" id="brainform-editor-heading">
                    {t("brainformRagCreateTitle")}
                  </h2>
                  {role !== "teacher" &&
                  !initialGroupId &&
                  ragGroupIds.length > 1 ? (
                    <label className={album.fl}>
                      <span>{t("group")}</span>
                      <select
                        value={newRag.groupId}
                        disabled={busyKey === "rag-new"}
                        onChange={(event) => {
                          const groupId = event.target.value;
                          setNewRag((current) => ({ ...current, groupId }));
                        }}
                      >
                        {groups.map((group) => (
                          <option key={group.id} value={group.id}>
                            {group.name}
                          </option>
                        ))}
                      </select>
                    </label>
                  ) : null}
                  <KnowledgeFilenameField
                    label={t("ragFilename")}
                    className={album.fl}
                    value={newRag.name}
                    disabled={busyKey === "rag-new"}
                    onChange={(name) =>
                      setNewRag((current) => ({ ...current, name }))
                    }
                  />
                  {newRag.file ? (
                    <p className={album.stkWarn} role="status">
                      {t("brainformRagFileStaged", {
                        filename: newRag.file.name,
                      })}{" "}
                      {t("brainformNotMarkdownEditor")}
                    </p>
                  ) : (
                    <KnowledgeMarkdownField
                      className={album.fl}
                      value={newRag.markdown}
                      disabled={busyKey === "rag-new"}
                      readOnly={busyKey === "rag-new"}
                      rows={10}
                      onChange={(markdown) =>
                        setNewRag((current) => ({ ...current, markdown }))
                      }
                    />
                  )}
                </div>
              </div>
            ) : pane.kind === "rag-edit" && selectedDraft ? (
              <div className={album.blank}>
                <div className={album.in}>
                  <h2 className="sr-only" id="brainform-editor-heading">
                    {selectedDraft.filename}
                  </h2>
                  <KnowledgeFilenameField
                    label={t("ragFilename")}
                    className={album.fl}
                    value={selectedDraft.filename}
                    disabled={busyKey === `import:${pane.draftKey}`}
                    readOnly={!selectedDraft.canEdit}
                    onChange={(filename) => {
                      if (!selectedDraft.canEdit) return;
                      updateRagDraft(pane.draftKey, {
                        ...selectedDraft,
                        filename,
                      });
                    }}
                  />
                  {selectedRagFile ? (
                    <p className={album.stkWarn} role="status">
                      {t("brainformRagFileStaged", {
                        filename: selectedRagFile.name,
                      })}{" "}
                      {t("brainformNotMarkdownEditor")}
                    </p>
                  ) : (
                    <KnowledgeMarkdownField
                      className={album.fl}
                      value={selectedDraft.markdown}
                      disabled={busyKey === `import:${pane.draftKey}`}
                      rows={16}
                      readOnly={!selectedDraft.canEdit}
                      onChange={(markdown) =>
                        updateRagDraft(pane.draftKey, {
                          ...selectedDraft,
                          markdown,
                        })
                      }
                    />
                  )}
                </div>
              </div>
            ) : (
              <LoadingCard size="sm" />
            )}
          </div>
        </>
      ) : null}
      {knowledgeEditor ? (
        <>
          <div className={kAlbum.top}>
            <h2
              id="brainform-knowledge-heading"
              className={cn(kAlbum.title, kAlbum.titleEd)}
              data-ui-guide="knowledge.files"
              data-ui-guide-text={t("brainformKnowledgeIntro")}
              tabIndex={0}
            >
              {t("brainformKnowledgeHeading")}
            </h2>
            <span className={kAlbum.tape} aria-hidden="true" />
            <span className={kAlbum.sp} />
            <span className={kAlbum.acts}>
              <PageAction
                name="back"
                placement="page"
                onClick={closePane}
                disabled={Boolean(busyKey)}
              />
              {pane?.kind === "knowledge-new" ? (
                <PageAction
                  name="done"
                  placement="page"
                  onClick={() => void saveNewKnowledge()}
                  disabled={
                    Boolean(busyKey) ||
                    !newKnowledge.name.trim() ||
                    !newKnowledge.markdown.trim()
                  }
                />
              ) : (
                <PageAction
                  name="done"
                  placement="page"
                  onClick={() => void saveKnowledge()}
                  disabled={
                    Boolean(busyKey) ||
                    !markdown?.can_edit ||
                    markdown.audience !== "full" ||
                    !knowledgeDirty
                  }
                />
              )}
            </span>
          </div>
          {pane?.kind === "knowledge-new" || markdown ? (
            <div className={kAlbum.spread}>
              <div className={kAlbum.lcol}>
                {pane?.kind === "knowledge-new" ||
                (markdown?.can_edit && markdown.audience === "full") ? (
                  <label
                    className={kAlbum.pack}
                    data-kind="knowledge"
                    {...knowledgeFileDrop}
                    aria-busy={
                      pane?.kind === "knowledge-new"
                        ? busyKey === "knowledge-new"
                        : busyKey ===
                          `knowledge-save:${markdown?.canonical_set_id}`
                    }
                  >
                    <span className={kAlbum.disc}>
                      <KnowledgeIcon name="upload" size={36} stroke={3} />
                    </span>
                    <input
                      className="sr-only"
                      type="file"
                      aria-label={t("brainformUploadKnowledgeFile")}
                      accept=".md,text/markdown"
                      disabled={Boolean(busyKey)}
                      onChange={(event) => {
                        const file = event.currentTarget.files?.[0];
                        event.currentTarget.value = "";
                        if (file) selectKnowledgeFile(file);
                      }}
                    />
                  </label>
                ) : null}
                <p className={kAlbum.req} aria-hidden="true">
                  {t("brainformUploadKnowledgeFile")}
                </p>
              </div>
              <section
                className={kAlbum.blank}
                aria-labelledby="brainform-editor-heading"
              >
                <div className={kAlbum.in}>
                  <h2 className="sr-only" id="brainform-editor-heading">
                    {pane?.kind === "knowledge-new"
                      ? newKnowledge.name.trim() || t("brainformNewKnowledge")
                      : (markdown?.knowledge_display_name ?? t("loading"))}
                  </h2>
                  {pane?.kind === "knowledge-edit" &&
                  markdown?.version_seq === 0 ? (
                    <p className={styles.empty} role="status">
                      {t("brainformKnowledgeFirstVersionEmpty")}
                    </p>
                  ) : null}
                  <div className="flex flex-col gap-[8px]">
                    <KnowledgeFilenameField
                      label={t("knowledgeFileNameLabel")}
                      fileError={filenameError}
                      invalid={filenameError}
                      describedBy={
                        knowledgeNameError
                          ? "brainform-knowledge-name-error"
                          : undefined
                      }
                      className={cn(album.fl, filenameError && kAlbum.flErr)}
                      value={
                        pane?.kind === "knowledge-new"
                          ? newKnowledge.name
                          : knowledgeNameDraft
                      }
                      disabled={
                        pane?.kind === "knowledge-new"
                          ? busyKey === "knowledge-new"
                          : busyKey ===
                            `knowledge-save:${markdown?.canonical_set_id}`
                      }
                      readOnly={
                        pane?.kind === "knowledge-edit" &&
                        (!markdown?.can_edit || markdown.audience !== "full")
                      }
                      onChange={(name) =>
                        pane?.kind === "knowledge-new"
                          ? setNewKnowledge((current) => ({ ...current, name }))
                          : setKnowledgeNameDraft(name)
                      }
                    />
                    {knowledgeNameError ? (
                      <span
                        id="brainform-knowledge-name-error"
                        className={kAlbum.em}
                      >
                        {knowledgeNameError}
                      </span>
                    ) : null}
                  </div>
                  {pane?.kind === "knowledge-new" ? (
                    <KnowledgeMarkdownField
                      className={album.fl}
                      value={newKnowledge.markdown}
                      disabled={busyKey === "knowledge-new"}
                      readOnly={busyKey === "knowledge-new"}
                      rows={13}
                      onChange={(markdown) =>
                        setNewKnowledge((current) => ({ ...current, markdown }))
                      }
                    />
                  ) : markdown ? (
                    <KnowledgeMarkdownField
                      className={album.fl}
                      value={markdownDraft}
                      disabled={
                        busyKey ===
                        `knowledge-save:${markdown.canonical_set_id}`
                      }
                      readOnly={
                        !markdown.can_edit ||
                        markdown.audience !== "full" ||
                        busyKey ===
                          `knowledge-save:${markdown.canonical_set_id}`
                      }
                      rows={13}
                      onChange={(value) => {
                        const current = knowledgeDrafts[
                          markdown.canonical_set_id
                        ] ?? {
                          markdown: markdown.markdown,
                          expectedVersionSeq: markdown.version_seq,
                        };
                        if (value !== markdownDraft) {
                          mutationStore.abandon(
                            `brainform-markdown:${markdown.canonical_set_id}:${current.expectedVersionSeq}`,
                          );
                        }
                        setMarkdownDraft(value);
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
                  ) : null}
                </div>
              </section>
            </div>
          ) : (
            <LoadingCard size="sm" />
          )}
        </>
      ) : null}
      {pane && !knowledgeEditor && !(ragPage && pane.kind.startsWith("rag")) ? (
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
                    : pane.kind === "knowledge-new"
                      ? newKnowledge.name.trim() || t("brainformNewKnowledge")
                      : pane.kind === "rag-new"
                        ? newRag.name.trim() || t("brainformNewRag")
                        : (markdown?.knowledge_display_name ?? t("loading"))}
              </h2>
            </div>
          </div>

          {pane.kind === "knowledge-new" ? (
            <div className={styles.editorForm}>
              <label
                className={styles.importButton}
                aria-busy={busyKey === "knowledge-new"}
              >
                <IconUpload />
                <input
                  className="sr-only"
                  type="file"
                  aria-label={t("brainformUploadKnowledgeFile")}
                  accept=".md,text/markdown"
                  disabled={Boolean(busyKey)}
                  onChange={(event) => {
                    const file = event.currentTarget.files?.[0];
                    event.currentTarget.value = "";
                    if (file) void importNewKnowledge(file);
                  }}
                />
              </label>
              <KnowledgeFilenameField
                fileError={filenameError}
                className={styles.field}
                value={newKnowledge.name}
                disabled={busyKey === "knowledge-new"}
                onChange={(name) =>
                  setNewKnowledge((current) => ({ ...current, name }))
                }
              />
              <KnowledgeMarkdownField
                className={styles.field}
                value={newKnowledge.markdown}
                disabled={busyKey === "knowledge-new"}
                readOnly={busyKey === "knowledge-new"}
                rows={18}
                onChange={(markdown) =>
                  setNewKnowledge((current) => ({ ...current, markdown }))
                }
              />
            </div>
          ) : null}

          {pane.kind === "rag-new" ? (
            <div className={styles.editorForm}>
              <label
                className={styles.importButton}
                aria-busy={busyKey === "rag-new"}
              >
                <IconUpload />
                <input
                  className="sr-only"
                  type="file"
                  aria-label={t("uploadRag")}
                  accept=".md,.pdf,.docx,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                  disabled={Boolean(busyKey)}
                  onChange={(event) => {
                    const file = event.currentTarget.files?.[0];
                    event.currentTarget.value = "";
                    if (file) void importNewRag(file);
                  }}
                />
              </label>
              {role !== "teacher" &&
              !initialGroupId &&
              ragGroupIds.length > 1 ? (
                <label className={styles.field}>
                  <span>{t("group")}</span>
                  <select
                    value={newRag.groupId}
                    disabled={busyKey === "rag-new"}
                    onChange={(event) => {
                      const groupId = event.target.value;
                      setNewRag((current) => ({ ...current, groupId }));
                    }}
                  >
                    {groups.map((group) => (
                      <option key={group.id} value={group.id}>
                        {group.name}
                      </option>
                    ))}
                  </select>
                </label>
              ) : null}
              <KnowledgeFilenameField
                fileError={filenameError}
                className={styles.field}
                value={newRag.name}
                disabled={busyKey === "rag-new"}
                onChange={(name) =>
                  setNewRag((current) => ({ ...current, name }))
                }
              />
              {newRag.file ? (
                <p className={styles.empty} role="status">
                  {t("brainformRagFileStaged", {
                    filename: newRag.file.name,
                  })}{" "}
                  {t("brainformNotMarkdownEditor")}
                </p>
              ) : (
                <KnowledgeMarkdownField
                  className={styles.field}
                  value={newRag.markdown}
                  disabled={busyKey === "rag-new"}
                  readOnly={busyKey === "rag-new"}
                  rows={18}
                  onChange={(markdown) =>
                    setNewRag((current) => ({ ...current, markdown }))
                  }
                />
              )}
            </div>
          ) : null}

          {pane.kind === "rag-edit" && selectedDraft ? (
            <div className={styles.editorForm}>
              {selectedDraft.canEdit ? (
                <label
                  className={styles.importButton}
                  aria-busy={busyKey === `import:${pane.draftKey}`}
                >
                  <IconUpload />
                  <input
                    className="sr-only"
                    type="file"
                    aria-label={t("knowledgeImportFile")}
                    accept=".md,.pdf,.docx,text/markdown,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                    disabled={Boolean(busyKey)}
                    onChange={(event) => {
                      const file = event.currentTarget.files?.[0];
                      event.currentTarget.value = "";
                      if (file) void importRag(pane.draftKey, file);
                    }}
                  />
                </label>
              ) : null}
              <KnowledgeFilenameField
                fileError={filenameError}
                className={styles.field}
                value={selectedDraft.filename}
                disabled={busyKey === `import:${pane.draftKey}`}
                readOnly={!selectedDraft.canEdit}
                onChange={(filename) => {
                  if (!selectedDraft.canEdit) return;
                  updateRagDraft(pane.draftKey, { ...selectedDraft, filename });
                }}
              />
              {selectedRagFile ? (
                <p className={styles.empty} role="status">
                  {t("brainformRagFileStaged", {
                    filename: selectedRagFile.name,
                  })}{" "}
                  {t("brainformNotMarkdownEditor")}
                </p>
              ) : (
                <KnowledgeMarkdownField
                  className={styles.field}
                  value={selectedDraft.markdown}
                  disabled={busyKey === `import:${pane.draftKey}`}
                  rows={16}
                  readOnly={!selectedDraft.canEdit}
                  onChange={(markdown) =>
                    updateRagDraft(pane.draftKey, {
                      ...selectedDraft,
                      markdown,
                    })
                  }
                />
              )}
            </div>
          ) : null}

          {pane.kind === "rag-view" ? (
            <ReportMarkdown>{pane.markdown}</ReportMarkdown>
          ) : null}

          {(pane.kind === "knowledge-view" || pane.kind === "knowledge-edit") &&
          markdown ? (
            <>
              {markdown.version_seq === 0 ? (
                <p className={styles.empty} role="status">
                  {t("brainformKnowledgeFirstVersionEmpty")}
                </p>
              ) : null}
              {pane.kind === "knowledge-edit" ? (
                <div className={styles.editorForm}>
                  {markdown.can_edit && markdown.audience === "full" ? (
                    <label
                      className={styles.importButton}
                      aria-busy={
                        busyKey ===
                        `knowledge-save:${markdown.canonical_set_id}`
                      }
                    >
                      <IconUpload />
                      <input
                        className="sr-only"
                        type="file"
                        aria-label={t("brainformUploadKnowledgeFile")}
                        accept=".md,text/markdown"
                        disabled={Boolean(busyKey)}
                        onChange={(event) => {
                          const file = event.currentTarget.files?.[0];
                          event.currentTarget.value = "";
                          if (file) void importKnowledgeEdit(file);
                        }}
                      />
                    </label>
                  ) : null}
                  <KnowledgeFilenameField
                    fileError={filenameError}
                    className={styles.field}
                    value={knowledgeNameDraft}
                    disabled={
                      busyKey === `knowledge-save:${markdown.canonical_set_id}`
                    }
                    readOnly={
                      !markdown.can_edit || markdown.audience !== "full"
                    }
                    onChange={setKnowledgeNameDraft}
                  />
                  <KnowledgeMarkdownField
                    className={styles.field}
                    value={markdownDraft}
                    disabled={
                      busyKey === `knowledge-save:${markdown.canonical_set_id}`
                    }
                    readOnly={
                      !markdown.can_edit ||
                      markdown.audience !== "full" ||
                      busyKey === `knowledge-save:${markdown.canonical_set_id}`
                    }
                    rows={18}
                    onChange={(value) => {
                      const current = knowledgeDrafts[
                        markdown.canonical_set_id
                      ] ?? {
                        markdown: markdown.markdown,
                        expectedVersionSeq: markdown.version_seq,
                      };
                      if (value !== markdownDraft) {
                        mutationStore.abandon(
                          `brainform-markdown:${markdown.canonical_set_id}:${current.expectedVersionSeq}`,
                        );
                      }
                      setMarkdownDraft(value);
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
                </div>
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
            </>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

function isFilenameError(error: unknown) {
  if (!error || typeof error !== "object") return false;
  const { details } = error as { details?: { field?: unknown } };
  return details?.field === "display_name" || details?.field === "filename";
}
