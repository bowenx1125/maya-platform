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
import { statusLabel, type MessageKey } from "../../lib/i18n";
import { useSession } from "../session-provider";
import { useT } from "../../lib/i18n";
import {
  ErrorNotice,
  LoadingCard,
  Notice,
  PageIntro,
  SectionCard,
} from "../ui";
import { IconClose, IconPlay, IconUpload } from "../quiet-icons";
import { ModuleCard, ModulePlus } from "../studyform-layout";
import { WorkspaceIcon } from "../workspace-icon";
import cards from "../knowledge/brainform-workspace.module.css";
import styles from "./voice-library.module.css";

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
}: {
  groupId: string | null;
  /** A teacher's own personal voices in this course, instead of a group's. */
  courseId?: string | null;
  /** Groups this person belongs to. Never a course-wide picker. */
  membershipGroupIds?: string[];
  /** Accounts opens a group so a teacher can play its voices. */
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

  const form = (
    <div className={styles.uploadCard}>
      {failure ? (
        <ErrorNotice
          inline
          error={failure.cause}
          onRetry={
            controlsDisabled || !failure.retry ? undefined : retryFailure
          }
        />
      ) : null}
      <div className={styles.uploadRow}>
        <label
          className={styles.uploadButton}
          data-ui-guide="voice.uploadSample"
          aria-busy={controlsDisabled || undefined}
        >
          <IconUpload />
          <input
            className="sr-only"
            type="file"
            disabled={controlsDisabled}
            accept=".wav,.mp3,.m4a,audio/wav,audio/mpeg,audio/mp4"
            onChange={(event) => {
              idempotency.abandon("voice-enroll");
              setFailure(null);
              setFile(event.target.files?.[0] ?? null);
              // Browsers fire change only when the chosen path differs, so
              // re-picking an edited file with the same name after a failure
              // would silently keep the stale File. Reset so every pick fires.
              event.target.value = "";
            }}
            aria-label={t("voiceSampleFile")}
          />
        </label>
        {file ? (
          <span className={styles.selectedFile} aria-live="polite">
            {file.name}
          </span>
        ) : null}
      </div>
      {/* Confirming consent is the create step: no sidebar Done, and the
          sidebar never changes while this panel is open. */}
      <button
        className={styles.consent}
        type="button"
        disabled={!file || controlsDisabled || !canEnroll}
        aria-busy={busy || undefined}
        aria-describedby={!file ? "voice-consent-hint" : undefined}
        title={!file ? t("voiceSelectFileFirst") : undefined}
        onClick={() => void submitEnrollment()}
      >
        {busy ? <span className="spinner" aria-hidden="true" /> : null}
        <span>{t("voiceConsent")}</span>
      </button>
      {/* Students read the grey button as "upload is broken" (2026-10-20):
          say why it is waiting. */}
      {!file ? (
        <p id="voice-consent-hint" className={styles.consentHint}>
          {t("voiceSelectFileFirst")}
        </p>
      ) : null}
    </div>
  );

  const selectedListed = profiles.some(
    (profile) => profile.id === selectedId && profile.status === "ready",
  );
  // The picker always has exactly one checked row: None, a listed ready voice,
  // or, for a binding this list cannot show (deleted, or not visible to this
  // person), the saved "Current voice" until another row is chosen.
  const pickerRows =
    onSelect && !loading ? (
      <>
        <li className={styles.voiceRow} data-choice="none">
          <label className={styles.voiceChoice}>
            <input
              className={styles.radio}
              type="radio"
              name={pickerName}
              checked={selectedId === null}
              disabled={controlsDisabled}
              onChange={() => onSelect(null)}
            />
            <span className={styles.voiceName}>{t("voiceNoneOption")}</span>
          </label>
        </li>
        {selectedId && !selectedListed ? (
          <li className={styles.voiceRow} data-choice="current">
            <label className={styles.voiceChoice}>
              <input
                className={styles.radio}
                type="radio"
                name={pickerName}
                checked
                disabled={controlsDisabled}
                onChange={() => undefined}
              />
              <span className={styles.voiceName}>
                {t("currentVoiceBinding")}
              </span>
            </label>
          </li>
        ) : null}
      </>
    ) : null;

  const list =
    profiles.length > 0 || pickerRows ? (
      <ul
        className={styles.voiceList}
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
          // No status pill: the row stays one line. A voice that is not ready
          // explains itself in a tooltip instead.
          const statusHint =
            profile.status === "ready"
              ? undefined
              : statusLabel(profile.status);
          return (
            <li
              className={styles.voiceRow}
              key={profile.id}
              data-status={profile.status}
              title={statusHint}
            >
              {editing ? (
                <input
                  className={styles.nameInput}
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
              ) : onSelect ? (
                <label className={styles.voiceChoice}>
                  <input
                    className={styles.radio}
                    type="radio"
                    name={pickerName}
                    checked={selectedId === profile.id}
                    disabled={controlsDisabled || profile.status !== "ready"}
                    onChange={() => onSelect(profile.id)}
                  />
                  <span className={styles.voiceName}>{name}</span>
                </label>
              ) : listenOnly || !manageable ? (
                <span className={styles.voiceName}>{name}</span>
              ) : (
                <button
                  className={styles.voiceName}
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
              )}
              <div className={styles.voiceActions}>
                {manageable || profile.status === "ready" ? (
                  <button
                    className={cards.iconButton}
                    aria-label={t("voicePreview")}
                    data-ui-guide="voice.preview"
                    type="button"
                    disabled={controlsDisabled || !playable}
                    onClick={() => void makePreview(profile.id)}
                  >
                    <IconPlay />
                  </button>
                ) : null}
                {/* Every row keeps its ×, whatever the status: enrolling,
                    failed, refused, outcome unknown or an earlier delete still
                    in progress. The server soft-deletes any of them and cleans
                    up the supplier voice on a best-effort basis. While this
                    row's delete runs, × stays visible as a disabled spinner. */}
                {!listenOnly && manageable ? (
                  <button
                    className={cards.iconButton}
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
                ) : null}
              </div>
              {preview[profile.id] ? (
                <audio
                  className={styles.audio}
                  controls
                  autoPlay
                  preload="auto"
                  src={preview[profile.id].url}
                  onError={() =>
                    invalidatePreview(profile.id, "voicePreviewFailed")
                  }
                />
              ) : null}
            </li>
          );
        })}
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
      {loading ? <LoadingCard /> : null}
      {list}
    </>
  ) : undefined;

  const createAction = listenOnly ? null : creating ? (
    // Top-right, where New was: back to the list, nothing is uploaded.
    <button
      className={cards.iconButton}
      type="button"
      aria-label={t("cancel")}
      title={t("cancel")}
      data-ui-guide="voice.cancelCreate"
      disabled={controlsDisabled}
      onClick={cancelCreate}
    >
      <WorkspaceIcon name="back" />
    </button>
  ) : (
    <ModulePlus
      label={t("voiceCreateTitle")}
      disabled={controlsDisabled || !canEnroll}
      onClick={() => setCreating(true)}
    />
  );

  return (
    <div className={styles.voicePanel} id={id}>
      {embedded || moduleCard ? null : <PageIntro title={t("voices")} />}
      {notice ? (
        <Notice tone="success" onClose={() => setNotice(null)}>
          {t(notice)}
        </Notice>
      ) : null}
      {embedded && !moduleCard ? (
        // Match Agent Avatar / AGENT.md and Team SectionCard title metrics.
        <SectionCard title={t("voices")} action={createAction}>
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
