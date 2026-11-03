"use client";

import {
  musicAvailable,
  toggleMusic,
  useMusicOn,
  type MusicChannelName,
} from "../lib/background-music";
import { useT } from "../lib/i18n";
import { cn } from "../lib/utils";
import { PRESS_MOTION } from "./ui/button";

// The sidebar's keycap: 48px, 3px border, press motion. Colours are
// !important so the 3D stage dock's pill rules cannot repaint the key.
const KEYCAP = `relative grid size-12 shrink-0 cursor-pointer place-items-center rounded-arc-s border-[3px] ${PRESS_MOTION} disabled:cursor-not-allowed`;

const FACE = {
  // No music set: grey, dashed ghost of the note, not pressable.
  empty:
    "!border-[#6B7280] !bg-[#E5E7EB] !shadow-[0_6px_0_#9CA3AF] !opacity-100",
  // Stopped: purple, the note sleeps.
  stop: "!border-border !bg-[#C4B5FD] !shadow-[0_6px_0_#111] active:!shadow-none",
  // Playing: the face flashes lime / cyan / yellow (lime when still).
  playing:
    "!border-border bg-[#A3E635] animate-[music-face_2.4s_steps(1)_infinite] !shadow-[0_6px_0_#111] active:!shadow-none motion-reduce:animate-none motion-reduce:!bg-[#A3E635]",
} as const;

/** The pixel note buddy on a 13x15 grid: stem, flag and a head with a face. */
function NoteBuddy({ awake }: { awake: boolean }) {
  return (
    <svg
      aria-hidden="true"
      width="26"
      height="30"
      viewBox="0 0 13 15"
      shapeRendering="crispEdges"
      className={
        awake
          ? "origin-bottom animate-[music-hop_0.6s_ease-in-out_infinite] motion-reduce:animate-none"
          : undefined
      }
    >
      <g fill="#111">
        <rect x="6" y="0" width="6" height="2" />
        <rect x="10" y="2" width="2" height="1" />
        <rect x="6" y="2" width="2" height="8" />
        <rect x="1" y="9" width="7" height="6" />
      </g>
      <rect x="2" y="10" width="5" height="4" fill="#fff" />
      {awake ? (
        <>
          <g fill="#111">
            <rect x="3" y="11" width="1" height="1" />
            <rect x="5" y="11" width="1" height="1" />
            <rect x="3" y="13" width="3" height="1" />
          </g>
          <rect x="2" y="12" width="1" height="1" fill="#FF4D8D" />
          <rect x="6" y="12" width="1" height="1" fill="#FF4D8D" />
        </>
      ) : (
        <g fill="#111">
          <rect x="2" y="12" width="2" height="1" />
          <rect x="5" y="12" width="2" height="1" />
        </g>
      )}
    </svg>
  );
}

function NoteGhost() {
  return (
    <svg
      aria-hidden="true"
      width="26"
      height="30"
      viewBox="0 0 13 15"
      shapeRendering="crispEdges"
      fill="none"
      stroke="#6B7280"
      strokeWidth="1"
      strokeDasharray="1 1"
    >
      <path d="M6.5 1.5h5v2h-3v8" />
      <rect x="1.5" y="9.5" width="7" height="5" />
    </svg>
  );
}

const POP =
  "pointer-events-none absolute text-[11px] leading-none font-black text-ink opacity-0 motion-reduce:hidden";

/**
 * A music key (option C, chosen 2026-11-03): a pixel note buddy. Empty (no
 * music set) is a grey dashed ghost; stopped, it sleeps on purple; playing,
 * it wakes, smiles and hops while notes pop out and the face flashes. The
 * sidebar key drives the workspace music; the 3D stage has its own. Its name
 * is for screen readers only; the buddy says the rest.
 */
export function MusicKey({
  channel,
  className,
}: {
  channel: MusicChannelName;
  className?: string;
}) {
  const t = useT();
  const on = useMusicOn(channel);
  const available = musicAvailable(channel);
  const state = !available ? "empty" : on ? "playing" : "stop";
  return (
    <button
      type="button"
      data-music-key={channel}
      data-music-state={state}
      data-playing={on || undefined}
      className={cn(KEYCAP, FACE[state], className)}
      aria-label={
        state === "empty"
          ? t("musicUnavailable")
          : on
            ? t("musicPause")
            : t("musicPlay")
      }
      aria-pressed={on}
      disabled={!available}
      onClick={() => toggleMusic(channel)}
    >
      {state === "empty" ? <NoteGhost /> : <NoteBuddy awake={on} />}
      {on ? (
        <>
          <span
            aria-hidden="true"
            className={`${POP} top-0 -left-[5px] animate-[music-pop_1.2s_ease-out_infinite]`}
          >
            ♪
          </span>
          <span
            aria-hidden="true"
            className={`${POP} top-1 -right-[7px] animate-[music-pop_1.2s_ease-out_0.6s_infinite]`}
          >
            ♫
          </span>
        </>
      ) : null}
    </button>
  );
}
