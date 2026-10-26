"use client";

import { MascotFigure, type MascotId } from "./academy/mascots";
import { agentMascot, agentTone } from "./ui/agent-card";
import { cn } from "../lib/utils";

/** Match final-v2b SUN(): repeating-conic at 50% 70%. */
export const CHAT_SUN = (bg: string) =>
  ({
    backgroundColor: bg,
    backgroundImage:
      "repeating-conic-gradient(from 0deg at 50% 70%,#ffffff66 0 10deg,transparent 10deg 20deg)",
  }) as const;

/** C empty: three grey ghost / character-select dashed slots. */
export function ChatEmptyGhosts() {
  const ids: MascotId[] = ["wave", "wreath", "scroll"];
  return (
    <div className="mx-auto flex gap-3" aria-hidden="true">
      {ids.map((id) => (
        <span
          key={id}
          className="grid h-20 w-16 place-items-end overflow-hidden rounded-[8px] border-[3px] border-dashed border-[#111]/50"
        >
          <MascotFigure
            id={id}
            className="h-16 w-auto opacity-40 grayscale"
          />
        </span>
      ))}
    </div>
  );
}

/** v2b newconv: 224px (w-56) radiant disk + agent's own avatar. */
export function ChatRadiantDisk({
  agentId,
  materialTheme,
}: {
  agentId: string;
  materialTheme?: string | null;
}) {
  const mascot = agentMascot(agentId, materialTheme);
  const tone = agentTone(agentId);
  return (
    <div className="relative m-auto mt-2 mb-6 h-56 w-56" aria-hidden="true">
      <div
        className="absolute inset-0 rounded-full border-[3px] border-[#111] shadow-[6px_6px_0_#111]"
        style={CHAT_SUN(tone)}
      />
      <MascotFigure
        id={mascot}
        className="absolute bottom-2 left-1/2 h-48 w-auto -translate-x-1/2"
      />
    </div>
  );
}

/** Light peeking-avatar strip (C silhouette, A palette). */
export function ChatPeekAvatar({
  agentId,
  materialTheme,
}: {
  agentId: string;
  materialTheme?: string | null;
}) {
  const mascot = agentMascot(agentId, materialTheme);
  const tone = agentTone(agentId);
  return (
    <span
      className="relative -mb-px grid h-[4.25rem] w-16 place-items-end overflow-hidden rounded-t-[10px] border-[3px] border-b-0 border-[#111] shadow-[3px_0_0_#111]"
      style={CHAT_SUN(tone)}
      aria-hidden="true"
    >
      <MascotFigure id={mascot} className="h-16 w-auto" />
    </span>
  );
}

/** History row / bubble avatar — square sunburst + mascot. */
export function ChatAvatar({
  agentId,
  materialTheme,
  size = 36,
  className,
}: {
  agentId: string;
  materialTheme?: string | null;
  size?: number;
  className?: string;
}) {
  const mascot = agentMascot(agentId, materialTheme);
  const tone = agentTone(agentId);
  return (
    <span
      className={cn(
        "grid shrink-0 place-items-end overflow-hidden rounded-[8px] border-2 border-[#111]",
        className,
      )}
      style={{ width: size, height: size, ...CHAT_SUN(tone) }}
      aria-hidden="true"
    >
      <MascotFigure
        id={mascot}
        className={size <= 30 ? "h-[27px] w-auto" : size <= 36 ? "h-[32px] w-auto" : "h-[40px] w-auto"}
      />
    </span>
  );
}

export function chatTapeTitleClass(extra?: string) {
  return cn(
    "m-0 inline-block -rotate-1 border-[2.5px] border-[#111] bg-[#FFE14D] px-3 font-display text-lg font-extrabold text-[#111] shadow-[2px_2px_0_#111]",
    extra,
  );
}

export function chatKindChipClass(extra?: string) {
  return cn(
    "mb-0.5 inline-block rounded-[4px] border-2 border-[#111] bg-white px-1.5 text-[11px] font-extrabold text-[#111] shadow-[2px_2px_0_#111]",
    extra,
  );
}

export function chatHistoryTapeClass(extra?: string) {
  return cn(
    "m-0 ml-2 inline-block -mt-5 -rotate-2 border-[2.5px] border-[#111] bg-[#FFE14D] px-3 py-0.5 font-display text-lg font-extrabold text-[#111] shadow-[2px_2px_0_#111]",
    extra,
  );
}
