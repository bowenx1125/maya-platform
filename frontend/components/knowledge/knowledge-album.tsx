"use client";

import type { ReactNode } from "react";

import { cn } from "../../lib/utils";
import { PRESS_MOTION } from "../ui/button";

/**
 * Teacher Knowledge "A album" (proposals/21-knowledge-final v2), as Tailwind
 * classes. The form fields reuse the RAG album's shared `albumStyles.fl`
 * (File Name / Content labels, 800 20px Bricolage, 8px gap).
 */
export const knowledgeAlbum = {
  alb: `relative box-border w-full max-w-[1120px] mx-auto text-[#111] [font-family:var(--font-lexend,'Lexend'),system-ui,sans-serif] bg-[#fff8e7] [background-image:radial-gradient(#e9dfc4_1.5px,transparent_1.5px)] [background-size:22px_22px] border-[3px] border-solid border-[#111] rounded-[14px] shadow-[10px_10px_0_#111] pt-[28px] pr-[36px] pb-[40px] pl-[92px] min-h-[720px] max-[960px]:pt-[16px] max-[960px]:pr-[14px] max-[960px]:pb-[24px] max-[960px]:pl-[14px] max-[960px]:min-h-0 max-[960px]:shadow-[6px_6px_0_#111] [&_*]:box-border [&_p]:m-0`,
  /** Create/edit: the rings stay at 390 (RAG 33 impl). */
  albEd: `max-[960px]:!pl-[58px]`,
  rings: `absolute left-[22px] top-[70px] bottom-[70px] flex flex-col justify-between [&_i]:block [&_i]:w-[30px] [&_i]:h-[14px] [&_i]:border-[3px] [&_i]:border-solid [&_i]:border-[#111] [&_i]:rounded-[10px] [&_i]:bg-[#ffe14d] max-[960px]:hidden`,
  ringsEd: `max-[960px]:!flex max-[960px]:!left-[12px]`,
  top: `flex items-center gap-[14px] h-[64px] mb-[22px] max-[960px]:h-auto max-[960px]:flex-wrap max-[960px]:gap-[10px] max-[960px]:mb-[16px]`,
  title: `m-0 inline-block bg-[#a3e635] border-[3px] border-solid border-[#111] rounded-[6px] shadow-[5px_5px_0_#111] py-[4px] px-[18px] [transform:rotate(-2deg)] [font:800_36px/normal_var(--font-bricolage,'Bricolage_Grotesque'),system-ui] max-[960px]:text-[28px]`,
  titleEd: `max-[960px]:!text-[24px] max-[960px]:!py-[3px] max-[960px]:!px-[12px]`,
  tape: `w-[58px] h-[18px] bg-[#67e8f9] border-2 border-solid border-[#111] [transform:rotate(6deg)] max-[960px]:hidden`,
  sp: "flex-1",
  acts: "flex gap-[12px] ml-auto",
  btn: `!inline-flex !items-center !gap-[6px] !h-[40px] !py-0 !px-[16px] !border-[2.5px] !border-solid !border-[#111] !rounded-[8px] ![font:800_14px_var(--font-lexend,'Lexend')] !bg-white !text-[#111] ${PRESS_MOTION}`,
  pink: "!bg-[#ff4d8d] hover:!bg-[#ff4d8d]",
  del: "!ml-auto !bg-[#ef4444] !text-white hover:!bg-[#ef4444]",
  grid: `grid grid-cols-[repeat(2,minmax(0,1fr))] gap-y-[30px] gap-x-[28px] m-0 p-0 list-none max-[960px]:grid-cols-[minmax(0,1fr)] max-[960px]:gap-[22px]`,
  card: "relative flex flex-col gap-[10px] p-[10px] border-[3px] border-solid border-[#111] rounded-[12px] shadow-[6px_6px_0_#111] [&:nth-child(4n+1)]:[transform:rotate(-1.2deg)] [&:nth-child(4n+2)]:[transform:rotate(1deg)] [&:nth-child(4n+3)]:[transform:rotate(-0.8deg)] [&:nth-child(4n)]:[transform:rotate(1.1deg)]",
  art: "h-[104px] border-[3px] border-solid border-[#111] rounded-[8px] overflow-hidden bg-white",
  plate: "flex flex-col gap-[10px] p-[12px] bg-white border-2 border-solid border-[#111] rounded-[8px]",
  fn: "[font:700_16px_var(--font-lexend,'Lexend')] text-[#111] text-left [overflow-wrap:anywhere] whitespace-normal [background:none] border-0 p-0 cursor-pointer",
  renameInput: "[font:700_16px_var(--font-lexend,'Lexend')] border-2 border-solid border-[#111] rounded-[6px] py-[2px] px-[6px]",
  bad: "block w-fit py-[4px] px-[8px] border-2 border-solid border-[#111] rounded-[6px] bg-[#ffe4e4] text-[#b91c1c] [font:600_12px_var(--font-lexend,'Lexend')]",
  ag: "w-fit py-[2px] px-[10px] bg-[#67e8f9] border-2 border-solid border-[#111] rounded-full shadow-[2px_2px_0_#111] [font:800_12px_var(--font-lexend,'Lexend')]",
  ft: "flex items-center gap-[10px] min-h-[40px]",
  ib: "!inline-grid !place-items-center !w-[40px] !h-[40px] !p-0 !bg-white !border-[2.5px] !border-solid !border-[#111] !rounded-[8px] !shadow-[4px_4px_0_#111] !opacity-60",
  ghost: "grid place-items-center min-h-[300px] text-[#b9ae90] border-[3px] border-dashed border-[#b9ae90] rounded-[12px]",
  ghostFirst: "grid place-items-center content-center justify-items-center gap-[16px] min-h-[300px] text-[#111] bg-white border-[3px] border-solid border-[#111] rounded-[12px] shadow-[6px_6px_0_#111] [&_p]:m-0 [&_p]:py-[4px] [&_p]:px-[14px] [&_p]:bg-[#ffe14d] [&_p]:border-[3px] [&_p]:border-solid [&_p]:border-[#111] [&_p]:rounded-[6px] [&_p]:shadow-[4px_4px_0_#111] [&_p]:[transform:rotate(-2deg)] [&_p]:[font:800_22px_var(--font-bricolage,'Bricolage_Grotesque'),system-ui]",
  ghostArt: "w-[180px] h-[70px] border-[3px] border-solid border-[#111] rounded-[8px] overflow-hidden",
  spread: `grid grid-cols-[240px_minmax(0,1fr)] gap-[34px] items-start max-[960px]:grid-cols-[minmax(0,1fr)] max-[960px]:gap-[22px]`,
  lcol: "flex flex-col gap-[22px]",
  pack: `relative grid place-items-center h-[310px] border-[3px] border-solid border-[#111] border-y-[14px] rounded-[10px] shadow-[6px_6px_0_#111] [transform:rotate(-1.5deg)] cursor-pointer [background:repeating-conic-gradient(from_0deg_at_50%_50%,#ff4d8d_0_10deg,#ff8db5_10deg_20deg)] max-[960px]:h-[170px]`,
  disc: `grid place-items-center w-[96px] h-[96px] rounded-full bg-[#ffe14d] border-[3px] border-solid border-[#111] shadow-[4px_4px_0_#111] max-[960px]:w-[72px] max-[960px]:h-[72px]`,
  req: "relative py-[14px] px-[16px] bg-[#fff1d6] border-[2.5px] border-solid border-[#111] border-l-[12px] border-l-[#ff4d8d] rounded-[6px] shadow-[5px_5px_0_#111] [transform:rotate(-1.2deg)] [font:700_14px/1.45_var(--font-lexend,'Lexend')]",
  blank: "p-[12px] bg-[#67e8f9] border-[3px] border-solid border-[#111] rounded-[12px] shadow-[7px_7px_0_#111]",
  in: "flex flex-col gap-[16px] p-[18px] bg-white border-[3px] border-solid border-[#111] rounded-[8px]",
  /** U3 field error: red edge on the File Name input. */
  flErr: "[&_input]:!border-[#ef4444] [&_input]:!shadow-[3px_3px_0_#ef4444]",
  em: "text-[#dc2626] [font:600_13px_var(--font-lexend,'Lexend')]",
} as const;

