"use client";

import { deleteConfirmText } from "../../lib/affected-agents";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";

import { PlatformApiError, type VoiceProfile } from "../../lib/api";
import { useIdempotencyStore } from "../../lib/idempotency";
import {
  cachedVoiceList,
  fetchVoiceList,
  forgetVoiceList,
  voiceListIdentity,
} from "../../lib/voice-list-cache";
import { type MessageKey } from "../../lib/i18n";
import { useSession } from "../session-provider";
import { useT } from "../../lib/i18n";
import {
  ErrorNotice,
  LoadingCard,
  Notice,
  PageIntro,
  SectionCard,
} from "../ui";
import { IconClose, IconPlay, IconPlus } from "../quiet-icons";
import { ModuleCard } from "../studyform-layout";
import { WorkspaceIcon } from "../workspace-icon";
import { PageAction } from "../page-action";
import { buttonVariants } from "../ui/button";
import { AGENT_NEW_BUTTON, agentCard } from "../agent-chrome";
import { cn } from "../../lib/utils";
import selection from "../selection-motion.module.css";
import {
  AlbumMic,
  AlbumRings,
  AlbumTrayAnchor,
  VoiceAlbumCard,
  VoiceAlbumCreate,
  useVoiceAgents,
  voiceAlbum,
} from "./voice-album";

const CONSENT_COPY_VERSION = "voice-consent-v1";

type PreviewState = {
  url: string;
  expiresAt: string;
};

type ScopeStatus = "loading" | "ready" | "denied" | "error";

type ListedVoice = VoiceProfile;

type RetryAction =
  | { kind: "load" }
  | { kind: "enroll"; file: File }
  | { kind: "preview" | "delete"; profileId: string }
  | {
      kind: "rename";
      profile: ListedVoice;
      name: string;
      restoreFocus: boolean;
    };

type VoiceFailure = { cause: unknown; retry: RetryAction | null };

// A terminal voice-clone refusal must not read as a transient provider
// outage: it gets no Retry affordance and is never remapped to the fallback
// voice banner.
function isCloneRefusal(cause: unknown): boolean {
  return (
    cause instanceof PlatformApiError && cause.code === "voice_clone_refused"
  );
}

// A 4xx answer about the file itself (bad audio, wrong type, too large) is
// final for those bytes: retrying the same File can never succeed, and the
// next attempt must be a freshly picked file under a fresh idempotency key.
function isFileRejection(cause: unknown): boolean {
  return (
    cause instanceof PlatformApiError &&
    typeof cause.status === "number" &&
    cause.status >= 400 &&
    cause.status < 500 &&
    cause.status !== 401 &&
    cause.status !== 403 &&
    cause.status !== 408 &&
    cause.status !== 429
  );
}

function voiceAwareCause(cause: unknown): unknown {
  // Only for enroll/preview: supplier outages steer to the platform fallback voice.
  // Do not remap rename/load — a 5xx there is not "provider unavailable".
  // A refused clone is a terminal answer, not an outage, and passes through.
  if (!(cause instanceof PlatformApiError)) return cause;
  if (isCloneRefusal(cause)) return cause;
  const providerDown =
    cause.code === "provider_unavailable" ||
    cause.code === "voice_enrollment_failed" ||
    (typeof cause.status === "number" && cause.status >= 500);
  if (!providerDown) return cause;
  return new PlatformApiError(cause.status, cause.message, {
    code: "voice_provider_unavailable",
    details: cause.details,
    ...(cause.requestId ? { request_id: cause.requestId } : {}),
  });
}

function enrollmentCreated(profile: VoiceProfile | null | undefined): boolean {
  return (
    profile !== null &&
    profile !== undefined &&
    Boolean(profile.id) &&
    (profile.status === "preview_ready" || profile.status === "ready") &&
    !profile.safe_error_code
  );
}

// A deleted voice stays on the server for its audit trail only. A refused
// clone is removed server-side; hide it here too so a list read before that
// sweep does not leave a card.
function listedVoices(profiles: VoiceProfile[]): ListedVoice[] {
  return profiles.filter(
    (profile) =>
      profile.status !== "deleted" &&
      !(
        profile.status === "failed" &&
        profile.safe_error_code === "voice_clone_refused"
      ),
  );
}

function previewIsCurrent(expiresAt: string): boolean {
  const expires = Date.parse(expiresAt);
  return Number.isFinite(expires) && expires > Date.now();
}

function VoiceDisc({ none = false }: { none?: boolean }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        selection.voiceDisc,
        "relative grid size-16 place-items-center rounded-full border-[3px] border-[#111]",
        none
          ? "bg-white text-[18px] leading-none font-black after:content-['∅']"
          : "bg-[repeating-radial-gradient(#222_0_2px,#333_2px_4px)] after:size-5 after:rounded-full after:border-2 after:border-[#111] after:bg-[#FFE14D] after:content-[''] peer-checked:after:bg-[#A3E635]",
        "peer-disabled:opacity-50",
      )}
    >
      <span
        className={cn(
          selection.voiceCheck,
          "absolute -top-1.5 -right-1.5 size-[22px] place-items-center rounded-full border-[2.5px] border-[#111] bg-[#FF4D8D] text-white shadow-[2px_2px_0_#111]",
        )}
      >
        <svg
          width="12"
          height="12"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="3.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="m5 12 4 4L19 6" />
        </svg>
      </span>
    </span>
  );
}

function VoiceSelectedLabel() {
  const t = useT();
  return (
    <span aria-hidden="true" className={selection.selectedLabel}>
      {t("selected")}
    </span>
  );
}

