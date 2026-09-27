"use client";

import { useEffect, useRef, useState } from "react";
import Link from "next/link";

import type { LiveSnapshot } from "../lib/api";
import type { AvatarState } from "./avatar";
import { useT } from "./locale";
import { ReportMarkdown } from "./report/report-markdown";
import { useSession } from "./session-provider";
import { ScholarScene } from "./stage3d/scholar-scene";
import type { StageCharacter } from "./stage3d/scholar-stage";
import { EmptyCard, ErrorNotice, LoadingCard, PageIntro } from "./ui";
import styles from "./classroom-live.module.css";

export function ClassroomLive() {
  const { api, user } = useSession();
  const t = useT();
  const courseId = user?.courses[0]?.course_id;
  const [snapshot, setSnapshot] = useState<LiveSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [audioBlocked, setAudioBlocked] = useState(false);
  const [audible, setAudible] = useState(false);
  const audioRef = useRef<HTMLAudioElement>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!courseId) return;
    let active = true;
    let socket: WebSocket | undefined;
    let sequence = -1;
    const audio = audioRef.current;
    const receive = (next: LiveSnapshot) => {
      if (!active || next.sequence < sequence) return;
      sequence = next.sequence;
      setSnapshot(next);
    };
    void api
      .classroomLive(courseId)
      .then(async (live) => {
        if (!live || !active) return;
        receive(await api.liveSnapshot(live.debate_id));
        if (!active) return;
        const url = new URL(
          `/api/v1/live/${live.debate_id}/events`,
          window.location.href,
        );
        url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
        socket = new WebSocket(url.href);
        socket.onmessage = (event) => {
          try {
            const next = JSON.parse(event.data) as LiveSnapshot;
            if (
              next.debate_id !== live.debate_id ||
              !Array.isArray(next.turns) ||
              !Array.isArray(next.participants)
            )
              throw new Error("Invalid Live snapshot");
            receive(next);
          } catch {
            socket?.close();
          }
        };
        socket.onclose = (event) => {
          if (!active) return;
          audioRef.current?.pause();
          if (event.code !== 1000)
            setError(new Error("Live disconnected. Reopen Live to connect."));
        };
      })
      .catch((cause) => {
        if (active) setError(cause);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
      socket?.close();
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
    audio.playbackRate = playback.playback_rate;
    const seek = () => {
      const target = playback.cursor_ms / 1000;
      if (Math.abs(audio.currentTime - target) > 0.8)
        audio.currentTime = target;
    };
    if (audio.readyState > 0) seek();
    else audio.addEventListener("loadedmetadata", seek, { once: true });
    if (playback.status === "playing") {
      void audio
        .play()
        .then(() => setAudioBlocked(false))
        .catch(() => setAudioBlocked(true));
    } else audio.pause();
    return () => audio.removeEventListener("loadedmetadata", seek);
  }, [snapshot, current]);

  useEffect(() => {
    const transcript = transcriptRef.current;
    transcript?.scrollTo?.({ top: transcript.scrollHeight });
  }, [snapshot?.turns.length]);

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
    <>
      <PageIntro title="Live" />
      {error ? <ErrorNotice error={error} /> : null}
      {loading ? (
        <LoadingCard />
      ) : !snapshot?.active ? (
        <EmptyCard title="Live offline" />
      ) : (
        <div className={styles.layout}>
          <div className={styles.scene}>
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
              <button className="primary-action" type="button" disabled>
                Interact
              </button>
            )}
          </div>
          <section className={styles.transcript}>
            <header>
              <h2>{t("debateTranscript")}</h2>
              {audioBlocked ? (
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
              role="log"
              aria-live="polite"
              aria-relevant="additions"
            >
              {snapshot.turns.map((turn) => (
                <article
                  key={turn.id}
                  aria-current={turn.id === current?.id ? "true" : undefined}
                >
                  <strong>
                    {
                      snapshot.participants.find(
                        (person) => person.id === turn.participant_id,
                      )?.name
                    }
                  </strong>
                  <ReportMarkdown>{turn.speech}</ReportMarkdown>
                </article>
              ))}
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
    </>
  );
}