/** Knowledge graph art: three linked nodes (no #01, no MD). */
export function KnowledgeArt({ id }: { id: string }) {
  return (
    <svg
      viewBox="0 0 320 100"
      width="100%"
      height="100%"
      preserveAspectRatio="xMidYMid slice"
      aria-hidden="true"
    >
      <defs>
        <linearGradient id={id} x1="0" x2="1" y1="0" y2="1">
          <stop stopColor="#E0FBFF" />
          <stop offset=".5" stopColor="#FBCFE8" />
          <stop offset="1" stopColor="#C7F9FF" />
        </linearGradient>
      </defs>
      <rect width="320" height="100" fill={`url(#${id})`} />
      <path
        d="M130 58 L165 34 M132 62 L192 66 M175 38 L190 58"
        stroke="#111"
        strokeWidth="3"
      />
      <circle cx="125" cy="60" r="15" fill="#A3E635" stroke="#111" strokeWidth="3" />
      <circle cx="170" cy="32" r="13" fill="#67E8F9" stroke="#111" strokeWidth="3" />
      <circle cx="198" cy="66" r="14" fill="#FF4D8D" stroke="#111" strokeWidth="3" />
    </svg>
  );
}

export function KnowledgeRings({ editor }: { editor?: boolean }) {
  return (
    <div
      className={cn(knowledgeAlbum.rings, editor && knowledgeAlbum.ringsEd)}
      aria-hidden="true"
    >
      {Array.from({ length: 7 }, (_, index) => (
        <i key={index} />
      ))}
    </div>
  );
}

const ICONS = {
  plus: "M12 5v14M5 12h14",
  download: "M12 4v11m-5-5 5 5 5-5M5 20h14",
  trash: "M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13",
  upload: "M12 20V8m-5 5 5-5 5 5M5 4h14",
} as const;

export function KnowledgeIcon({
  name,
  size = 16,
  stroke = 2.6,
}: {
  name: keyof typeof ICONS;
  size?: number;
  stroke?: number;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={stroke}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={ICONS[name]} />
    </svg>
  );
}

/** One Knowledge card: tone by generation state. */
export function KnowledgeCard({
  tone,
  artId,
  children,
  footer,
}: {
  tone: "" | "running" | "failed";
  artId: string;
  children: ReactNode;
  footer: ReactNode;
}) {
  return (
    <li
      className={cn(
        knowledgeAlbum.card,
        tone === "running"
          ? "bg-[#fde68a]"
          : tone === "failed"
            ? "bg-[#fca5a5]"
            : "bg-[#a3e635]",
      )}
    >
      <div className={knowledgeAlbum.art}>
        <KnowledgeArt id={artId} />
      </div>
      <div className={knowledgeAlbum.plate}>{children}</div>
      <div className={knowledgeAlbum.ft}>{footer}</div>
    </li>
  );
}
