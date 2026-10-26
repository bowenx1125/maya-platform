"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import Link from "next/link";

import {
  PlatformApiError,
  type LiveSnapshot,
  type PlatformApi,
} from "../lib/api";
import type { AvatarState } from "./avatar";
import { useT } from "../lib/i18n";
import { ReportMarkdown } from "./report/report-markdown";
import { useSession } from "./session-provider";
import { ScholarScene } from "./stage3d/scholar-scene";
import type { StageCharacter } from "./stage3d/scholar-stage";
import { ErrorNotice, PageIntro } from "./ui";
import styles from "./classroom-live.module.css";

/** Speaker tones, by participant order (Arcade category colours + main). */
const SPEAKER_TONES = ["#FF4D8D", "#67E8F9", "#A3E635", "#FDBA74"];

/** A row of cabinet marquee LEDs; decoration only. */
function Leds({ count, className }: { count: number; className: string }) {
  return (
    <div className={className} aria-hidden="true">
      {Array.from({ length: count }, (_, index) => (
        <i key={index} />
      ))}
    </div>
  );
}

export function ClassroomLive() {
  const { api, user } = useSession();
  const courseId = user?.courses[0]?.course_id;
  return (
    <ClassroomLiveSession
      key={`${user?.id ?? ""}:${courseId ?? ""}`}
      api={api}
      courseId={courseId}
    />
  );
}

