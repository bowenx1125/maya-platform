"use client";

import type { CSSProperties, ReactNode } from "react";

import { useT } from "../../lib/i18n";
import { cn } from "../../lib/utils";
import { MascotFigure, type MascotId } from "./mascots";
import { useAcademyMood } from "./mood";

/*
 * The sign-in stage, proposal 38 v3 (docs/ui-proposals/auth): scheme 1's
 * title screen with scheme 2's character cards and scheme 3's comic beats.
 * The cards answer the mood the forms already set: a field being filled in
 * lifts the picked card and sends speed lines at the form, a password flips
 * every card face down, a refused sign-in rains on the scene for its beat.
 */

const CARDS: { id: MascotId; bg: string }[] = [
  { id: "scroll", bg: "#C4B5FD" },
  { id: "wreath", bg: "#FFB4C8" },
  { id: "tablet", bg: "#A3E635" },
  { id: "wave", bg: "#FFE14D" },
];
const TILTS = [-7, -2, 3, 8];

export function Star({
  size,
  fill = "#FFE14D",
  className,
}: {
  size: number;
  fill?: string;
  className?: string;
}) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 100 100"
      width={size}
      height={size}
      className={cn("pointer-events-none absolute", className)}
    >
      <path
        d="M50 4 61 37 96 37 68 58 79 92 50 71 21 92 32 58 4 37 39 37Z"
        fill={fill}
        stroke="#111"
        strokeWidth="6"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** A comic burst with no words in it. */
export function Burst({
  size,
  fill,
  className,
}: {
  size: number;
  fill: string;
  className?: string;
}) {
  const points = Array.from({ length: 28 }, (_, i) => {
    const r = i % 2 ? 36 : 50;
    const a = (Math.PI * 2 * i) / 28;
    return `${(50 + r * Math.cos(a)).toFixed(2)},${(50 + r * Math.sin(a)).toFixed(2)}`;
  }).join(" ");
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 100 100"
      width={size}
      height={size}
      className={cn("pointer-events-none absolute", className)}
    >
      <polygon
        points={points}
        fill={fill}
        stroke="#111"
        strokeWidth="2.5"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function Sweat({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn("pointer-events-none absolute flex gap-1", className)}
    >
      {[-10, 20].map((turn) => (
        <i
          key={turn}
          className="block h-5 w-3.5 rounded-[50%_50%_50%_50%/60%_60%_40%_40%] border-[3px] border-[#111] bg-[#67E8F9]"
          style={{ transform: `rotate(${turn}deg)` }}
        />
      ))}
    </span>
  );
}

