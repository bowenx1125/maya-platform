"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { PlatformApiError, type VoiceProfile } from "../../lib/api";
import { useIdempotencyStore } from "../../lib/idempotency";
import type { MessageKey } from "../../lib/i18n";
import { useT } from "../locale";
import { PageAction } from "../page-action";
import { useSession } from "../session-provider";
import { ErrorNotice, LoadingCard, PageIntro, StatusBadge } from "../ui";
import { IconCheck, IconClose, IconPlay } from "../quiet-icons";
import { ModuleCard, ModuleList, ModulePlus } from "../studyform-layout";
import cards from "../knowledge/brainform-workspace.module.css";
import styles from "./voice-library.module.css";

const CONSENT_COPY_VERSION = "voice-consent-v1";

type PreviewState = {
  url: string;
  expiresAt: string;
};

type ScopeStatus = "loading" | "ready" | "denied" | "error";

type ListedVoice = VoiceProfile;

export function VoiceLibrary({
  groupId,
  membershipGroupIds = [],
  listenOnly = false,
  embedded = false,
  initialCreate = false,
  id,
}: {
  groupId: string | null;
  /** Groups this person belongs to. Never a course-wide picker. */
  membershipGroupIds?: string[];
  /** Accounts opens a group so a teacher can play its voices. */
  listenOnly?: boolean;
  embedded?: boolean;
  initialCreate?: boolean;
  id?: string;
}) {
  const t = useT();
  const { api } = useSession();
  const membershipKey = membershipGroupIds.join("|");
  const scopes = useMemo<string[]>(
    () => (groupId ? [groupId] : membershipKey ? membershipKey.split("|") : []),
    [groupId, membershipKey],
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
  const [error, setError] = useState<unknown>(null);
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

  const load = useCallback(async () => {
    const sequence = ++loadSequence.current;
    if (scopes.length === 0) {
      setProfiles([]);
      setScopeStatus({});
      setError(null);
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    const results = await Promise.all(
      scopes.map(async (scopeId) => {
        try {
          return {
            scopeId,
            status: "ready" as const,
            profiles: await api.voiceProfiles(scopeId),
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
    setProfiles(
      results.flatMap((result) =>
        result.status === "denied" ? [] : result.profiles,
      ),
    );
    setScopeStatus(
      Object.fromEntries(
        results.map((result) => [result.scopeId, result.status]),
      ),
    );
    const failure = results.find((result) => result.status === "error");
    const denial = results.find((result) => result.status === "denied");
    const ready = results.some((result) => result.status === "ready");
    // A refused group is not an empty library. Say so when nothing else loaded.
    setError(failure?.cause ?? (!ready && denial ? denial.cause : null));
    setLoading(false);
  }, [api, scopes]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => {
      window.clearTimeout(timer);
      loadSequence.current += 1;
    };
  }, [load]);

  const enrollmentGroupId = listenOnly
    ? null
    : groupId &&
        (scopeStatus[groupId] === "ready" || scopeStatus[groupId] === "error")
      ? groupId
      : scopes.length === 1 &&
          (scopeStatus[scopes[0]] === "ready" ||
            scopeStatus[scopes[0]] === "error")
        ? scopes[0]
        : null;
  const canEnroll = Boolean(enrollmentGroupId) && !loading && !listenOnly;

  async function submitEnrollment() {
    if (!canEnroll || !enrollmentGroupId || !file || !consent) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.enrollVoice(enrollmentGroupId, file, CONSENT_COPY_VERSION, {
        idempotency: idempotency.handleFor("voice-enroll"),
      });
      idempotency.finish("voice-enroll");
      setFile(null);
      setConsent(false);
      setCreating(false);
      setNotice("voiceProfileCreatedNotice");
      await load();
    } catch (cause) {
      setError(cause);
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
    if (activeName.current !== profile.id || !editingName || savingName.current)
      return;
    const value = editingName.value.trim();
    if (value === (profile.source_filename ?? "")) {
      closeNameEditor(profile.id, restoreFocus);
      return;
    }
    savingName.current = true;
    setBusy(true);
    setError(null);
    try {
      const renamed = await api.renameVoiceProfile(profile.id, value);
      setProfiles((current) =>
        current.map((item) =>
          item.id === profile.id ? { ...item, ...renamed } : item,
        ),
      );
      closeNameEditor(profile.id, restoreFocus);
    } catch (cause) {
      setError(cause);
    } finally {
      savingName.current = false;
      setBusy(false);
    }
  }

  async function makePreview(profileId: string) {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const resource = await api.createVoicePreview(profileId);
      setPreview((current) => ({
        ...current,
        [profileId]: {
          url: resource.playback_url,
          expiresAt: resource.expires_at,
        },
      }));
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  async function confirm(profileId: string) {
    setBusy(true);
    setError(null);
    try {
      await api.confirmVoiceProfile(profileId);
      setPreview((current) => {
        const next = { ...current };
        delete next[profileId];
        return next;
      });
      await load();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  async function remove(profileId: string) {
    if (!window.confirm(t("voiceDeleteConfirm"))) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await api.deleteVoiceProfile(profileId, {
        idempotency: idempotency.handleFor(`voice-delete-${profileId}`),
      });
      idempotency.finish(`voice-delete-${profileId}`);
      setPreview((current) => {
        const next = { ...current };
        delete next[profileId];
        return next;
      });
      await load();
    } catch (cause) {
      setError(cause);
    } finally {
      setBusy(false);
    }
  }

  const form = (
    <div className={styles.uploadCard}>
      {error ? <ErrorNotice error={error} onRetry={() => void load()} /> : null}
      <label className={styles.field}>
        <span>{t("voiceSampleLabel")}</span>
        <input
          className={styles.fileInput}
          type="file"
          accept=".wav,.mp3,.m4a,audio/wav,audio/mpeg,audio/mp4"
          data-ui-guide="voice.uploadSample"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
          aria-label={t("voiceSampleFile")}
        />
      </label>
      <label className={styles.consent}>
        <input
          type="checkbox"
          aria-label={t("voiceConsent")}
          checked={consent}
          onChange={(event) => setConsent(event.target.checked)}
        />
        <span>{t("voiceConsent")}</span>
      </label>
      <PageAction
        name="back"
        disabled={busy}
        onClick={() => {
          setCreating(false);
          setFile(null);
          setConsent(false);
        }}
      />
      <PageAction
        name="done"
        disabled={!file || !consent || busy || !canEnroll}
        onClick={() => void submitEnrollment()}
      />
    </div>
  );

  const list =
    profiles.length > 0 ? (
      <ModuleList>
        {profiles.map((profile) => {
          const name = profile.source_filename ?? t("voiceCustom");
          const editing = editingName?.id === profile.id;
          return (
            <li className={cards.row} key={profile.id}>
              <div className={cards.rowCopy}>
                {editing ? (
                  <input
                    className={styles.nameInput}
                    aria-label={t("voiceName")}
                    value={editingName.value}
                    readOnly={busy}
                    ref={focusNameInput}
                    onChange={(event) =>
                      setEditingName({
                        id: profile.id,
                        value: event.target.value,
                      })
                    }
                    onBlur={() => void saveName(profile)}
                    onKeyDown={(event) => {
                      if (event.nativeEvent.isComposing) return;
                      if (event.key === "Enter") {
                        event.preventDefault();
                        void saveName(profile, true);
                      } else if (
                        event.key === "Escape" &&
                        !savingName.current
                      ) {
                        event.preventDefault();
                        closeNameEditor(profile.id, true);
                      }
                    }}
                  />
                ) : listenOnly ? (
                  <span className={cards.staticTitle}>{name}</span>
                ) : (
                  <button
                    className={cards.titleButton}
                    type="button"
                    disabled={busy || profile.status === "deleted"}
                    ref={(button) => {
                      if (button && focusName.current === profile.id) {
                        button.focus();
                        focusName.current = null;
                      }
                    }}
                    onClick={() => {
                      activeName.current = profile.id;
                      setError(null);
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
              </div>
              <div className={cards.actions}>
                {profile.status === "preview_ready" ||
                profile.status === "ready" ? (
                  <button
                    className={cards.iconButton}
                    aria-label={t("voicePreview")}
                    data-ui-guide="voice.preview"
                    type="button"
                    disabled={busy}
                    onClick={() => void makePreview(profile.id)}
                  >
                    <IconPlay />
                  </button>
                ) : null}
                {!listenOnly && profile.status === "preview_ready" ? (
                  <button
                    className={cards.iconButton}
                    aria-label={t("voiceConfirm")}
                    data-ui-guide="voice.confirm"
                    type="button"
                    disabled={busy || !preview[profile.id]}
                    onClick={() => void confirm(profile.id)}
                  >
                    <IconCheck />
                  </button>
                ) : null}
                {!listenOnly && profile.status !== "deleted" ? (
                  <button
                    className={cards.iconButton}
                    aria-label={t("voiceDelete")}
                    data-ui-guide="voice.delete"
                    type="button"
                    disabled={busy}
                    onClick={() => void remove(profile.id)}
                  >
                    <IconClose />
                  </button>
                ) : null}
              </div>
              {preview[profile.id] ? (
                <div className={cards.rowExtra}>
                  <audio
                    className={styles.audio}
                    controls
                    preload="none"
                    src={preview[profile.id].url}
                  />
                </div>
              ) : null}
            </li>
          );
        })}
      </ModuleList>
    ) : null;

  const body = creating ? (
    form
  ) : error || loading || list ? (
    <>
      {error ? <ErrorNotice error={error} onRetry={() => void load()} /> : null}
      {loading ? <LoadingCard /> : null}
      {list}
    </>
  ) : undefined;

  return (
    <div className={styles.voicePanel} id={id}>
      {embedded ? null : <PageIntro title={t("voices")} />}
      {notice ? (
        <div className="notice notice-success" role="status">
          {t(notice)}
        </div>
      ) : null}
      <ModuleCard
        title={t("voices")}
        labelledBy={id ? `${id}-title` : "voices-title"}
        empty={body ? undefined : t("voiceNone")}
        action={
          creating || listenOnly ? null : (
            <ModulePlus
              label={t("voiceCreateTitle")}
              disabled={busy || !canEnroll}
              onClick={() => setCreating(true)}
            />
          )
        }
      >
        {body}
      </ModuleCard>
    </div>
  );
}
