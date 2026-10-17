"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { PlatformApiError, type VoiceProfile } from "../../lib/api";
import { useIdempotencyStore } from "../../lib/idempotency";
import type { MessageKey } from "../../lib/i18n";
import { useT } from "../locale";
import { PageAction } from "../page-action";
import { useSession } from "../session-provider";
import {
  ErrorNotice,
  LoadingCard,
  Notice,
  PageIntro,
  SectionCard,
  StatusBadge,
} from "../ui";
import { IconCheck, IconClose, IconPlay, IconUpload } from "../quiet-icons";
import { ModuleCard, ModulePlus, ModuleTiles } from "../studyform-layout";
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
  | { kind: "preview" | "confirm" | "delete"; profileId: string }
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

function voiceAwareCause(cause: unknown): unknown {
  // Only for enroll/preview: supplier outages steer to the platform fallback voice.
  // Do not remap rename/load/confirm — a 5xx there is not "provider unavailable".
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
  initialCreate?: boolean;
  selectedId?: string | null;
  disabled?: boolean;
  onSelect?: (profileId: string) => void;
  onProfilesChange?: (profiles: VoiceProfile[]) => void;
  id?: string;
}) {
  const t = useT();
  const { api } = useSession();
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
  const [profiles, setProfiles] = useState<ListedVoice[]>([]);
  const [scopeStatus, setScopeStatus] = useState<Record<string, ScopeStatus>>(
    {},
  );
  const [file, setFile] = useState<File | null>(null);
  const [creating, setCreating] = useState(initialCreate && !listenOnly);
  const [consent, setConsent] = useState(false);
  const [loading, setLoading] = useState(scopes.length > 0);
  const [busy, setBusy] = useState(false);
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
  const focusNameInput = useCallback((input: HTMLInputElement | null) => {
    input?.focus();
  }, []);

  const load = useCallback(
    async (options?: { quiet?: boolean }) => {
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
              profiles: courseId
                ? await api.personalVoiceProfiles(scopeId)
                : await api.voiceProfiles(scopeId),
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
      // A deleted voice stays on the server for its audit trail only.
      const nextProfiles = results.flatMap((result) =>
        result.status === "denied"
          ? []
          : result.profiles.filter((profile) => profile.status !== "deleted"),
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
    [api, courseId, onProfilesChange, scopes],
  );

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => {
      window.clearTimeout(timer);
      loadSequence.current += 1;
    };
  }, [load]);

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
    if (!canEnroll || !enrollmentGroupId || !upload || !consent) return;
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
      setConsent(false);
      setCreating(false);
      setNotice("voiceProfileCreatedNotice");
      await load();
    } catch (cause) {
      setFailure({
        cause: voiceAwareCause(cause),
        retry: isCloneRefusal(cause) ? null : { kind: "enroll", file: upload },
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

  async function confirm(profileId: string, retry = false) {
    if (controlsDisabled) return;
    setBusy(true);
    setFailure(null);
    try {
      // A lost confirmation response may already have promoted the profile.
      const current = retry ? await api.voiceProfile(profileId) : null;
      if (current?.status !== "ready") {
        if (
          !preview[profileId] ||
          !previewIsCurrent(preview[profileId].expiresAt)
        ) {
          invalidatePreview(profileId, "voicePreviewExpired");
          return;
        }
        await api.confirmVoiceProfile(profileId);
      }
      setPreview((current) => {
        const next = { ...current };
        delete next[profileId];
        return next;
      });
      clearConfirmationFailure(profileId);
      await load();
    } catch (cause) {
      if (
        cause instanceof PlatformApiError &&
        cause.status === 409 &&
        cause.code === "invalid_state"
      ) {
        try {
          const current = await api.voiceProfile(profileId);
          if (current.status === "ready") {
            setPreview((resources) => {
              const next = { ...resources };
              delete next[profileId];
              return next;
            });
            clearConfirmationFailure(profileId);
            await load();
          } else {
            invalidatePreview(profileId, "voicePreviewExpired");
          }
        } catch (lookupFailure) {
          setFailure({
            cause: lookupFailure,
            retry: { kind: "confirm", profileId },
          });
        }
      } else {
        setFailure({ cause, retry: { kind: "confirm", profileId } });
      }
    } finally {
      setBusy(false);
    }
  }

  // Agents bound to a deleted voice speak with the fallback voice, so
  // deleting never blocks a Debate.
  async function remove(profile: ListedVoice) {
    if (controlsDisabled) return;
    if (!window.confirm(t("voiceDeleteConfirm"))) return;
    setBusy(true);
    setFailure(null);
    setNotice(null);
    const handle = `voice-delete:${profile.id}`;
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
      await load();
    } catch (cause) {
      setFailure({ cause, retry: { kind: "delete", profileId: profile.id } });
    } finally {
      setBusy(false);
    }
  }

  function clearConfirmationFailure(profileId: string) {
    setFailure((current) => {
      const retry = current?.retry;
      return retry &&
        (retry.kind === "preview" || retry.kind === "confirm") &&
        retry.profileId === profileId
        ? null
        : current;
    });
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
    else if (action.kind === "confirm") void confirm(action.profileId, true);
    else if (action.kind === "delete") {
      const profile = profiles.find((item) => item.id === action.profileId);
      if (profile) void remove(profile);
    } else if (action.kind === "rename")
      void rename(action.profile, action.name, action.restoreFocus);
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
      <label className={styles.consent}>
        <input
          type="checkbox"
          disabled={controlsDisabled}
          aria-label={t("voiceConsent")}
          checked={consent}
          onChange={(event) => setConsent(event.target.checked)}
        />
        <span>{t("voiceConsent")}</span>
      </label>
      <PageAction
        name="back"
        disabled={controlsDisabled}
        onClick={() => {
          setCreating(false);
          setFailure(null);
          setFile(null);
          setConsent(false);
        }}
      />
      <PageAction
        name="done"
        disabled={!file || !consent || controlsDisabled || !canEnroll}
        onClick={() => void submitEnrollment()}
      />
    </div>
  );

  const list =
    profiles.length > 0 ? (
      <ModuleTiles>
        {profiles.map((profile) => {
          const name = profile.source_filename ?? t("voiceCustom");
          const editing = editingName?.id === profile.id;
          // A groupmate's voice can be chosen, but only its creator renames,
          // previews or confirms it.
          const manageable = profile.can_manage !== false;
          const canPlay =
            manageable &&
            (profile.status === "preview_ready" || profile.status === "ready");
          return (
            <li className="agent-tile" key={profile.id}>
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
                <button
                  className="agent-tile-name"
                  type="button"
                  aria-pressed={selectedId === profile.id}
                  disabled={controlsDisabled || profile.status !== "ready"}
                  onClick={() => onSelect(profile.id)}
                >
                  {name}
                </button>
              ) : listenOnly || !manageable ? (
                <span className="agent-tile-name">{name}</span>
              ) : (
                <button
                  className="agent-tile-name"
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
              {profile.status !== "ready" ? (
                <StatusBadge status={profile.status} />
              ) : null}
              {canPlay ? (
                <button
                  className={cards.iconButton}
                  aria-label={t("voicePreview")}
                  data-ui-guide="voice.preview"
                  type="button"
                  disabled={controlsDisabled}
                  onClick={() => void makePreview(profile.id)}
                >
                  <IconPlay />
                </button>
              ) : null}
              {!listenOnly &&
              manageable &&
              profile.status === "preview_ready" ? (
                <button
                  className={cards.iconButton}
                  aria-label={t("voiceConfirm")}
                  data-ui-guide="voice.confirm"
                  type="button"
                  disabled={controlsDisabled || !preview[profile.id]}
                  onClick={() => void confirm(profile.id)}
                >
                  <IconCheck />
                </button>
              ) : null}
              {!listenOnly && !onSelect && manageable ? (
                <button
                  className={cards.iconButton}
                  aria-label={t("voiceDeleteNamed", { name })}
                  data-ui-guide="voice.delete"
                  type="button"
                  disabled={controlsDisabled}
                  onClick={() => void remove(profile)}
                >
                  <IconClose />
                </button>
              ) : null}
              {preview[profile.id] ? (
                <audio
                  className={styles.audio}
                  controls
                  preload="none"
                  src={preview[profile.id].url}
                  onError={() =>
                    invalidatePreview(profile.id, "voicePreviewFailed")
                  }
                />
              ) : null}
            </li>
          );
        })}
      </ModuleTiles>
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

  const createAction =
    creating || listenOnly ? null : (
      <ModulePlus
        label={t("voiceCreateTitle")}
        disabled={controlsDisabled || !canEnroll}
        onClick={() => setCreating(true)}
      />
    );

  return (
    <div className={styles.voicePanel} id={id}>
      {embedded ? null : <PageIntro title={t("voices")} />}
      {notice ? (
        <Notice tone="success" onClose={() => setNotice(null)}>
          {t(notice)}
        </Notice>
      ) : null}
      {embedded ? (
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
