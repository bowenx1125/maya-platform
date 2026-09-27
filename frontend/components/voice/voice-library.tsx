"use client";

import { useCallback, useEffect, useState } from "react";

import { type VoiceProfile } from "../../lib/api";
import { useIdempotencyStore } from "../../lib/idempotency";
import type { MessageKey } from "../../lib/i18n";
import { useLocale, useT } from "../locale";
import { useSession } from "../session-provider";
import { WorkspaceAction } from "../workspace-actions";
import {
  EmptyCard,
  ErrorNotice,
  LoadingCard,
  PageIntro,
  SectionCard,
  StatusBadge,
} from "../ui";
import styles from "./voice-library.module.css";

const CONSENT_COPY_VERSION = "voice-consent-v1";

type PreviewState = {
  url: string;
  expiresAt: string;
};

export function VoiceLibrary({ groupId }: { groupId: string }) {
  const t = useT();
  const { locale } = useLocale();
  const { api } = useSession();
  const [profiles, setProfiles] = useState<VoiceProfile[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [sampleLanguage, setSampleLanguage] = useState<"en" | "zh-CN">(
    locale === "zh" ? "zh-CN" : "en",
  );
  const [creating, setCreating] = useState(false);
  const [consent, setConsent] = useState(false);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<MessageKey | null>(null);
  const [preview, setPreview] = useState<Record<string, PreviewState>>({});
  const idempotency = useIdempotencyStore();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setProfiles(await api.voiceProfiles(groupId));
    } catch (cause) {
      setError(cause);
    } finally {
      setLoading(false);
    }
  }, [api, groupId]);

  useEffect(() => {
    const timer = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  async function submitEnrollment() {
    if (!file || !consent) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await api.enrollVoice(groupId, file, CONSENT_COPY_VERSION, {
        idempotency: idempotency.handleFor("voice-enroll"),
        language: sampleLanguage,
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

  if (loading) {
    return (
      <>
        <WorkspaceAction name="new" disabled />
        <LoadingCard />
      </>
    );
  }
  if (error && profiles.length === 0) {
    return (
      <>
        <WorkspaceAction name="new" disabled />
        <ErrorNotice error={error} onRetry={() => void load()} />
      </>
    );
  }

  return (
    <div className={styles.voicePanel}>
      <PageIntro title={t("voices")} />
      <WorkspaceAction
        name="new"
        disabled={busy || creating}
        onClick={() => setCreating(true)}
      />
      {error ? (
        <ErrorNotice error={error} onRetry={() => setError(null)} />
      ) : null}
      {notice ? (
        <div className="notice notice-success" role="status">
          {t(notice)}
        </div>
      ) : null}
      {creating ? (
        <SectionCard>
          <WorkspaceAction
            name="back"
            disabled={busy}
            onClick={() => {
              setCreating(false);
              setFile(null);
              setConsent(false);
            }}
          />
          <WorkspaceAction
            name="done"
            disabled={!file || !consent || busy}
            onClick={() => void submitEnrollment()}
          />
          <div className={styles.uploadCard}>
            <input
              className={styles.fileInput}
              type="file"
              accept=".wav,.mp3,.m4a,audio/wav,audio/mpeg,audio/mp4"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              aria-label={t("voiceSampleFile")}
            />
            {file ? <p className={styles.hint}>{file.name}</p> : null}
            <label>
              <span>{t("voiceSampleLanguage")}</span>
              <select
                aria-label={t("voiceSampleLanguage")}
                value={sampleLanguage}
                onChange={(event) =>
                  setSampleLanguage(
                    event.target.value === "zh-CN" ? "zh-CN" : "en",
                  )
                }
              >
                <option value="en">{t("voiceLanguageEn")}</option>
                <option value="zh-CN">{t("voiceLanguageZh")}</option>
              </select>
            </label>
            <label className={styles.consent} data-ui-guide="voice.consent">
              <input
                type="checkbox"
                aria-label={t("voiceConsent")}
                checked={consent}
                onChange={(event) => setConsent(event.target.checked)}
              />
              <span>{t("voiceConsentLabel")}</span>
            </label>
          </div>
        </SectionCard>
      ) : null}
      <SectionCard title={t("voiceGroupTitle")}>
        {profiles.length === 0 ? (
          <EmptyCard title={t("voiceNoCustom")} />
        ) : (
          <div className={styles.profileList}>
            {profiles.map((profile) => (
              <article className={styles.profile} key={profile.id}>
                <div className={styles.profileHeader}>
                  <span className={styles.profileName}>
                    {profile.source_filename ?? t("voiceCustom")}
                  </span>
                  <StatusBadge status={profile.status} />
                </div>
                <p className={styles.profileId}>
                  {t("voiceProfileIdLabel")}: <code>{profile.id}</code>
                </p>
                {preview[profile.id] ? (
                  <audio
                    className={styles.audio}
                    controls
                    preload="none"
                    src={preview[profile.id].url}
                  />
                ) : null}
                <div className={styles.actions}>
                  {profile.status === "preview_ready" ||
                  profile.status === "ready" ? (
                    <button
                      className="secondary-action"
                      type="button"
                      disabled={busy}
                      onClick={() => void makePreview(profile.id)}
                    >
                      {t("voicePreview")}
                    </button>
                  ) : null}
                  {profile.status === "preview_ready" ? (
                    <button
                      className="primary-action"
                      type="button"
                      disabled={busy || !preview[profile.id]}
                      onClick={() => void confirm(profile.id)}
                    >
                      {t("voiceConfirm")}
                    </button>
                  ) : null}
                  {profile.status !== "deleted" ? (
                    <button
                      className="text-link"
                      type="button"
                      disabled={busy}
                      onClick={() => void remove(profile.id)}
                    >
                      {t("voiceDelete")}
                    </button>
                  ) : null}
                </div>
              </article>
            ))}
          </div>
        )}
      </SectionCard>
    </div>
  );
}
