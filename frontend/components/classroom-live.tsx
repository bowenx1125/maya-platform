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
import { ErrorNotice, LoadingCard, PageIntro } from "./ui";
import { cn } from "../lib/utils";

/** Speaker tones, by participant order (Arcade category colours + main). */
const SPEAKER_TONES = ["#FF4D8D", "#67E8F9", "#A3E635", "#FDBA74"];

/*
 * Student Live chrome, ported 1:1 from the approved mockups
 * (proposals/01-student-live-v2 F1 On Air + Loading, v3 T1 transcript, v3 O2
 * Offline). Tailwind only; keyframes live in styles/arcade.css (live-*).
 * The approved mocks replaced the page container's padding (48px 0 80px
 * desktop, 28px 16px 48px phone) with 28px 0 140px / 16px 12px 150px in an
 * 1100px column; the root's margins reproduce that.
 */
const LIVE_ROOT =
  "mx-[max(-72px,calc((100%-1106px)/2))] -mt-5 pb-[60px] font-body text-[#111] max-[600px]:-mx-1 max-[600px]:-mt-3 max-[600px]:max-w-none max-[600px]:pb-[102px] motion-reduce:**:animate-none! motion-reduce:**:before:animate-none! motion-reduce:**:after:animate-none!";
const CABINET =
  "relative rounded-[22px] border-[3px] border-[#111] bg-[#111] px-[14px] pt-[14px] pb-[18px] shadow-[6px_6px_0_#FF4D8D]";
const SCREEN =
  "relative grid h-[min(52vh,460px)] place-items-center overflow-hidden rounded-[12px] border-[3px] border-[#333] bg-[#1d1d1d]";
const SCAN =
  "pointer-events-none absolute inset-0 bg-[repeating-linear-gradient(#ffffff08_0_2px,transparent_2px_5px)]";
const LED_ON =
  "size-3 animate-live-blink rounded-full bg-[#FF4D8D] shadow-[0_0_8px_#FF4D8D] even:bg-[#FFE14D] even:shadow-[0_0_8px_#FFE14D] even:[animation-delay:.6s]";
const EYE =
  "absolute top-[38%] h-[34px] w-[70px] rounded-b-[40px] border-b-8 border-[#67E8F9] drop-shadow-[0_0_6px_#67E8F9]";
const BUBBLE =
  "absolute animate-live-rise rounded-full border-[3px] border-[#9CA3AF] opacity-0";
const PLUG =
  "absolute right-[60px] -bottom-[46px] h-[46px] w-[120px] before:absolute before:top-0 before:left-0 before:h-10 before:w-[70px] before:rounded-bl-[30px] before:border-b-[6px] before:border-l-[6px] before:border-[#111] after:absolute after:-bottom-1 after:left-[62px] after:h-[22px] after:w-[34px] after:-rotate-[14deg] after:rounded-[4px] after:border-[3px] after:border-[#111] after:bg-[#4B5563] after:shadow-[8px_0_0_-4px_#111]";
const SIGN =
  "absolute -top-1.5 left-1/2 z-[5] origin-top animate-live-swing [transform:translateX(-50%)_rotate(-7deg)] before:absolute before:-top-[38px] before:left-1/2 before:-ml-px before:h-10 before:w-0.5 before:origin-bottom before:-rotate-[24deg] before:bg-[#111]";
const SIGN_TITLE =
  "m-0 inline-block rounded-[4px] border-2 border-[#111] bg-white px-[14px] py-1.5 font-display text-[28px] font-extrabold whitespace-nowrap shadow-[4px_4px_0_#111]";
const SCENE =
  "relative h-[min(64vh,660px)] min-h-[300px] overflow-visible rounded-[22px] border-[14px] border-t-[40px] border-[#111] bg-[var(--surface-subtle)] shadow-[6px_6px_0_#FF4D8D] outline-[3px] outline-[#111] [&>:not(:first-child)]:overflow-hidden [&>:not(:first-child)]:rounded-[8px] max-[600px]:h-[48vh]";
const INTERACT =
  "inline-flex min-h-14 min-w-[104px] items-center justify-center rounded-full border-[3px] border-[#111] bg-[#FF4D8D] px-[34px] font-display text-[18px] leading-normal font-extrabold text-[#111] no-underline shadow-[0_6px_0_#111] disabled:bg-[#4B5563] disabled:text-[#E5E7EB] disabled:opacity-100 disabled:shadow-[0_3px_0_#111]";
