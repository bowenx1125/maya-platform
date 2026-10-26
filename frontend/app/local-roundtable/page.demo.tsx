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
  const [message, setMessage] = useState("");
  const [showTranscript, setShowTranscript] = useState(false);

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
    <main className="relative h-dvh overflow-hidden bg-white [font-family:PingFang_SC,Microsoft_YaHei,Noto_Sans_CJK_SC,system-ui,sans-serif]">
      <ScholarScene
        characters={characters}
        layout="preview"
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

      <header className="absolute top-3 right-3 z-10 max-w-[calc(100%-24px)] max-[700px]:top-2 max-[700px]:right-2 max-[700px]:max-w-[calc(100%-16px)] [&_h1]:absolute [&_h1]:m-0 [&_h1]:size-px [&_h1]:overflow-hidden [&_h1]:border-0 [&_h1]:p-0 [&_h1]:whitespace-nowrap [&_h1]:[clip:rect(0,0,0,0)]">
        <h1>圆桌语音演示</h1>
        <div className="flex max-w-full gap-[3px] overflow-x-auto rounded-lg border border-[rgba(211,167,74,0.52)] bg-[rgba(252,250,246,0.94)] p-1 shadow-[0_8px_24px_rgba(39,35,61,0.18)] backdrop-blur-[14px]">
          <input
            aria-label="选择本地语音目录"
            className="hidden"
            onChange={(event) => void loadDirectory(event)}
            ref={pickerRef}
            type="file"
          />
          <button
            className="min-h-[34px] cursor-pointer rounded-[5px] border-0 bg-transparent px-3 py-1.5 text-[0.84rem] font-[650] whitespace-nowrap text-(--indigo-dark) hover:enabled:bg-(--gold-soft) hover:enabled:text-(--indigo-dark) focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-(--indigo) disabled:cursor-not-allowed disabled:opacity-50 max-[360px]:px-[7px] max-[360px]:text-[0.82rem]"
            aria-label="选择本地语音目录"
            onClick={() => pickerRef.current?.click()}
            type="button"
          >
            <span className="max-[360px]:hidden">选择目录</span>
            <span className="hidden max-[360px]:inline">目录</span>
          </button>
          <button
            className="min-h-[34px] cursor-pointer rounded-[5px] border-0 bg-transparent px-3 py-1.5 text-[0.84rem] font-[650] whitespace-nowrap text-(--indigo-dark) hover:enabled:bg-(--gold-soft) hover:enabled:text-(--indigo-dark) focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-(--indigo) disabled:cursor-not-allowed disabled:opacity-50 max-[360px]:px-[7px] max-[360px]:text-[0.82rem] enabled:bg-(--indigo) enabled:text-white hover:enabled:bg-(--gold-soft) hover:enabled:text-(--indigo-dark)"
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
            className="min-h-[34px] cursor-pointer rounded-[5px] border-0 bg-transparent px-3 py-1.5 text-[0.84rem] font-[650] whitespace-nowrap text-(--indigo-dark) hover:enabled:bg-(--gold-soft) hover:enabled:text-(--indigo-dark) focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-(--indigo) disabled:cursor-not-allowed disabled:opacity-50 max-[360px]:px-[7px] max-[360px]:text-[0.82rem]"
            disabled={
              !debate || index < 0 || index >= debate.manifest.turns.length - 1
            }
            onClick={() => void playTurn(index + 1)}
            type="button"
          >
            下一位
          </button>
          <button
            className="min-h-[34px] cursor-pointer rounded-[5px] border-0 bg-transparent px-3 py-1.5 text-[0.84rem] font-[650] whitespace-nowrap text-(--indigo-dark) hover:enabled:bg-(--gold-soft) hover:enabled:text-(--indigo-dark) focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-(--indigo) disabled:cursor-not-allowed disabled:opacity-50 max-[360px]:px-[7px] max-[360px]:text-[0.82rem]"
            aria-label={showTranscript ? "收起文字记录" : "显示文字记录"}
            aria-controls="local-roundtable-transcript"
            aria-expanded={showTranscript}
            onClick={() => setShowTranscript((current) => !current)}
            type="button"
          >
            <span className="max-[360px]:hidden">
              {showTranscript ? "收起记录" : "文字记录"}
            </span>
            <span className="hidden max-[360px]:inline">记录</span>
          </button>
        </div>
      </header>

      {message ? (
        <p
          className="absolute bottom-3.5 left-3.5 z-[9] m-0 max-w-[calc(100%-28px)] rounded-md border border-[rgba(211,167,74,0.5)] bg-[rgba(252,250,246,0.96)] px-2.5 py-1.5 text-[0.82rem] text-(--ink)"
          role="status"
        >
          {message}
        </p>
      ) : null}

      <section
        aria-label="辩论文字"
        className="absolute inset-x-0 bottom-0 z-[8] grid h-[clamp(220px,34dvh,360px)] grid-rows-[auto_1fr] border-t-2 border-(--gold) bg-[rgba(252,250,246,0.58)] px-6 py-4 [font-family:Songti_SC,Noto_Serif_CJK_SC,Source_Han_Serif_SC,SimSun,serif] backdrop-blur-[6px] max-[700px]:h-[min(45dvh,360px)] max-[700px]:p-3"
        hidden={!showTranscript}
        id="local-roundtable-transcript"
      >
        <div className="flex items-baseline justify-between gap-3 max-[700px]:flex-col max-[700px]:items-start max-[700px]:gap-0.5 [&_h2]:m-0 [&_h2]:min-w-0 [&_h2]:truncate [&_h2]:text-base [&_h2]:font-bold">
          <h2>{debate?.manifest.topic ?? "发言记录"}</h2>
        </div>
        <div className="overflow-y-auto">
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
                className="grid grid-cols-[72px_1fr] gap-3 border-b border-(--line) py-2.5 data-[active=true]:[&_strong]:text-(--indigo-dark) [&_strong]:text-[0.9rem] [&_p]:m-0 [&_p]:min-h-[1.5em] [&_p]:text-base [&_p]:leading-normal"
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
