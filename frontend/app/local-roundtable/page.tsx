"use client";

import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type ChangeEvent,
} from "react";

import { AVATAR_TEMPLATE_DEFAULT_CONFIGS } from "../../components/avatar/types";
import { bubbleProgressFrom } from "../../components/debate-beta/stage/bubble-progress";
import { ScholarScene } from "../../components/stage3d/scholar-scene";
import type { StageCharacter } from "../../components/stage3d/scholar-stage";
import {
  parseLocalDebateManifest,
  type LocalDebateManifest,
} from "../../lib/local-roundtable";
import styles from "./roundtable.module.css";

type ReadyDebate = {
  manifest: LocalDebateManifest;
  audioUrls: string[];
};

const slots = ["A", "B", "C", "D", "E"] as const;
const defaultNames = ["老子", "柏拉图"];

export default function LocalRoundtablePage() {
  const pickerRef = useRef<HTMLInputElement>(null);
  const audioRef = useRef<HTMLAudioElement>(null);
  const urlsRef = useRef<string[]>([]);
  const [debate, setDebate] = useState<ReadyDebate | null>(null);
  const [index, setIndex] = useState(-1);
  const [elapsed, setElapsed] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [message, setMessage] = useState("选择本地生成目录，开始语音演示");

  useEffect(() => {
    pickerRef.current?.setAttribute("webkitdirectory", "");
    return () => urlsRef.current.forEach(URL.revokeObjectURL);
  }, []);

  const playTurn = useCallback(
    async (nextIndex: number) => {
      const audio = audioRef.current;
      if (!audio || !debate || nextIndex >= debate.manifest.turns.length) {
        setPlaying(false);
        setMessage("演示完成");
        return;
      }
      audio.pause();
      audio.src = debate.audioUrls[nextIndex];
      audio.currentTime = 0;
      setIndex(nextIndex);
      setElapsed(0);
      try {
        await audio.play();
        setPlaying(true);
        setMessage("");
      } catch {
        setPlaying(false);
        setMessage("音频播放失败，文字仍可查看");
      }
    },
    [debate],
  );

  async function loadDirectory(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files ?? []);
    const manifestFile = files.find((file) => file.name === "manifest.json");
    if (!manifestFile) {
      setMessage("目录中缺少 manifest.json");
      return;
    }
    try {
      const manifest = parseLocalDebateManifest(
        JSON.parse(await manifestFile.text()),
      );
      const audioFiles = manifest.turns.map((turn) => {
        const matches = files.filter((file) => file.name === turn.audio_file);
        if (matches.length !== 1) throw new Error("音频文件缺失或重名");
        return matches[0];
      });
      for (const file of audioFiles) {
        const header = new Uint8Array(await file.slice(0, 12).arrayBuffer());
        if (
          String.fromCharCode(...header.slice(0, 4)) !== "RIFF" ||
          String.fromCharCode(...header.slice(8, 12)) !== "WAVE"
        ) {
          throw new Error("音频文件不是 WAV 格式");
        }
      }
      audioRef.current?.pause();
      urlsRef.current.forEach(URL.revokeObjectURL);
      const audioUrls = audioFiles.map(URL.createObjectURL);
      urlsRef.current = audioUrls;
      setDebate({ manifest, audioUrls });
      setIndex(-1);
      setElapsed(0);
      setPlaying(false);
      setMessage("音频已就绪");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "目录读取失败");
    }
    event.target.value = "";
  }

  const turn = index >= 0 ? debate?.manifest.turns[index] : undefined;
  const progress = turn ? Math.min(1, elapsed / turn.duration_seconds) : 0;
  const characters: StageCharacter[] = (
    debate?.manifest.turns ?? defaultNames.map((character) => ({ character }))
  ).map((entry, position) => ({
    id: `speaker-${position}`,
    slot: slots[position],
    name: entry.character,
    config:
      position % 2 === 0
        ? AVATAR_TEMPLATE_DEFAULT_CONFIGS["maya-warm-scholar"]
        : AVATAR_TEMPLATE_DEFAULT_CONFIGS["maya-civic-observer"],
  }));
  const visuals = Object.fromEntries(
    characters.map((character, position) => [
      character.id,
      playing && index === position ? "speaking" : "idle",
    ]),
  ) as Record<string, "speaking" | "idle">;

  return (
    <main className={styles.page}>
      <ScholarScene
        characters={characters}
        visuals={visuals}
        resting={!playing}
        speakingId={playing ? `speaker-${index}` : null}
        bubbleText={
          turn && playing
            ? bubbleProgressFrom(turn.speech, elapsed, turn.duration_seconds)
            : ""
        }
        loadingLabel="人物加载中"
        unavailableLabel="3D 舞台不可用，语音和文字仍可播放"
      />

      <header className={styles.toolbar}>
        <h1>圆桌语音演示</h1>
        <div className={styles.controls}>
          <input
            aria-label="选择本地语音目录"
            className={styles.hiddenInput}
            onChange={(event) => void loadDirectory(event)}
            ref={pickerRef}
            type="file"
          />
          <button onClick={() => pickerRef.current?.click()} type="button">
            选择目录
          </button>
          <button
            disabled={!debate}
            onClick={() => {
              const audio = audioRef.current;
              if (!audio) return;
              if (playing) {
                audio.pause();
                setPlaying(false);
                setMessage("已暂停");
              } else if (index >= 0 && !audio.ended) {
                void audio
                  .play()
                  .then(() => {
                    setPlaying(true);
                    setMessage("");
                  })
                  .catch(() => setMessage("音频播放失败，文字仍可查看"));
              } else {
                void playTurn(0);
              }
            }}
            type="button"
          >
            {playing
              ? "暂停"
              : message === "演示完成"
                ? "重播"
                : index >= 0
                  ? "继续"
                  : "开始"}
          </button>
          <button
            disabled={
              !debate || index < 0 || index >= debate.manifest.turns.length - 1
            }
            onClick={() => void playTurn(index + 1)}
            type="button"
          >
            下一位
          </button>
        </div>
      </header>

      <section className={styles.transcript} aria-label="辩论文字">
        <div className={styles.transcriptHeading}>
          <h2>{debate?.manifest.topic ?? "发言记录"}</h2>
          <span role="status">{message}</span>
        </div>
        <div className={styles.turns}>
          {debate?.manifest.turns.map((entry, turnIndex) => {
            const visible =
              turnIndex < index ||
              (turnIndex === index && !playing && !!message);
            const speech = visible
              ? entry.speech
              : turnIndex === index
                ? Array.from(entry.speech)
                    .slice(
                      0,
                      Math.ceil(Array.from(entry.speech).length * progress),
                    )
                    .join("")
                : "";
            return (
              <article
                className={styles.turn}
                data-active={turnIndex === index}
                key={entry.audio_file}
              >
                <strong>{entry.character}</strong>
                <p>{speech}</p>
              </article>
            );
          })}
        </div>
      </section>
      <audio
        onEnded={() => void playTurn(index + 1)}
        onError={() => {
          if (index >= 0) {
            setPlaying(false);
            setMessage("音频播放失败，文字仍可查看");
          }
        }}
        onTimeUpdate={(event) => setElapsed(event.currentTarget.currentTime)}
        ref={audioRef}
      />
    </main>
  );
}