const INTERACT_HINT =
  "m-0 max-w-[min(100%,42ch)] rounded-[8px] border-2 border-[#111] bg-[#FFF7CC] px-2.5 py-1.5 text-right text-sm leading-[1.4] text-[#111] max-[600px]:self-stretch max-[600px]:text-left";
const TRANSCRIPT =
  "relative rounded-[22px] border-[3px] border-[#111] bg-[#111] px-6 py-5 text-[#F3F4F6] shadow-[6px_6px_0_#FF4D8D] max-[600px]:p-4";
const PLAY_AUDIO =
  "rounded-[10px] border-2 border-white bg-[#1d1d1d] text-white shadow-[3px_3px_0_#FF4D8D]";
const TRANSCRIPT_LOG =
  "relative grid max-h-80 gap-3 overflow-y-auto overscroll-contain pt-1.5 pr-2 pb-3 pl-1 [scrollbar-gutter:stable]";
/** One T1 turn; the last child is ReportMarkdown's root (the speech box). */
const TURN =
  "group/turn grid grid-cols-[64px_1fr] items-start gap-x-[14px] gap-y-0 opacity-50 saturate-[.6] aria-[current=true]:px-[14px] aria-[current=true]:py-2.5 aria-[current=true]:opacity-100 aria-[current=true]:filter-none max-[600px]:grid-cols-[44px_1fr] max-[600px]:gap-x-2.5 " +
  "[&>:last-child]:relative [&>:last-child]:col-start-2 [&>:last-child]:mt-1.5 [&>:last-child]:rounded-[4px] [&>:last-child]:border-2 [&>:last-child]:border-white [&>:last-child]:bg-[#1d1d1d] [&>:last-child]:px-[14px] [&>:last-child]:py-2.5 [&>:last-child]:text-[#F3F4F6] " +
  "aria-[current=true]:[&>:last-child]:border-[#FFE14D] aria-[current=true]:[&>:last-child]:shadow-[4px_4px_0_#FF4D8D] aria-[current=true]:[&>:last-child]:after:absolute aria-[current=true]:[&>:last-child]:after:right-2.5 aria-[current=true]:[&>:last-child]:after:bottom-1.5 aria-[current=true]:[&>:last-child]:after:animate-live-blink-fast aria-[current=true]:[&>:last-child]:after:border-[7px] aria-[current=true]:[&>:last-child]:after:border-transparent aria-[current=true]:[&>:last-child]:after:border-t-[9px] aria-[current=true]:[&>:last-child]:after:border-t-[#FFE14D]";
const PORTRAIT =
  "relative row-span-2 size-16 overflow-hidden rounded-[6px] border-[3px] border-white bg-[var(--speaker)] shadow-[3px_3px_0_#FF4D8D] before:absolute before:top-3 before:left-[14px] before:size-[30px] before:rounded-[4px] before:bg-[#111] before:shadow-[inset_6px_8px_0_-2px_var(--speaker)] after:absolute after:inset-x-2 after:-bottom-1.5 after:h-[22px] after:rounded-t-[10px] after:bg-[#111] group-aria-[current=true]/turn:animate-live-blink group-aria-[current=true]/turn:shadow-[0_0_0_3px_#FFE14D,4px_4px_0_3px_#FF4D8D] max-[600px]:size-11 max-[600px]:before:top-1.5 max-[600px]:before:left-2 max-[600px]:before:h-[22px] max-[600px]:before:w-6";
const NAME_PLATE =
  "justify-self-start bg-[var(--speaker)] py-1 pr-[22px] pl-3 font-display text-[15px] leading-normal font-black tracking-[.06em] text-[#111] uppercase [clip-path:polygon(0_0,100%_0,calc(100%-14px)_100%,0_100%)] group-aria-[current=true]/turn:text-[#FF4D8D]";
const METER =
  "col-start-2 row-start-1 h-3 w-[38%] -skew-x-[14deg] self-center justify-self-end border-2 border-white bg-[linear-gradient(90deg,var(--speaker)_var(--meter),#333_0)] max-[600px]:w-[30%]";

/** A row of cabinet LEDs (or the marquee over the stage); decoration only. */
function Leds({
  count,
  off = false,
  marquee = false,
}: {
  count: number;
  off?: boolean;
  marquee?: boolean;
}) {
  return (
    <div
      className={cn(
        "flex justify-center gap-[10px]",
        marquee
          ? "pointer-events-none absolute inset-x-0 -top-[30px] z-[3]"
          : "mb-3",
        off && "opacity-40",
      )}
      aria-hidden="true"
    >
      {Array.from({ length: count }, (_, index) => (
        <i
          key={index}
          className={off ? "size-3 rounded-full bg-[#3a3a3a]" : LED_ON}
        />
      ))}
    </div>
  );
}

