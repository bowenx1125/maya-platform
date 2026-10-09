"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import { PlatformApiError, type Group, type VoiceProfile } from "../../lib/api";
import { useIdempotencyStore } from "../../lib/idempotency";
import type { MessageKey } from "../../lib/i18n";
import { useT } from "../locale";
import { PageAction } from "../page-action";
import { WorkspaceIcon } from "../workspace-icon";
import { useSession } from "../session-provider";
import {
  EmptyCard,
  ErrorNotice,
  LoadingCard,
  PageIntro,
  SectionCard,
  StatusBadge,
} from "../ui";
import { IconCheck, IconClose, IconPlay } from "../quiet-icons";
import cards from "../library-cards.module.css";
import styles from "./voice-library.module.css";

const CONSENT_COPY_VERSION = "voice-consent-v1";

type PreviewState = {
  url: string;
  expiresAt: string;
};

export function VoiceLibrary({
  groupId,
  groupOptions,
  onGroupChange,
  embedded = false,
  initialCreate = false,
}: {
  groupId: string | null;
  groupOptions?: Pick<Group, "id" | "name">[];
  onGroupChange?: (groupId: string) => void;
  embedded?: boolean;
  initialCreate?: boolean;
}) {
  const t = useT();
  const { api } = useSession();
  const [profiles, setProfiles] = useState<VoiceProfile[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [creating, setCreating] = useState(initialCreate && Boolean(groupId));
  const [consent, setConsent] = useState(false);
  const [loading, setLoading] = useState(Boolean(groupId));
  const [checkedGroupId, setCheckedGroupId] = useState<string | null>(null);
  const [unavailableGroupId, setUnavailableGroupId] = useState<string | null>(
    null,
  );
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
    if (!groupId) {
      setProfiles([]);
      setLoading(false);
      setError(null);
      setCheckedGroupId(null);
      setUnavailableGroupId(null);
      return;
    }
    const sequence = ++loadSequence.current;
    setLoading(true);
    setError(null);
    try {
      const nextProfiles = await api.voiceProfiles(groupId);
      if (sequence === loadSequence.current) {
        setProfiles(nextProfiles);
        setCheckedGroupId(groupId);
        setUnavailableGroupId(null);
      }
    } catch (cause) {
      if (sequence === loadSequence.current) {
        setError(cause);
        setCheckedGroupId(groupId);
        setUnavailableGroupId(
          cause instanceof PlatformApiError &&
            (cause.status === 403 || cause.status === 404)
            ? groupId
            : null,
        );
      }
    } finally {
      if (sequence === loadSequence.current) setLoading(false);
    }
  }, [api, groupId]);

  useEffect(() => {
    if (!groupId) {
      loadSequence.current += 1;
      return;
    }
    const timer = window.setTimeout(() => void load(), 0);
    return () => {
      window.clearTimeout(timer);
      loadSequence.current += 1;
    };
  }, [groupId, load]);

  async function submitEnrollment() {
    if (!groupScopeReady || !groupId || !file || !consent) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.enrollVoice(groupId, file, CONSENT_COPY_VERSION, {
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

  async function saveName(profile: VoiceProfile, restoreFocus = false) {
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
        current.map((item) => (item.id === profile.id ? renamed : item)),
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

  if (loading && groupOptions === undefined) {
    return <LoadingCard />;
  }
  if (error && profiles.length === 0 && groupOptions === undefined) {
    return <ErrorNotice error={error} onRetry={() => void load()} />;
  }

  const groupPicker =
    groupOptions === undefined ? null : groupOptions.length ? (
      <label className={styles.field}>
        <span>{t("group")}</span>
        <select
          value={groupId ?? ""}
          disabled={busy || creating || editingName !== null}
          onChange={(event) => onGroupChange?.(event.target.value)}
        >
          <option value="">{t("selectGroup")}</option>
          {groupOptions.map((group) => (
            <option key={group.id} value={group.id}>
              {group.name}
            </option>
          ))}
        </select>
      </label>
    ) : (
      <EmptyCard title={t("rosterNoGroups")} />
    );

  const groupScopeReady = Boolean(
    groupId &&
    !loading &&
    checkedGroupId === groupId &&
    unavailableGroupId !== groupId,
  );

  const newVoice = (
    <button
      className="inline-button symbol-button"
      type="button"
      aria-label={t("voiceCreateTitle")}
      disabled={busy || creating || !groupScopeReady}
      onClick={() => setCreating(true)}
    >
      <WorkspaceIcon name="new" />
    </button>
  );

  return (
    <div className={styles.voicePanel}>
      {embedded ? null : <PageIntro title={t("voices")} />}
      {error &&
      (creating || groupOptions === undefined || profiles.length > 0) ? (
        <ErrorNotice error={error} onRetry={() => setError(null)} />
      ) : null}
      {notice ? (
        <div className="notice notice-success" role="status">
          {t(notice)}
        </div>
      ) : null}
      {creating ? (
        <SectionCard className={styles.uploadCard}>
          {groupPicker}
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
            disabled={!file || !consent || busy || !groupScopeReady}
            onClick={() => void submitEnrollment()}
          />
        </SectionCard>
      ) : (
        <SectionCard
          title={`${t("voices")} · ${profiles.length}`}
          action={newVoice}
        >
          {groupPicker}
          {loading ? <LoadingCard /> : null}
          {error && profiles.length === 0 && groupOptions !== undefined ? (
            <ErrorNotice error={error} onRetry={() => void load()} />
          ) : null}
          {groupScopeReady && !error && profiles.length === 0 ? (
            <EmptyCard title={t("voiceNone")} />
          ) : null}
          {!loading && groupId ? (
            <div className={`knowledge-tile-grid ${cards.grid}`}>
              {profiles.map((profile) => (
                <article
                  className={`knowledge-tile ${cards.tile}`}
                  key={profile.id}
                >
                  <span className="document-main">
                    {editingName?.id === profile.id ? (
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
                    ) : (
                      <button
                        className={styles.nameButton}
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
                        {profile.source_filename ?? t("voiceCustom")}
                      </button>
                    )}
                  </span>
                  <div className={`icon-action-row ${cards.actions}`}>
                    {profile.status === "preview_ready" ||
                    profile.status === "ready" ? (
                      <button
                        className="icon-action"
                        aria-label={t("voicePreview")}
                        data-ui-guide="voice.preview"
                        type="button"
                        disabled={busy}
                        onClick={() => void makePreview(profile.id)}
                      >
                        <IconPlay />
                      </button>
                    ) : null}
                    {profile.status === "preview_ready" ? (
                      <button
                        className="icon-action"
                        aria-label={t("voiceConfirm")}
                        data-ui-guide="voice.confirm"
                        type="button"
                        disabled={busy || !preview[profile.id]}
                        onClick={() => void confirm(profile.id)}
                      >
                        <IconCheck />
                      </button>
                    ) : null}
                    {profile.status !== "deleted" ? (
                      <button
                        className="icon-action icon-action-danger"
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
                  {profile.status !== "ready" ? (
                    <div className={cards.status}>
                      <StatusBadge status={profile.status} />
                    </div>
                  ) : null}
                  {preview[profile.id] ? (
                    <audio
                      className={styles.audio}
                      controls
                      preload="none"
                      src={preview[profile.id].url}
                    />
                  ) : null}
                </article>
              ))}
            </div>
          ) : null}
        </SectionCard>
      )}
    </div>
  );
}