function ClassroomLiveSession({
  api,
  courseId,
}: {
  api: PlatformApi;
  courseId?: string;
}) {
  const t = useT();
  const [snapshot, setSnapshot] = useState<LiveSnapshot | null>(null);
  const [loading, setLoading] = useState(Boolean(courseId));
  const [error, setError] = useState<unknown>(null);
  const [audioBlocked, setAudioBlocked] = useState(false);
  const [audible, setAudible] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let active = true;
    let socket: WebSocket | undefined;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let checking = false;
    let denied = false;
    let debateId: string | undefined;
    let sequence = -1;
    const audio = audioRef.current;
    const closeSocket = () => {
      const previous = socket;
      socket = undefined;
      if (!previous) return;
      previous.onmessage = null;
      previous.onclose = null;
      previous.close();
    };
    const receive = (next: LiveSnapshot, expectedId: string) => {
      if (!active || denied || debateId !== expectedId) return;
      if (
        next.debate_id !== expectedId ||
        !Number.isSafeInteger(next.sequence) ||
        next.sequence < 0 ||
        !Array.isArray(next.turns) ||
        !Array.isArray(next.participants)
      )
        throw new Error("Invalid Live snapshot");
      if (next.sequence < sequence) return;
      sequence = next.sequence;
      const current = next.turns.find(
        (turn) => turn.id === next.playback?.current_turn_id,
      );
      if (!next.active || !current?.audio_url) setAudioBlocked(false);
      setSnapshot(next);
      setError(null);
      if (!next.active) closeSocket();
    };
    const schedule = () => {
      clearTimeout(timer);
      if (active && !denied) timer = setTimeout(() => void check(), 5000);
    };
    const denyAccess = (cause: PlatformApiError) => {
      denied = true;
      clearTimeout(timer);
      closeSocket();
      audio?.pause();
      audio?.removeAttribute("src");
      setSnapshot(null);
      setAudioBlocked(false);
      setAudible(false);
      setLoading(false);
      setError(cause);
    };
    const check = async () => {
      if (!active || denied || !courseId || checking) return;
      checking = true;
      clearTimeout(timer);
      try {
        const live = await api.classroomLive(courseId);
        if (!active || denied) return;
        const nextId = live?.debate_id;
        if (nextId !== debateId) {
          closeSocket();
          debateId = nextId;
          sequence = -1;
          setSnapshot(null);
          setAudioBlocked(false);
          setAudible(false);
          audio?.pause();
          audio?.removeAttribute("src");
        }
        setError(null);
        if (!nextId || socket) return;
        const next = await api.liveSnapshot(nextId);
        if (!active || denied || debateId !== nextId) return;
        receive(next, nextId);
        if (!next.active) return;
        const url = new URL(
          `/api/v1/live/${nextId}/events`,
          window.location.href,
        );
        url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
        const connection = new WebSocket(url.href);
        socket = connection;
        connection.onmessage = (event) => {
          if (!active || socket !== connection) return;
          try {
            receive(JSON.parse(event.data) as LiveSnapshot, nextId);
          } catch (cause) {
            setError(cause);
            closeSocket();
            audio?.pause();
            schedule();
          }
        };
        connection.onclose = (event) => {
          if (!active || socket !== connection) return;
          if (event.code === 4401 || event.code === 4403) {
            denyAccess(
              new PlatformApiError(event.code - 4000, "Live access denied."),
            );
            return;
          }
          closeSocket();
          audio?.pause();
          if (event.code !== 1000)
            setError(new Error("Live disconnected. Reopen Live to connect."));
          schedule();
        };
      } catch (cause) {
        if (!active || denied) return;
        if (
          cause instanceof PlatformApiError &&
          (cause.status === 401 || cause.status === 403)
        ) {
          denyAccess(cause);
        } else setError(cause);
      } finally {
        checking = false;
        if (active) setLoading(false);
        schedule();
      }
    };
    const refresh = () => {
      if (document.visibilityState === "visible") void check();
    };

    void check();
    window.addEventListener("online", refresh);
    window.addEventListener("focus", refresh);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      active = false;
      clearTimeout(timer);
      window.removeEventListener("online", refresh);
      window.removeEventListener("focus", refresh);
      document.removeEventListener("visibilitychange", refresh);
      closeSocket();
      audio?.pause();
    };
  }, [api, courseId]);

  const current = snapshot?.turns.find(
    (turn) => turn.id === snapshot.playback?.current_turn_id,
  );
  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;
    const playback = snapshot?.playback;
    // Only a platform-relative URL from the authenticated projection is playable.
    const expected = current
      ? `/api/v1/live/${snapshot?.debate_id}/audio/${current.id}`
      : null;
    if (
      !snapshot?.active ||
      !playback ||
      !current?.audio_url ||
      current.audio_url !== expected
    ) {
      audio.pause();
      audio.removeAttribute("src");
      return;
    }
    if (audio.getAttribute("src") !== current.audio_url)
      audio.src = current.audio_url;
    audio.playbackRate = 1;
    const seek = () => {
      const target = playback.cursor_ms / 1000;
      if (Math.abs(audio.currentTime - target) > 0.8)
        audio.currentTime = target;
    };
    if (audio.readyState > 0) seek();
    else audio.addEventListener("loadedmetadata", seek, { once: true });
    let active = true;
    if (playback.status === "playing") {
      void audio
        .play()
        .then(() => {
          if (active) setAudioBlocked(false);
        })
        .catch(() => {
          if (active) setAudioBlocked(true);
        });
    } else audio.pause();
    return () => {
      active = false;
      audio.removeEventListener("loadedmetadata", seek);
    };
  }, [snapshot, current]);

  useEffect(() => {
    const transcript = transcriptRef.current;
    transcript?.scrollTo?.({ top: transcript.scrollHeight });
  }, [snapshot?.turns.length]);

  // Keep the lit (current) turn in view when it is not the latest one.
  const currentId = current?.id;
  useEffect(() => {
    const transcript = transcriptRef.current;
    const turn = transcript?.querySelector<HTMLElement>(
      ':scope > article[aria-current="true"]',
    );
    if (!transcript || !turn) return;
    const top = turn.offsetTop - 8;
    const bottom = turn.offsetTop + turn.offsetHeight;
    if (
      top < transcript.scrollTop ||
      bottom > transcript.scrollTop + transcript.clientHeight
    )
      transcript.scrollTo?.({ top });
  }, [currentId, snapshot?.turns.length]);

  const characters: StageCharacter[] = (snapshot?.participants ?? []).map(
    (participant, index) => ({
      id: participant.id,
      name: participant.name,
      config: participant.avatar_config,
      slot: (["A", "B", "C", "D", "E"] as const)[index],
    }),
  );
  const visuals: Record<string, AvatarState> = Object.fromEntries(
    characters.map((character) => [
      character.id,
      audible && current?.participant_id === character.id ? "speaking" : "idle",
    ]),
  );

  return (
    <div className={styles.root}>
      <PageIntro title="Live" />
      {error ? <ErrorNotice error={error} /> : null}
      {loading ? (
        <section
          className={`${styles.cabinet} ${styles.loading}`}
          role="status"
        >
          <Leds count={12} className={styles.leds} />
          <div className={styles.screen}>
            <div className={styles.scan} aria-hidden="true" />
            <div className={styles.loadingBody}>
              {/* The sign-in's four scholar blocks, still waiting their turn. */}
              <span className={styles.blocks} aria-hidden="true">
                <i />
                <i />
                <i />
                <i />
              </span>
              <b>{t("loading")}</b>
            </div>
          </div>
          <div className={styles.knobs} aria-hidden="true">
            <i />
            <i />
            <i />
          </div>
        </section>
      ) : !snapshot?.active ? (
        <section className={styles.offline}>
          {/* The cabinet sleeps: marquee off, eyes closed, cord unplugged. */}
          <div className={styles.cabinet}>
            <Leds count={12} className={`${styles.leds} ${styles.ledsOff}`} />
            <div className={styles.screen}>
              <div className={styles.scan} aria-hidden="true" />
              <div className={styles.decor} aria-hidden="true">
                <span className={styles.eye} />
                <span className={styles.eye} />
                <span className={styles.crt} />
                <i className={styles.bubble} />
                <i className={styles.bubble} />
                <i className={styles.bubble} />
              </div>
            </div>
            <div className={styles.knobs} aria-hidden="true">
              <i />
              <i />
              <i />
            </div>
            <span className={styles.plug} aria-hidden="true" />
          </div>
          <div className={styles.sign}>
            <h2>Live offline</h2>
          </div>
        </section>
      ) : (
        <div className={styles.layout}>
          <div className={styles.scene}>
            <Leds count={14} className={styles.marquee} />
            <ScholarScene
              layout="preview"
              characters={characters}
              visuals={visuals}
              resting={!current}
              speakingId={current?.participant_id}
              bubbleText={current?.speech}
              loadingLabel={t("loading")}
              unavailableLabel="3D unavailable"
            />
          </div>
          <div className={styles.interactionActions}>
            {snapshot.interaction_url?.startsWith("/classroom/") ? (
              <Link className="primary-action" href={snapshot.interaction_url}>
                Interact
              </Link>
            ) : (
              <>
                <button
                  className="primary-action"
                  type="button"
                  disabled
                  aria-describedby="live-interaction-unavailable"
                >
                  Interact
                </button>
                <p
                  className={styles.interactionHint}
                  id="live-interaction-unavailable"
                  role="status"
                >
                  {t("liveInteractionUnavailable")}
                </p>
              </>
            )}
          </div>
          <section className={styles.transcript}>
            <header>
              <h2>{t("debateTranscript")}</h2>
              {audioBlocked &&
              current &&
              current.audio_url ===
                `/api/v1/live/${snapshot.debate_id}/audio/${current.id}` ? (
                <button
                  className="secondary-action"
                  onClick={() => {
                    void audioRef.current
                      ?.play()
                      .then(() => setAudioBlocked(false))
                      .catch(() => setAudioBlocked(true));
                  }}
                >
                  Play audio
                </button>
              ) : null}
            </header>
            <div
              ref={transcriptRef}
              className={styles.log}
              role="log"
              aria-live="polite"
              aria-relevant="additions"
            >
              {snapshot.turns.map((turn, index) => {
                const speaker = snapshot.participants.findIndex(
                  (person) => person.id === turn.participant_id,
                );
                const tone = {
                  "--speaker": SPEAKER_TONES[Math.max(speaker, 0) % 4],
                  "--meter": `${Math.max(90 - index * 17, 10)}%`,
                } as CSSProperties;
                return (
                  <article
                    key={turn.id}
                    className={styles.turn}
                    style={tone}
                    aria-current={turn.id === current?.id ? "true" : undefined}
                  >
                    <span className={styles.portrait} aria-hidden="true" />
                    <strong>{snapshot.participants[speaker]?.name}</strong>
                    <span className={styles.meter} aria-hidden="true" />
                    <ReportMarkdown>{turn.speech}</ReportMarkdown>
                  </article>
                );
              })}
            </div>
          </section>
        </div>
      )}
      <audio
        ref={audioRef}
        onPlaying={() => setAudible(true)}
        onPause={() => setAudible(false)}
        onEnded={() => setAudible(false)}
        onError={() => {
          setAudible(false);
          setAudioBlocked(true);
        }}
      />
    </div>
  );
}