export function VoiceLibrary({
  groupId,
  courseId = null,
  membershipGroupIds = [],
  listenOnly = false,
  embedded = false,
  moduleCard = false,
  initialCreate = false,
  selectedId = null,
  disabled = false,
  onSelect,
  onProfilesChange,
  id,
  album = false,
}: {
  groupId: string | null;
  /** A teacher's own personal voices in this course, instead of a group's. */
  courseId?: string | null;
  /** Groups this person belongs to. Never a course-wide picker. */
  membershipGroupIds?: string[];
  /** A teacher visiting a group: no new voice here. Renaming and deleting
   * follow each voice's can_manage from the server. */
  listenOnly?: boolean;
  embedded?: boolean;
  /** Studyform home: the same ModuleCard frame as the Teams panel beside it. */
  moduleCard?: boolean;
  initialCreate?: boolean;
  /** The Agent's voice. With onSelect the list is a single-choice picker
   * whose None row stands for "no voice", so exactly one row is checked. */
  selectedId?: string | null;
  disabled?: boolean;
  onSelect?: (profileId: string | null) => void;
  onProfilesChange?: (profiles: VoiceProfile[]) => void;
  id?: string;
  /** The dedicated /student/voices and /teacher/voices page: the Voice
   * Sticker Album list. The create screen keeps its old layout. */
  album?: boolean;
}) {
  const t = useT();
  const session = useSession();
  const { api } = session;
  const cacheIdentity = voiceListIdentity(
    session.user?.id,
    session.identityGeneration,
  );
  const listKind = courseId ? "personal" : "group";
  const membershipKey = membershipGroupIds.join("|");
  const scopes = useMemo<string[]>(
    () =>
      courseId
        ? [courseId]
        : groupId
          ? [groupId]
          : membershipKey
            ? membershipKey.split("|")
            : [],
    [courseId, groupId, membershipKey],
  );
  // A return visit shows the list this person was last given at once and
  // refreshes it quietly; the first visit still shows the loading card.
  const [cached] = useState(() => {
    if (scopes.length === 0) return null;
    const lists = scopes.map((scopeId) =>
      cachedVoiceList(api, cacheIdentity, listKind, scopeId),
    );
    return lists.every((list) => list !== undefined)
      ? listedVoices(lists.flat())
      : null;
  });
  const [profiles, setProfiles] = useState<ListedVoice[]>(cached ?? []);
  const [scopeStatus, setScopeStatus] = useState<Record<string, ScopeStatus>>(
    () =>
      cached
        ? Object.fromEntries(
            scopes.map((scopeId) => [scopeId, "ready" as ScopeStatus]),
          )
        : {},
  );
  const [file, setFile] = useState<File | null>(null);
  const [creating, setCreating] = useState(initialCreate && !listenOnly);
  const [loading, setLoading] = useState(scopes.length > 0 && !cached);
  const [busy, setBusy] = useState(false);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const controlsDisabled = busy || disabled;
  const [failure, setFailure] = useState<VoiceFailure | null>(null);
  const [notice, setNotice] = useState<MessageKey | null>(null);
  const [preview, setPreview] = useState<Record<string, PreviewState>>({});
  const [editingName, setEditingName] = useState<{
    id: string;
    value: string;
  } | null>(null);
  const activeName = useRef<string | null>(null);
  const savingName = useRef(false);
  const focusName = useRef<string | null>(null);
  const loadSequence = useRef(0);
  const idempotency = useIdempotencyStore();
  const pickerName = useId();
  const focusNameInput = useCallback((input: HTMLInputElement | null) => {
    input?.focus();
  }, []);

  const load = useCallback(
    async (options?: { quiet?: boolean; reuse?: boolean }) => {
      const sequence = ++loadSequence.current;
      if (scopes.length === 0) {
        setProfiles([]);
        onProfilesChange?.([]);
        setScopeStatus({});
        setFailure(null);
        setLoading(false);
        return;
      }
      // A focus refresh must not blank the list. The Agent editor keeps unsaved
      // AGENT.md in the parent, and this list is the only place a new voice appears.
      if (!options?.quiet) {
        setLoading(true);
        setFailure((current) =>
          current?.retry?.kind === "load" ? null : current,
        );
      }
      const results = await Promise.all(
        scopes.map(async (scopeId) => {
          try {
            return {
              scopeId,
              status: "ready" as const,
              profiles: await fetchVoiceList(
                api,
                cacheIdentity,
                listKind,
                scopeId,
                { reuse: options?.reuse },
              ),
              cause: null,
            };
          } catch (cause) {
            const denied =
              cause instanceof PlatformApiError &&
              (cause.status === 403 || cause.status === 404);
            return {
              scopeId,
              status: denied ? ("denied" as const) : ("error" as const),
              profiles: [] as VoiceProfile[],
              cause,
            };
          }
        }),
      );
      if (sequence !== loadSequence.current) return;
      const nextProfiles = results.flatMap((result) =>
        result.status === "denied" ? [] : listedVoices(result.profiles),
      );
      setProfiles(nextProfiles);
      onProfilesChange?.(nextProfiles);
      setScopeStatus(
        Object.fromEntries(
          results.map((result) => [result.scopeId, result.status]),
        ),
      );
      const failure = results.find((result) => result.status === "error");
      const denial = results.find((result) => result.status === "denied");
      const ready = results.some((result) => result.status === "ready");
      // A refused group is not an empty library. Say so when nothing else loaded.
      const cause = failure?.cause ?? (!ready && denial ? denial.cause : null);
      setFailure((current) => {
        if (current && current.retry?.kind !== "load") return current;
        return cause ? { cause, retry: { kind: "load" } } : null;
      });
      setLoading(false);
    },
    [api, cacheIdentity, listKind, onProfilesChange, scopes],
  );

  useEffect(() => {
    // Join a Studyform prefetch already in flight; a cached list refreshes
    // without blanking.
    const timer = window.setTimeout(
      () => void load({ quiet: cached !== null, reuse: true }),
      0,
    );
    return () => {
      window.clearTimeout(timer);
      loadSequence.current += 1;
    };
  }, [cached, load]);

  const invalidatePreview = useCallback(
    (profileId: string, message: MessageKey) => {
      setPreview((current) => {
        const next = { ...current };
        delete next[profileId];
        return next;
      });
      setFailure(
        (current) =>
          current ?? {
            cause: new Error(t(message)),
            retry: { kind: "preview", profileId },
          },
      );
    },
    [t],
  );

  useEffect(() => {
    const entries = Object.entries(preview);
    if (entries.length === 0) return;
    const expiry = Math.min(
      ...entries.map(([, resource]) => Date.parse(resource.expiresAt)),
    );
    const timer = window.setTimeout(
      () => {
        for (const [profileId, resource] of entries) {
          if (
            !Number.isFinite(Date.parse(resource.expiresAt)) ||
            Date.parse(resource.expiresAt) <= Date.now()
          ) {
            invalidatePreview(profileId, "voicePreviewExpired");
          }
        }
      },
      Math.max(0, Math.min(expiry - Date.now(), 2_147_483_647)),
    );
    return () => window.clearTimeout(timer);
  }, [invalidatePreview, preview]);

  useEffect(() => {
    function refreshVisibleVoices() {
      if (document.visibilityState === "hidden") return;
      void load({ quiet: true });
    }
    window.addEventListener("focus", refreshVisibleVoices);
    document.addEventListener("visibilitychange", refreshVisibleVoices);
    return () => {
      window.removeEventListener("focus", refreshVisibleVoices);
      document.removeEventListener("visibilitychange", refreshVisibleVoices);
    };
  }, [load]);

  const enrollmentGroupId = listenOnly
    ? null
    : courseId &&
        (scopeStatus[courseId] === "ready" || scopeStatus[courseId] === "error")
      ? courseId
      : groupId &&
          (scopeStatus[groupId] === "ready" || scopeStatus[groupId] === "error")
        ? groupId
        : scopes.length === 1 &&
            (scopeStatus[scopes[0]] === "ready" ||
              scopeStatus[scopes[0]] === "error")
          ? scopes[0]
          : null;
  const canEnroll =
    Boolean(enrollmentGroupId) && !loading && !listenOnly && !controlsDisabled;

  async function submitEnrollment(upload = file) {
    if (!canEnroll || !enrollmentGroupId || !upload) return;
    setBusy(true);
    setFailure(null);
    setNotice(null);
    try {
      const options = { idempotency: idempotency.handleFor("voice-enroll") };
      const profile = await (courseId
        ? api.enrollPersonalVoice(
            courseId,
            upload,
            CONSENT_COPY_VERSION,
            options,
          )
        : api.enrollVoice(
            enrollmentGroupId,
            upload,
            CONSENT_COPY_VERSION,
            options,
          ));
      // Created is the server's confirmed terminal state, never the mere
      // arrival of a response: a failed card and a success toast must never
      // describe the same upload.
      if (!enrollmentCreated(profile)) {
        idempotency.abandon("voice-enroll");
        setFailure({
          cause: new PlatformApiError(502, t("errorVoiceEnrollmentFailed"), {
            code: profile?.safe_error_code ?? "voice_enrollment_failed",
          }),
          // Soft-fail responses are terminal for this upload; no auto-retry.
          retry: null,
        });
        await load();
        return;
      }
      idempotency.finish("voice-enroll");
      setFile(null);
      setCreating(false);
      setNotice("voiceProfileCreatedNotice");
      // Owner decision (2026-10-24): a voice just uploaded from an Agent is
      // that Agent's choice. Without an upload the choice stays as it was,
      // None by default.
      if (onSelect && profile) onSelect(profile.id);
      await load();
    } catch (cause) {
      const rejected = isCloneRefusal(cause) || isFileRejection(cause);
      if (rejected) {
        // Drop the rejected file and its key so re-picking a fixed file, even
        // one with the same name, is a brand-new upload and not a replay.
        idempotency.abandon("voice-enroll");
        setFile(null);
      }
      setFailure({
        cause: voiceAwareCause(cause),
        retry: rejected ? null : { kind: "enroll", file: upload },
      });
    } finally {
      setBusy(false);
    }
  }

  function closeNameEditor(profileId: string, restoreFocus: boolean) {
    activeName.current = null;
    if (restoreFocus) focusName.current = profileId;
    setEditingName(null);
  }

  async function saveName(profile: ListedVoice, restoreFocus = false) {
    if (
      controlsDisabled ||
      activeName.current !== profile.id ||
      !editingName ||
      savingName.current
    )
      return;
    const value = editingName.value.trim();
    if (value === (profile.source_filename ?? "")) {
      closeNameEditor(profile.id, restoreFocus);
      return;
    }
    await rename(profile, value, restoreFocus);
  }

  async function rename(
    profile: ListedVoice,
    name: string,
    restoreFocus: boolean,
  ) {
    if (controlsDisabled || savingName.current) return;
    savingName.current = true;
    setBusy(true);
    setFailure(null);
    try {
      const renamed = await api.renameVoiceProfile(profile.id, name);
      // The next visit must not show the old name from the cached list.
      for (const scopeId of scopes)
        forgetVoiceList(api, cacheIdentity, listKind, scopeId);
      setProfiles((current) =>
        current.map((item) =>
          item.id === profile.id ? { ...item, ...renamed } : item,
        ),
      );
      closeNameEditor(profile.id, restoreFocus);
    } catch (cause) {
      setFailure({
        cause,
        retry: { kind: "rename", profile, name, restoreFocus },
      });
    } finally {
      savingName.current = false;
      setBusy(false);
    }
  }

  async function makePreview(profileId: string) {
    if (controlsDisabled) return;
    setBusy(true);
    setFailure(null);
    setNotice(null);
    try {
      const resource = await api.createVoicePreview(profileId);
      if (!previewIsCurrent(resource.expires_at)) {
        invalidatePreview(profileId, "voicePreviewExpired");
        return;
      }
      setPreview((current) => ({
        ...current,
        [profileId]: {
          url: resource.playback_url,
          expiresAt: resource.expires_at,
        },
      }));
      setFailure((current) => {
        const retry = current?.retry;
        return retry?.kind === "preview" && retry.profileId === profileId
          ? null
          : current;
      });
    } catch (cause) {
      setFailure({
        cause: voiceAwareCause(cause),
        retry: { kind: "preview", profileId },
      });
    } finally {
      setBusy(false);
    }
  }

  // Agents using a deleted voice get a new version without it (silent in
  // Immerse); Debates keep their own voice, so deleting never blocks one.
  async function remove(profile: ListedVoice) {
    if (controlsDisabled) return;
    const message = await deleteConfirmText(
      t("voiceDeleteConfirm"),
      () => api.voiceAffectedAgents(profile.id),
      (names) => t("deleteAffectsAgents", { names }),
    );
    if (!window.confirm(message)) return;
    setBusy(true);
    setFailure(null);
    setNotice(null);
    const handle = `voice-delete:${profile.id}`;
    setDeletingId(profile.id);
    try {
      await api.deleteVoiceProfile(profile.id, {
        idempotency: idempotency.handleFor(handle),
      });
      idempotency.finish(handle);
      setPreview((current) => {
        const next = { ...current };
        delete next[profile.id];
        return next;
      });
      // A deleted voice cannot stay the Agent's choice; the picker falls back
      // to None rather than leaving no row checked.
      if (onSelect && selectedId === profile.id) onSelect(null);
      await load();
    } catch (cause) {
      setFailure({ cause, retry: { kind: "delete", profileId: profile.id } });
    } finally {
      setDeletingId(null);
      setBusy(false);
    }
  }

  function retryFailure() {
    if (!failure || controlsDisabled) return;
    // A terminal refusal offers no Retry; the failure card explains and the
    // teacher chooses a different file or path.
    const action = failure.retry;
    if (!action) return;
    if (action.kind === "load") void load();
    else if (action.kind === "enroll") void submitEnrollment(action.file);
    else if (action.kind === "preview") void makePreview(action.profileId);
    else if (action.kind === "delete") {
      const profile = profiles.find((item) => item.id === action.profileId);
      if (profile) void remove(profile);
    } else if (action.kind === "rename")
      void rename(action.profile, action.name, action.restoreFocus);
  }

  // Leaving the form creates nothing: the chosen file is discarded and the
  // next upload starts a fresh idempotent request.
  function cancelCreate() {
    idempotency.abandon("voice-enroll");
    setCreating(false);
    setFailure(null);
    setFile(null);
  }

  function selectVoiceFile(file: File | undefined) {
    idempotency.abandon("voice-enroll");
    setFailure(null);
    setFile(file ?? null);
  }

  // The album's record player; its consent card is the create button here.
  // No sidebar Done, and the sidebar never changes while this panel is open.
  const form = (
    <div className="grid min-w-0 gap-4">
      {failure ? (
        <ErrorNotice
          inline
          error={failure.cause}
          onRetry={
            controlsDisabled || !failure.retry ? undefined : retryFailure
          }
        />
      ) : null}
      <VoiceAlbumCreate
        busy={busy}
        disabled={controlsDisabled}
        onFile={selectVoiceFile}
        fileName={file?.name ?? null}
        requirement={t("voiceSampleFile")}
        consent={t("voiceConsent")}
        consentAction={{
          onConfirm: () => void submitEnrollment(),
          disabled: !file || controlsDisabled || !canEnroll,
          busy,
          describedBy: !file ? "voice-consent-hint" : "voice-sample-req",
        }}
        input={
          <input
            className="sr-only"
            type="file"
            disabled={controlsDisabled}
            accept=".wav,.mp3,.m4a,audio/wav,audio/mpeg,audio/mp4"
            onChange={(event) => {
              selectVoiceFile(event.currentTarget.files?.[0]);
              // Browsers fire change only when the chosen path differs, so
              // re-picking an edited file with the same name after a failure
              // would silently keep the stale File. Reset so every pick fires.
              event.currentTarget.value = "";
            }}
            aria-label={t("voiceSampleFile")}
            aria-describedby="voice-sample-req"
            data-ui-guide="voice.uploadSample"
          />
        }
      />
      {/* Students read a grey button as "upload is broken" (2026-10-20):
          say why it is waiting. */}
      {!file ? (
        <p
          id="voice-consent-hint"
          className="m-0 font-body text-sm font-bold text-[#555]"
        >
          {t("voiceSelectFileFirst")}
        </p>
      ) : null}
    </div>
  );

  const arcadePicker = Boolean(onSelect);
  // Option A: a record per voice, its name below, its keys under that.
  function arcadeRow(selected: boolean) {
    return cn(
      "grid w-[104px] min-w-0 content-start justify-items-center gap-1.5",
      selected && "is-selected",
    );
  }
  function arcadeChoice() {
    return cn(
      selection.voiceChoice,
      "grid min-w-0 cursor-pointer justify-items-center gap-1.5 font-body text-ink has-[input:disabled]:cursor-not-allowed",
    );
  }
  function arcadeRadio() {
    return "peer sr-only";
  }
  function arcadeName() {
    return cn(
      selection.voiceName,
      "max-w-full rounded-md border-[3px] border-[#111] bg-white px-2 py-px text-center font-body text-xs leading-[1.4] font-extrabold wrap-anywhere peer-checked:bg-[#FFE14D]",
    );
  }
  const selectedListed = profiles.some(
    (profile) => profile.id === selectedId && profile.status === "ready",
  );
  // The picker always has exactly one checked row: None, a listed ready voice,
  // or, for a binding this list cannot show (deleted, or not visible to this
  // person), the saved "Current voice" until another row is chosen.
  const pickerRows =
    onSelect && !loading ? (
      <>
        <li
          className={
            arcadePicker
              ? arcadeRow(selectedId === null)
              : "group flex min-w-0 flex-wrap items-center justify-between gap-x-2.5 gap-y-1 rounded-xl border border-[#ebe5df] bg-[#fdfaf3] px-[14px] py-1.5 transition-[box-shadow,border-color] duration-200 hover:border-[#ddd3c4] hover:shadow-[0_6px_18px_rgb(64_52_32/0.06)]"
          }
          data-choice="none"
          data-selected={selectedId === null ? "true" : undefined}
        >
          <label
            className={
              arcadePicker
                ? arcadeChoice()
                : "flex min-h-8 min-w-0 flex-[1_1_0] cursor-pointer items-center gap-2.5 has-[input:disabled]:cursor-default"
            }
          >
            <input
              className={
                arcadePicker
                  ? arcadeRadio()
                  : "radio m-0 inline-grid size-[18px] shrink-0 appearance-none place-items-center rounded-full border-[1.5px] border-[#8b7d66] bg-transparent cursor-inherit before:size-2.5 before:rounded-full before:bg-(--gold,#967c50) before:content-[''] before:scale-0 before:transition-transform before:duration-150 checked:border-(--gold,#967c50) checked:before:scale-100 disabled:border-[#cfc8bb] focus-visible:outline focus-visible:outline-2 focus-visible:outline-(--gold) focus-visible:outline-offset-[3px]"
              }
              type="radio"
              name={pickerName}
              checked={selectedId === null}
              disabled={controlsDisabled}
              onChange={() => onSelect(null)}
            />
            {arcadePicker ? <VoiceDisc none /> : null}
            <span
              className={
                arcadePicker
                  ? arcadeName()
                  : "m-0 min-w-0 flex-[1_1_0] overflow-hidden border-0 bg-transparent p-0 font-(family-name:--display-serif) text-[1.05rem] font-[650] leading-[1.25] tracking-[-0.01em] text-left text-ellipsis whitespace-nowrap text-inherit group-data-[status=failed]:text-[#8b887f] group-data-[status=deleting]:text-[#8b887f] group-data-[status=outcome_unknown]:text-[#8b887f] cursor-pointer disabled:cursor-default focus-visible:outline focus-visible:outline-2 focus-visible:outline-(--gold) focus-visible:outline-offset-4"
              }
            >
              {t("voiceNoneOption")}
            </span>
            {arcadePicker ? <VoiceSelectedLabel /> : null}
          </label>
        </li>
        {selectedId && !selectedListed ? (
          <li
            className={
              arcadePicker
                ? arcadeRow(true)
                : "group flex min-w-0 flex-wrap items-center justify-between gap-x-2.5 gap-y-1 rounded-xl border border-[#ebe5df] bg-[#fdfaf3] px-[14px] py-1.5 transition-[box-shadow,border-color] duration-200 hover:border-[#ddd3c4] hover:shadow-[0_6px_18px_rgb(64_52_32/0.06)]"
            }
            data-choice="current"
            data-selected="true"
          >
            <label
              className={
                arcadePicker
                  ? arcadeChoice()
                  : "flex min-h-8 min-w-0 flex-[1_1_0] cursor-pointer items-center gap-2.5 has-[input:disabled]:cursor-default"
              }
            >
              <input
                className={
                  arcadePicker
                    ? arcadeRadio()
                    : "radio m-0 inline-grid size-[18px] shrink-0 appearance-none place-items-center rounded-full border-[1.5px] border-[#8b7d66] bg-transparent cursor-inherit before:size-2.5 before:rounded-full before:bg-(--gold,#967c50) before:content-[''] before:scale-0 before:transition-transform before:duration-150 checked:border-(--gold,#967c50) checked:before:scale-100 disabled:border-[#cfc8bb] focus-visible:outline focus-visible:outline-2 focus-visible:outline-(--gold) focus-visible:outline-offset-[3px]"
                }
                type="radio"
                name={pickerName}
                checked
                disabled={controlsDisabled}
                onChange={() => undefined}
              />
              {arcadePicker ? <VoiceDisc /> : null}
              <span
                className={
                  arcadePicker
                    ? arcadeName()
                    : "m-0 min-w-0 flex-[1_1_0] overflow-hidden border-0 bg-transparent p-0 font-(family-name:--display-serif) text-[1.05rem] font-[650] leading-[1.25] tracking-[-0.01em] text-left text-ellipsis whitespace-nowrap text-inherit group-data-[status=failed]:text-[#8b887f] group-data-[status=deleting]:text-[#8b887f] group-data-[status=outcome_unknown]:text-[#8b887f] cursor-pointer disabled:cursor-default focus-visible:outline focus-visible:outline-2 focus-visible:outline-(--gold) focus-visible:outline-offset-4"
                }
              >
                {t("currentVoiceBinding")}
              </span>
              {arcadePicker ? <VoiceSelectedLabel /> : null}
            </label>
          </li>
        ) : null}
      </>
    ) : null;

  const albumList = album && !onSelect && !embedded;
  const voiceAgents = useVoiceAgents(profiles, albumList);

  function nameField(
    profile: ListedVoice,
    name: string,
    editing: boolean,
    manageable: boolean,
    inAlbum: boolean,
  ) {
    if (editing && editingName) {
      return (
        <input
          className={
            inAlbum
              ? voiceAlbum.nameInput
              : "m-0 min-w-0 flex-[1_1_0] w-auto px-1 border border-(--workspace-border,var(--line)) rounded bg-(--workspace-content,var(--surface-subtle)) text-(--ink) font-[inherit] text-base font-semibold leading-normal text-left"
          }
          aria-label={t("voiceName")}
          value={editingName.value}
          readOnly={controlsDisabled}
          ref={focusNameInput}
          onChange={(event) => {
            setFailure(null);
            setEditingName({
              id: profile.id,
              value: event.target.value,
            });
          }}
          onBlur={() => void saveName(profile)}
          onKeyDown={(event) => {
            if (event.nativeEvent.isComposing) return;
            if (event.key === "Enter") {
              event.preventDefault();
              void saveName(profile, true);
            } else if (event.key === "Escape" && !savingName.current) {
              event.preventDefault();
              closeNameEditor(profile.id, true);
            }
          }}
        />
      );
    }
    if (!manageable) {
      return (
        <span
          className={
            inAlbum
              ? voiceAlbum.vn
              : "m-0 min-w-0 flex-[1_1_0] overflow-hidden border-0 bg-transparent p-0 font-(family-name:--display-serif) text-[1.05rem] font-[650] leading-[1.25] tracking-[-0.01em] text-left text-ellipsis whitespace-nowrap text-inherit group-data-[status=failed]:text-[#8b887f] group-data-[status=deleting]:text-[#8b887f] group-data-[status=outcome_unknown]:text-[#8b887f] cursor-pointer disabled:cursor-default focus-visible:outline focus-visible:outline-2 focus-visible:outline-(--gold) focus-visible:outline-offset-4"
          }
        >
          {name}
        </span>
      );
    }
    return (
      <button
        className={
          inAlbum
            ? voiceAlbum.vn
            : "m-0 min-w-0 flex-[1_1_0] overflow-hidden border-0 bg-transparent p-0 font-(family-name:--display-serif) text-[1.05rem] font-[650] leading-[1.25] tracking-[-0.01em] text-left text-ellipsis whitespace-nowrap text-inherit group-data-[status=failed]:text-[#8b887f] group-data-[status=deleting]:text-[#8b887f] group-data-[status=outcome_unknown]:text-[#8b887f] cursor-pointer disabled:cursor-default focus-visible:outline focus-visible:outline-2 focus-visible:outline-(--gold) focus-visible:outline-offset-4"
        }
        type="button"
        disabled={controlsDisabled || profile.status === "deleted"}
        ref={(button) => {
          if (button && focusName.current === profile.id) {
            button.focus();
            focusName.current = null;
          }
        }}
        onClick={() => {
          activeName.current = profile.id;
          setFailure(null);
          setEditingName({
            id: profile.id,
            value: profile.source_filename ?? "",
          });
        }}
      >
        {name}
      </button>
    );
  }

  function previewButton(
    profile: ListedVoice,
    manageable: boolean,
    playable: boolean,
    inAlbum: boolean,
  ) {
    if (!(manageable || profile.status === "ready")) return null;
    return (
      <button
        className={
          inAlbum
            ? cn(voiceAlbum.ib, voiceAlbum.play)
            : cn(
                buttonVariants({ variant: "neutral", size: "icon" }),
                "min-h-0 rounded-[10px] p-0",
              )
        }
        aria-label={t("voicePreview")}
        data-ui-guide="voice.preview"
        type="button"
        disabled={controlsDisabled || !playable}
        onClick={() => void makePreview(profile.id)}
      >
        <IconPlay />
      </button>
    );
  }

  // Every row keeps its ×, whatever the status: enrolling, failed, refused,
  // outcome unknown or an earlier delete still in progress. The server
  // soft-deletes any of them and cleans up the supplier voice on a
  // best-effort basis. While this row's delete runs, × stays visible as a
  // disabled spinner.
  function deleteButton(
    profile: ListedVoice,
    name: string,
    manageable: boolean,
    inAlbum: boolean,
  ) {
    if (!manageable) return null;
    return (
      <button
        className={
          inAlbum
            ? cn(voiceAlbum.ib, voiceAlbum.del)
            : cn(
                buttonVariants({ variant: "neutral", size: "icon" }),
                "min-h-0 rounded-[10px] p-0",
              )
        }
        aria-label={t("voiceDeleteNamed", { name })}
        aria-busy={deletingId === profile.id || undefined}
        data-ui-guide="voice.delete"
        type="button"
        disabled={controlsDisabled}
        onClick={() => void remove(profile)}
      >
        {deletingId === profile.id ? (
          <span className="spinner" aria-hidden="true" />
        ) : (
          <IconClose />
        )}
      </button>
    );
  }

  function previewAudio(profile: ListedVoice, inAlbum: boolean) {
    if (!preview[profile.id]) return null;
    return (
      <audio
        className={
          inAlbum
            ? voiceAlbum.audio
            : "col-span-full w-full min-w-0 flex-[1_0_100%]"
        }
        controls
        autoPlay
        preload="auto"
        src={preview[profile.id].url}
        onError={() => invalidatePreview(profile.id, "voicePreviewFailed")}
      />
    );
  }

  const list =
    profiles.length > 0 || pickerRows ? (
      <ul
        className={
          albumList
            ? voiceAlbum.grid
            : arcadePicker
              ? "m-0 flex list-none flex-wrap gap-x-4 gap-y-5 p-0"
              : "m-0 grid list-none gap-2 p-0"
        }
        role={onSelect ? "radiogroup" : undefined}
        aria-label={onSelect ? t("voices") : undefined}
      >
        {pickerRows}
        {profiles.map((profile) => {
          const name = profile.source_filename ?? t("voiceCustom");
          const editing = editingName?.id === profile.id;
          // A groupmate's ready voice can be chosen and heard, but only its
          // creator renames or deletes it.
          const manageable = profile.can_manage !== false;
          const playable =
            profile.status === "preview_ready" || profile.status === "ready";
          if (albumList) {
            return (
              <VoiceAlbumCard
                key={profile.id}
                index={profiles.indexOf(profile)}
                profile={profile}
                agents={voiceAgents[profile.id]}
                name={nameField(profile, name, editing, manageable, true)}
                footer={
                  <>
                    {previewButton(profile, manageable, playable, true)}
                    <span className="flex-1" />
                    {deleteButton(profile, name, manageable, true)}
                  </>
                }
                audio={previewAudio(profile, true)}
              />
            );
          }
          return (
            <li
              className={
                arcadePicker
                  ? arcadeRow(selectedId === profile.id)
                  : "group flex min-w-0 flex-wrap items-center justify-between gap-x-2.5 gap-y-1 rounded-xl border border-[#ebe5df] bg-[#fdfaf3] px-[14px] py-1.5 transition-[box-shadow,border-color] duration-200 hover:border-[#ddd3c4] hover:shadow-[0_6px_18px_rgb(64_52_32/0.06)]"
              }
              key={profile.id}
              data-status={profile.status}
              data-selected={
                arcadePicker && selectedId === profile.id ? "true" : undefined
              }
            >
              {editing ? (
                nameField(profile, name, editing, manageable, false)
              ) : onSelect ? (
                <label
                  className={
                    arcadePicker
                      ? arcadeChoice()
                      : "flex min-h-8 min-w-0 flex-[1_1_0] cursor-pointer items-center gap-2.5 has-[input:disabled]:cursor-default"
                  }
                >
                  <input
                    className={
                      arcadePicker
                        ? arcadeRadio()
                        : "radio m-0 inline-grid size-[18px] shrink-0 appearance-none place-items-center rounded-full border-[1.5px] border-[#8b7d66] bg-transparent cursor-inherit before:size-2.5 before:rounded-full before:bg-(--gold,#967c50) before:content-[''] before:scale-0 before:transition-transform before:duration-150 checked:border-(--gold,#967c50) checked:before:scale-100 disabled:border-[#cfc8bb] focus-visible:outline focus-visible:outline-2 focus-visible:outline-(--gold) focus-visible:outline-offset-[3px]"
                    }
                    type="radio"
                    name={pickerName}
                    checked={selectedId === profile.id}
                    disabled={controlsDisabled || profile.status !== "ready"}
                    onChange={() => onSelect(profile.id)}
                  />
                  {arcadePicker ? <VoiceDisc /> : null}
                  <span
                    className={
                      arcadePicker
                        ? arcadeName()
                        : "m-0 min-w-0 flex-[1_1_0] overflow-hidden border-0 bg-transparent p-0 font-(family-name:--display-serif) text-[1.05rem] font-[650] leading-[1.25] tracking-[-0.01em] text-left text-ellipsis whitespace-nowrap text-inherit group-data-[status=failed]:text-[#8b887f] group-data-[status=deleting]:text-[#8b887f] group-data-[status=outcome_unknown]:text-[#8b887f] cursor-pointer disabled:cursor-default focus-visible:outline focus-visible:outline-2 focus-visible:outline-(--gold) focus-visible:outline-offset-4"
                    }
                  >
                    {name}
                  </span>
                  {arcadePicker ? <VoiceSelectedLabel /> : null}
                </label>
              ) : (
                nameField(profile, name, editing, manageable, false)
              )}
              <div
                className={
                  arcadePicker
                    ? "flex shrink-0 items-center gap-1.5"
                    : "flex shrink-0 items-center gap-0.5"
                }
              >
                {previewButton(profile, manageable, playable, false)}
                {deleteButton(profile, name, manageable, false)}
              </div>
              {previewAudio(profile, false)}
            </li>
          );
        })}
        {albumList
          ? Array.from(
              { length: (3 - (profiles.length % 3)) % 3 },
              (_, index) => (
                <li
                  key={`ghost-${index}`}
                  className={voiceAlbum.ghost}
                  aria-hidden="true"
                >
                  {index === 0 ? "+" : null}
                </li>
              ),
            )
          : null}
      </ul>
    ) : null;

  const body = creating ? (
    form
  ) : failure || loading || list ? (
    <>
      {failure ? (
        <ErrorNotice
          inline
          error={failure.cause}
          onRetry={
            controlsDisabled || !failure.retry ? undefined : retryFailure
          }
        />
      ) : null}
      {loading ? <LoadingCard size="lg" count={3} /> : null}
      {list}
    </>
  ) : undefined;

  const createAction = listenOnly ? null : creating ? (
    // Top-right, where New was: back to the list, nothing is uploaded. Icon
    // and word, in the same key as New (2026-11-03: it was icon only).
    <button
      className={
        arcadePicker
          ? AGENT_NEW_BUTTON
          : cn(
              buttonVariants({ variant: "neutral" }),
              "gap-1.5 font-display text-base font-extrabold",
            )
      }
      type="button"
      data-ui-guide="voice.cancelCreate"
      disabled={controlsDisabled}
      onClick={cancelCreate}
    >
      <WorkspaceIcon name="back" size={16} />
      <span>{t("back")}</span>
    </button>
  ) : (
    <button
      type="button"
      aria-label={t("voiceCreateTitle")}
      disabled={controlsDisabled || !canEnroll}
      onClick={() => setCreating(true)}
      className={
        albumList
          ? voiceAlbum.pn
          : arcadePicker
            ? AGENT_NEW_BUTTON
            : cn(
                buttonVariants({ variant: "default" }),
                "gap-1.5 font-display text-base font-extrabold",
              )
      }
    >
      <IconPlus size={16} />
      <span aria-hidden="true">{t("voiceCreateTitle")}</span>
    </button>
  );

  if (albumList && creating) {
    const titleId = id ? `${id}-title` : "voices-title";
    return (
      <div id={id} data-voice-album="v2" data-voice-create="p2-tab">
        <section className={voiceAlbum.alb} aria-labelledby={titleId}>
          <AlbumRings />
          <div
            className={`${voiceAlbum.top} max-md:flex-wrap max-md:gap-x-[12px] max-md:gap-y-[16px] max-md:mb-[22px]`}
          >
            <h2 id={titleId} className={voiceAlbum.h2}>
              {t("voices")}
            </h2>
            <span
              className={`${voiceAlbum.tape} max-md:w-[44px]`}
              aria-hidden="true"
            />
            <span className="flex-1 max-md:basis-full max-md:h-0" />
            {/* Back / Done inside the album top row (same band as list New). */}
            <PageAction
              name="back"
              placement="page"
              onClick={cancelCreate}
              disabled={controlsDisabled}
              guide="voice.cancelCreate"
            />
            <PageAction
              name="done"
              placement="page"
              onClick={() => void submitEnrollment()}
              disabled={!file || controlsDisabled || !canEnroll}
              busy={busy}
              describedBy="voice-sample-req voice-consent-text"
            />
          </div>
          {failure ? (
            <ErrorNotice
              inline
              error={failure.cause}
              onRetry={
                controlsDisabled || !failure.retry ? undefined : retryFailure
              }
            />
          ) : null}
          <VoiceAlbumCreate
            busy={busy}
            disabled={controlsDisabled}
            onFile={selectVoiceFile}
            fileName={file?.name ?? null}
            requirement={t("voiceSampleFile")}
            consent={t("voiceConsent")}
            input={
              <input
                className="sr-only"
                type="file"
                disabled={controlsDisabled}
                accept=".wav,.mp3,.m4a,audio/wav,audio/mpeg,audio/mp4"
                onChange={(event) => {
                  selectVoiceFile(event.currentTarget.files?.[0]);
                  event.currentTarget.value = "";
                }}
                aria-label={t("voiceSampleFile")}
                aria-describedby="voice-sample-req"
              />
            }
          />
          {failure ? <AlbumTrayAnchor /> : null}
        </section>
      </div>
    );
  }

  if (albumList && !creating) {
    const titleId = id ? `${id}-title` : "voices-title";
    return (
      <div id={id} data-voice-album="v2">
        {notice ? (
          <Notice tone="success" onClose={() => setNotice(null)}>
            {t(notice)}
          </Notice>
        ) : null}
        <section className={voiceAlbum.alb} aria-labelledby={titleId}>
          <AlbumRings />
          <div className={voiceAlbum.top}>
            <h2 id={titleId} className={voiceAlbum.h2}>
              {t("voices")}
            </h2>
            <span className={voiceAlbum.tape} aria-hidden="true" />
            <span className="flex-1" />
            {createAction}
          </div>
          {failure ? (
            <ErrorNotice
              inline
              error={failure.cause}
              onRetry={
                controlsDisabled || !failure.retry ? undefined : retryFailure
              }
            />
          ) : null}
          {loading ? <LoadingCard size="lg" count={3} /> : null}
          {list ??
            (loading ? null : (
              <ul className={voiceAlbum.grid}>
                {!loading && !failure ? (
                  <li className={voiceAlbum.ghostFirst}>
                    <AlbumMic />
                    <p>{t("voiceNone")}</p>
                  </li>
                ) : (
                  <li className={voiceAlbum.skel} aria-hidden="true" />
                )}
                <li
                  className={failure ? voiceAlbum.skel : voiceAlbum.ghost}
                  aria-hidden="true"
                />
                <li
                  className={failure ? voiceAlbum.skel : voiceAlbum.ghost}
                  aria-hidden="true"
                />
              </ul>
            ))}
          {failure ? <AlbumTrayAnchor /> : null}
        </section>
      </div>
    );
  }

  return (
    <div
      className={arcadePicker ? "min-w-0" : "grid gap-6"}
      id={id}
      data-arcade-voices={arcadePicker ? "v2" : undefined}
    >
      {embedded || moduleCard ? null : <PageIntro title={t("voices")} />}
      {notice ? (
        <Notice tone="success" onClose={() => setNotice(null)}>
          {t(notice)}
        </Notice>
      ) : null}
      {embedded && !moduleCard ? (
        // Match Agent Avatar / AGENT.md and Team SectionCard title metrics.
        <SectionCard
          title={t("voices")}
          action={createAction}
          className={cn(agentCard("voices", profiles.length === 0), "mb-0")}
        >
          {body ?? <p className="muted-copy">{t("voiceNone")}</p>}
        </SectionCard>
      ) : (
        <ModuleCard
          title={t("voices")}
          labelledBy={id ? `${id}-title` : "voices-title"}
          empty={body ? undefined : t("voiceNone")}
          action={createAction}
        >
          {body}
        </ModuleCard>
      )}
    </div>
  );
}