/** The cabinet's three control knobs; decoration only. */
function Knobs({ tones }: { tones: string[] }) {
  return (
    <div className="mt-[14px] flex justify-center gap-4" aria-hidden="true">
      {tones.map((tone, index) => (
        <i
          key={index}
          className={cn(
            "size-[26px] rounded-full border-2 border-black shadow-[inset_-3px_-3px_0_#0005]",
            tone,
          )}
        />
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
    <div className={LIVE_ROOT}>
      <PageIntro title="Live" />
      {error ? <ErrorNotice kind="bell" transient error={error} /> : null}
      {loading ? (
        <section className={cn(CABINET, "mt-2")}>
          <Leds count={12} />
          <div className={SCREEN}>
            <div className={SCAN} aria-hidden="true" />
            {/* The site-wide loading cards, on the cabinet's screen (bare:
                the screen is their frame). */}
            <div className="relative w-[min(720px,100%)]">
              <LoadingCard bare size="sm" />
            </div>
          </div>
          <Knobs tones={["bg-[#FF4D8D]", "bg-[#67E8F9]", "bg-[#A3E635]"]} />
        </section>
      ) : !snapshot?.active ? (
        <section className="relative mx-auto mt-[46px] mb-[70px] max-w-[820px]">
          {/* The cabinet sleeps: marquee off, eyes closed, cord unplugged. */}
          <div
            className={cn(
              CABINET,
              "max-w-full origin-bottom animate-live-breathe shadow-[6px_6px_0_#4B5563]",
            )}
          >
            <Leds count={12} off />
            <div className={cn(SCREEN, "bg-[#151515]")}>
              <div className={SCAN} aria-hidden="true" />
              <div className="absolute inset-0" aria-hidden="true">
                <span className={cn(EYE, "left-[calc(50%-110px)]")} />
                <span className={cn(EYE, "left-[calc(50%+40px)]")} />
                <span className="absolute top-[70%] right-[10%] left-[10%] h-1 animate-live-blink-slow bg-[#67E8F9] opacity-50 shadow-[0_0_14px_3px_#67E8F9]" />
                <i className={cn(BUBBLE, "top-[34%] left-[66%] size-[14px]")} />
                <i
                  className={cn(
                    BUBBLE,
                    "top-[30%] left-[70%] size-5 [animation-delay:1s]",
                  )}
                />
                <i
                  className={cn(
                    BUBBLE,
                    "top-[26%] left-[74%] size-7 [animation-delay:2s]",
                  )}
                />
              </div>
            </div>
            <Knobs tones={["bg-[#4B5563]", "bg-[#4B5563]", "bg-[#4B5563]"]} />
            <span className={PLUG} aria-hidden="true" />
          </div>
          <div className={SIGN}>
            <h2 className={SIGN_TITLE}>Live offline</h2>
          </div>
        </section>
      ) : (
        <div className="grid gap-[18px]">
          <div className={SCENE}>
            <Leds count={14} marquee />
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
          <div className="flex flex-col items-end justify-end gap-2">
            {snapshot.interaction_url?.startsWith("/classroom/") ? (
              <Link
                className={cn("primary-action", INTERACT)}
                href={snapshot.interaction_url}
              >
                Interact
              </Link>
            ) : (
              <>
                <button
                  className={cn("primary-action", INTERACT)}
                  type="button"
                  disabled
                  aria-describedby="live-interaction-unavailable"
                >
                  Interact
                </button>
                <p
                  className={INTERACT_HINT}
                  id="live-interaction-unavailable"
                  role="status"
                >
                  {t("liveInteractionUnavailable")}
                </p>
              </>
            )}
          </div>
          <section className={TRANSCRIPT}>
            <header className="mb-4 flex items-center justify-between gap-4">
              <h2 className="m-0 font-display text-xl font-extrabold text-[#FFE14D]">
                {t("debateTranscript")}
              </h2>
              {audioBlocked &&
              current &&
              current.audio_url ===
                `/api/v1/live/${snapshot.debate_id}/audio/${current.id}` ? (
                <button
                  className={cn("secondary-action", PLAY_AUDIO)}
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
              className={TRANSCRIPT_LOG}
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
                    className={TURN}
                    style={tone}
                    aria-current={turn.id === current?.id ? "true" : undefined}
                  >
                    <span className={PORTRAIT} aria-hidden="true" />
                    <strong className={NAME_PLATE}>
                      {snapshot.participants[speaker]?.name}
                    </strong>
                    <span className={METER} aria-hidden="true" />
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
