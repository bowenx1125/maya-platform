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

// An 8-bit music note on a 7x8 grid, drawn as pixels.
const PIXEL_NOTE: ReadonlyArray<readonly [number, number, number, number]> = [
  [3, 0, 4, 1], // flag
  [3, 1, 1, 5], // stem
  [6, 1, 1, 1],
  [1, 5, 2, 2], // head
  [0, 6, 1, 1],
  [3, 6, 1, 1],
  [1, 7, 2, 1],
];

// The sidebar's keycap (48px, 3px border, press motion) with a console face:
// the whole key is the dark screen, so no light ring shows around it.
const MUSIC_KEY_FACE = "bg-[#1F2937] inset-shadow-[0_2px_0_#ffffff26]";
const KEYCAP = `relative grid size-12 shrink-0 cursor-pointer place-items-center rounded-arc-s border-[3px] border-border ${MUSIC_KEY_FACE} ${PRESS_MOTION} disabled:cursor-not-allowed disabled:opacity-50`;

/**
 * A music key dressed as a handheld console: the dark face is the screen,
 * with a pixel note, dim when off, lit and bobbing while its music plays,
 * and a corner LED. The sidebar key drives the workspace music; the 3D
 * stage has its own. Its name is for screen readers only; the screen and
 * LED say the rest.
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
  return (
    <button
      type="button"
      data-music-key={channel}
      data-playing={on || undefined}
      className={cn(KEYCAP, className)}
      aria-label={
        !available
          ? t("musicUnavailable")
          : on
            ? t("musicPause")
            : t("musicPlay")
      }
      aria-pressed={on}
      disabled={!available}
      onClick={() => toggleMusic(channel)}
    >
      <span
        aria-hidden="true"
        className={`absolute top-[4px] right-[4px] size-[6px] rounded-full ${on ? "bg-[#4ADE80] shadow-[0_0_6px_#4ADE80]" : "bg-[#4B5563]"}`}
      />
      <svg
        aria-hidden="true"
        width="18"
        height="20"
        viewBox="0 0 7 8"
        shapeRendering="crispEdges"
        className={
          on
            ? "animate-[music-bob_0.9s_ease-in-out_infinite] fill-[#A3E635] drop-shadow-[0_0_3px_#A3E635] motion-reduce:animate-none"
            : "fill-[#A3E635]/60"
        }
      >
        {PIXEL_NOTE.map(([x, y, w, h]) => (
          <rect key={`${x}-${y}`} x={x} y={y} width={w} height={h} />
        ))}
      </svg>
    </button>
  );
}