/** The page-wide layers behind both columns: rain, stage floor, speed lines. */
export function SignInBackdrop() {
  const mood = useAcademyMood();
  return (
    <>
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(#FF4D8D_2.4px,transparent_2.9px)] bg-[length:18px_18px] [mask-image:radial-gradient(circle_at_100%_0%,#000_0_18%,transparent_34%),radial-gradient(circle_at_0%_0%,#000_0_10%,transparent_22%)]"
      />
      {mood === "refused" ? (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 bg-[#C9D3F0d9] bg-[repeating-linear-gradient(100deg,transparent_0_26px,#ffffff88_26px_29px)]"
        />
      ) : null}
      <div
        aria-hidden="true"
        className="absolute right-0 bottom-0 left-0 h-[110px] border-t-[8px] border-[#111] bg-[#A3E635] bg-[repeating-linear-gradient(90deg,#0000_0_40px,#0001_40px_80px)] max-[767px]:top-[392px] max-[767px]:bottom-auto max-[767px]:h-[64px]"
      />
      {mood === "attentive" ? (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute top-[30%] left-[44%] h-[34%] w-[16%] bg-[repeating-linear-gradient(0deg,transparent_0_18px,#111_18px_22px)] [mask-image:linear-gradient(90deg,transparent,#000_40%,#000_70%,transparent)] max-[767px]:hidden"
        />
      ) : null}
    </>
  );
}

/** Title, burst and stars, then the four character cards on the stage. */
export function SignInStage({ picked }: { picked: number }) {
  const t = useT();
  const mood = useAcademyMood();
  const hidden = mood === "discreet";
  const sad = mood === "refused";
  return (
    <section
      className="relative min-h-[620px] max-[767px]:h-[456px] max-[767px]:min-h-0"
      aria-label={t("academyStageLabel")}
    >
      <p className="absolute top-12 left-16 z-[2] m-0 -rotate-3 border-[4px] border-[#111] bg-white bg-[linear-gradient(90deg,#A3E635_0_12px,transparent_12px_calc(100%-12px),#A3E635_calc(100%-12px))] px-5 py-1 font-body text-[15px] font-extrabold tracking-[.16em] text-[#111] shadow-[5px_5px_0_#111] max-[767px]:top-5 max-[767px]:left-4 max-[767px]:text-[10px]">
        {t("academyEyebrow")}
      </p>
      <div className="absolute top-[118px] left-12 max-[767px]:top-16 max-[767px]:left-3">
        <Burst
          size={280}
          fill="#FFFFFF"
          className="-top-24 left-[-30px] -rotate-6 max-[767px]:hidden"
        />
        <h1 className="relative m-0 -rotate-[6deg] rounded-[24px] border-[5px] border-[#111] bg-[#FF4D8D] py-2 pr-14 pl-8 font-display text-[124px] leading-none font-extrabold text-white shadow-[12px_12px_0_#111] [-webkit-text-stroke:5px_#111] [paint-order:stroke_fill] after:absolute after:top-1/2 after:-right-[10px] after:-translate-y-1/2 after:border-y-[22px] after:border-l-[34px] after:border-y-transparent after:border-l-[#111] after:content-[''] max-[1100px]:text-[96px] max-[767px]:pr-9 max-[767px]:pl-5 max-[767px]:text-[62px] max-[767px]:shadow-[7px_7px_0_#111] max-[767px]:[-webkit-text-stroke:3px_#111]">
          {t("appName")}
        </h1>
        <Star
          size={104}
          className="-top-16 -right-16 z-10 rotate-12 max-[767px]:-top-8 max-[767px]:-right-6 max-[767px]:size-12"
        />
        <Star
          size={64}
          fill="#67E8F9"
          className="-bottom-16 left-10 z-10 -rotate-12 max-[767px]:-bottom-9 max-[767px]:size-[34px]"
        />
        <Star
          size={46}
          fill="#A3E635"
          className="-top-10 left-[40%] z-10 rotate-6 max-[767px]:-top-6 max-[767px]:size-[26px]"
        />
      </div>
      <div
        role="img"
        aria-label={t("signInCastLabel")}
        className="absolute right-4 bottom-[88px] left-6 flex items-end justify-center max-[767px]:top-[226px] max-[767px]:right-2 max-[767px]:bottom-auto max-[767px]:left-2"
      >
        {CARDS.map((card, index) => (
          <CharacterCard
            key={card.id}
            id={card.id}
            bg={card.bg}
            tilt={TILTS[index] + (sad ? (index % 2 ? 12 : -12) : 0)}
            lift={
              index === picked && !hidden && !sad
                ? -44
                : sad
                  ? 14
                  : index % 2
                    ? 0
                    : 10
            }
            chosen={index === picked && !hidden && !sad}
            sweat={sad && index % 2 === 1}
          />
        ))}
      </div>
    </section>
  );
}

function CharacterCard({
  id,
  bg,
  tilt,
  lift,
  chosen,
  sweat,
}: {
  id: MascotId;
  bg: string;
  tilt: number;
  lift: number;
  chosen: boolean;
  sweat: boolean;
}) {
  const mood = useAcademyMood();
  const hidden = mood === "discreet";
  const face: CSSProperties = hidden
    ? {
        backgroundColor: "#FF4D8D",
        backgroundImage:
          "radial-gradient(circle,#FFE14D 0 8px,transparent 9px),radial-gradient(circle,#ffffff 0 5px,transparent 6px)",
        backgroundSize: "38px 38px",
        backgroundPosition: "0 0,19px 19px",
      }
    : {
        backgroundColor: mood === "refused" ? "#C9D3F0" : bg,
        backgroundImage:
          "repeating-conic-gradient(from 0deg at 50% 72%,#ffffff66 0 9deg,transparent 9deg 18deg)",
      };
  let marks: ReactNode = null;
  if (chosen)
    marks = (
      <>
        <span
          aria-hidden="true"
          className="absolute -top-14 left-1/2 z-[2] h-0 w-0 -translate-x-1/2 border-x-[20px] border-t-[28px] border-x-transparent border-t-[#FF4D8D] drop-shadow-[3px_3px_0_#111] max-[767px]:-top-8 max-[767px]:border-x-[11px] max-[767px]:border-t-[15px]"
        />
        {mood === "attentive" ? (
          <span
            aria-hidden="true"
            className="absolute -top-6 -right-3 z-[3] grid size-9 place-items-center rounded-full border-[3px] border-[#111] bg-[#FFE14D] font-display text-xl font-extrabold text-[#111] shadow-[3px_3px_0_#111]"
          >
            !
          </span>
        ) : null}
      </>
    );
  return (
    <div
      className={cn(
        "relative -ml-5 w-[172px] shrink-0 transition-transform duration-300 ease-[cubic-bezier(.2,1.4,.4,1)] first:ml-0 motion-reduce:transition-none max-[1100px]:w-[140px] max-[767px]:-ml-3 max-[767px]:w-[92px]",
        chosen && "z-10",
      )}
      style={{
        transform: `rotate(${tilt}deg) translateY(${lift}px) scale(${chosen ? 1.1 : 1})`,
      }}
    >
      {marks}
      {sweat ? <Sweat className="-top-7 left-6 z-[3]" /> : null}
      <div
        className={cn(
          "relative h-[270px] overflow-hidden rounded-[20px] border-[5px] border-[#111] shadow-[7px_7px_0_#111] max-[1100px]:h-[220px] max-[767px]:h-[150px] max-[767px]:rounded-[12px] max-[767px]:border-[3px]",
          chosen &&
            "outline-[6px] outline-offset-[3px] outline-[#FF4D8D] max-[767px]:outline-[4px]",
        )}
        style={face}
      >
        {hidden ? (
          <span
            aria-hidden="true"
            className="absolute top-1/2 left-1/2 size-14 -translate-x-1/2 -translate-y-1/2 rounded-full border-[4px] border-[#111] bg-[linear-gradient(90deg,#111_50%,#FF4D8D_50%)] max-[767px]:size-8"
          />
        ) : (
          <MascotFigure
            id={id}
            mood={mood}
            className="absolute bottom-[-6px] left-1/2 h-[236px] w-auto -translate-x-1/2 max-[1100px]:h-[190px] max-[767px]:h-[128px]"
          />
        )}
      </div>
    </div>
  );
}
