"use client";

/*
 * Proposal 38 v2 · bold Arcade sign-in and registration (design only).
 * Three schemes with the mascots reacting to the form. Every string comes
 * from t(); decorations are aria-hidden. Demo pages exist only under
 * `next dev`:  /auth-proposals?s=1|2|3&state=login|user|pw|error|reg1|reg2
 */

import { Suspense, useEffect, type CSSProperties, type ReactNode } from "react";
import { useSearchParams } from "next/navigation";

import {
  AcademyMoodProvider,
  useSetAcademyMood,
  type AcademyMood,
} from "../../components/academy/mood";
import {
  AcademyMascots,
  MascotFigure,
  type MascotId,
} from "../../components/academy/mascots";
import { DismissibleAlert } from "../../components/dismissible-alert";
import { PRESS_MOTION } from "../../components/ui/button";
import { useT } from "../../lib/i18n";
import { cn } from "../../lib/utils";

type State = "login" | "user" | "pw" | "error" | "reg1" | "reg2";
type T = ReturnType<typeof useT>;

const MOOD: Record<State, AcademyMood> = {
  login: "idle",
  user: "attentive",
  pw: "discreet",
  error: "refused",
  reg1: "attentive",
  reg2: "idle",
};
const CAST: MascotId[] = ["scroll", "wreath", "tablet", "wave"];

/* ── shared pieces ─────────────────────────────────────────────── */

const INPUT =
  "box-border h-[54px] w-full rounded-[12px] border-[4px] border-[#111] bg-white px-4 font-body text-lg font-bold text-[#111] outline-none";
const FOCUS = "shadow-[5px_5px_0_#FF4D8D] -translate-y-0.5";
const BIG_PRIMARY = `box-border h-[62px] w-full cursor-pointer rounded-[16px] border-[4px] border-[#111] bg-[#FF4D8D] font-display text-[26px] font-extrabold text-[#111] ${PRESS_MOTION} shadow-[0_8px_0_#111]`;
const BIG_SECONDARY = `box-border h-[54px] w-full cursor-pointer rounded-[14px] border-[4px] border-[#111] bg-white font-display text-xl font-extrabold text-[#111] ${PRESS_MOTION}`;
const LINK =
  "cursor-pointer border-0 bg-transparent p-0 font-body text-[15px] font-extrabold text-[#111] underline decoration-[#FF4D8D] decoration-[4px] underline-offset-4";

function MoodSync({ mood }: { mood: AcademyMood }) {
  const setMood = useSetAcademyMood();
  useEffect(() => setMood(mood), [mood, setMood]);
  return null;
}

function Star({
  size,
  fill = "#FFE14D",
  className,
  style,
}: {
  size: number;
  fill?: string;
  className?: string;
  style?: CSSProperties;
}) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 100 100"
      width={size}
      height={size}
      className={cn("pointer-events-none absolute", className)}
      style={style}
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

/** A comic "POW" burst, no text. */
function Burst({
  size,
  fill = "#FFE14D",
  className,
  children,
}: {
  size: number;
  fill?: string;
  className?: string;
  children?: ReactNode;
}) {
  const points = Array.from({ length: 28 }, (_, i) => {
    const r = i % 2 ? 36 : 50;
    const a = (Math.PI * 2 * i) / 28;
    return `${50 + r * Math.cos(a)},${50 + r * Math.sin(a)}`;
  }).join(" ");
  return (
    <div
      className={cn("absolute grid place-items-center", className)}
      style={{ width: size, height: size }}
    >
      <svg
        aria-hidden="true"
        viewBox="0 0 100 100"
        className="absolute inset-0 size-full"
      >
        <polygon
          points={points}
          fill={fill}
          stroke="#111"
          strokeWidth="2.5"
          strokeLinejoin="round"
        />
      </svg>
      <div className="relative">{children}</div>
    </div>
  );
}

/** Little blue sweat drops for the refused pose. */
function Sweat({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn("pointer-events-none absolute flex gap-1", className)}
    >
      {[0, 1].map((i) => (
        <i
          key={i}
          className="block h-5 w-3.5 rounded-[50%_50%_50%_50%/60%_60%_40%_40%] border-[3px] border-[#111] bg-[#67E8F9]"
          style={{ transform: `rotate(${i ? 20 : -10}deg)` }}
        />
      ))}
    </span>
  );
}

/** "!" pop over a head when a field is being filled in. */
function Pop({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "pointer-events-none absolute grid size-9 place-items-center rounded-full border-[3px] border-[#111] bg-[#FFE14D] font-display text-xl font-extrabold shadow-[3px_3px_0_#111]",
        className,
      )}
    >
      !
    </span>
  );
}

function BrandDot({ className }: { className?: string }) {
  return (
    <span
      aria-hidden="true"
      className={cn(
        "inline-block shrink-0 rounded-full border-[4px] border-[#111] bg-[linear-gradient(90deg,#111_50%,#FF4D8D_50%)]",
        className,
      )}
    />
  );
}

function Field({
  label,
  type = "text",
  value,
  focus,
  hint,
}: {
  label: string;
  type?: string;
  value?: string;
  focus?: boolean;
  hint?: string;
}) {
  return (
    <label className="grid gap-1.5 font-body text-sm font-extrabold text-[#111]">
      <span>{label}</span>
      <input
        className={cn(INPUT, focus && FOCUS)}
        type={type}
        defaultValue={value}
        readOnly
      />
      {hint ? (
        <small className="font-body text-[13px] font-bold text-[#555]">
          {hint}
        </small>
      ) : null}
    </label>
  );
}

function GroupList({ t }: { t: T }) {
  return (
    <div className="relative">
      <Field label={t("registerGroupLabel")} value="第" focus />
      <div className="absolute top-full right-0 left-0 z-10 mt-2 overflow-hidden rounded-[12px] border-[4px] border-[#111] bg-white shadow-[6px_6px_0_#111]">
        <p className="m-0 border-b-[3px] border-dashed border-[#1114] px-3 py-1.5 font-body text-[11px] font-extrabold tracking-[.1em] text-[#555] uppercase">
          {t("registerSuggestions")}
        </p>
        {(
          [
            ["第一组", 4],
            ["第二组", 3],
          ] as const
        ).map(([name, count], index) => (
          <div
            key={name}
            className={cn(
              "flex items-center justify-between px-3 py-2.5 font-body text-base font-extrabold",
              index === 0 && "bg-[#FFE14D]",
            )}
          >
            {name}
            <span className="rounded-[6px] border-[3px] border-[#111] bg-white px-1.5 text-xs font-extrabold">
              {t("memberCountShort", { count })}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Fields and actions; the heading and frame belong to each scheme. */
function Fields({ state }: { state: State }) {
  const t = useT();
  if (state === "reg1")
    return (
      <>
        <Field label={t("username")} value="li_tongxue" focus />
        <Field label={t("password")} type="password" hint={t("passwordRule")} />
        <Field label={t("registerConfirmPassword")} type="password" />
        <button type="button" className={BIG_PRIMARY}>
          {t("registerNext")}
        </button>
        <p className="m-0 text-center font-body text-[15px] font-bold">
          {t("haveAccount")}{" "}
          <button type="button" className={LINK}>
            {t("signIn")}
          </button>
        </p>
      </>
    );
  if (state === "reg2")
    return (
      <>
        <GroupList t={t} />
        <div className="h-[118px]" aria-hidden="true" />
        <button type="button" className={BIG_PRIMARY}>
          {t("registerSubmit")}
        </button>
        <button type="button" className={BIG_SECONDARY}>
          {t("registerBack")}
        </button>
      </>
    );
  return (
    <>
      {state === "error" ? (
        <DismissibleAlert className="form-error" resetKey="mock">
          {t("loginFailed")}
        </DismissibleAlert>
      ) : null}
      <Field
        label={t("username")}
        value={state === "login" ? "" : "li_tongxue"}
        focus={state === "user"}
      />
      <Field
        label={t("password")}
        type="password"
        value={state === "pw" || state === "error" ? "secret" : ""}
        focus={state === "pw" || state === "error"}
      />
      <button type="button" className={BIG_PRIMARY}>
        {t("signIn")}
      </button>
      <p className="m-0 text-center font-body text-[15px] font-bold">
        {t("needAccount")}{" "}
        <button type="button" className={LINK}>
          {t("needAccountLink")}
        </button>
      </p>
    </>
  );
}

function useCopy(state: State) {
  const t = useT();
  const register = state === "reg1" || state === "reg2";
  const current = state === "reg2" ? 2 : 1;
  return {
    t,
    register,
    current,
    title: register ? t("registerTitle") : t("academyWelcome"),
    step: register
      ? `${t("registerStepOf", { current, total: 2 })} · ${
          current === 1 ? t("registerStepAccount") : t("registerStepGroup")
        }`
      : null,
  };
}

/** Per-mascot pose for the reacting schemes (jump / turn away / shake). */
function pose(state: State, index: number): CSSProperties {
  const mood = MOOD[state];
  if (mood === "attentive")
    return {
      transform: `translateY(${index % 2 ? -34 : -18}px) rotate(${6 + index * 2}deg)`,
    };
  if (mood === "discreet")
    return { transform: `scaleX(-1) rotate(${index % 2 ? 4 : -4}deg)` };
  if (mood === "refused")
    return {
      transform: `rotate(${index % 2 ? 9 : -9}deg) translateX(${index % 2 ? 6 : -6}px)`,
    };
  return { transform: `rotate(${index % 2 ? 2 : -2}deg)` };
}

function Steps({ current, step }: { current: number; step: string }) {
  return (
    <div className="grid gap-2">
      <div className="flex items-center gap-2" aria-hidden="true">
        {[1, 2].map((n) => (
          <span key={n} className="contents">
            {n === 2 ? (
              <i className="block h-1 flex-1 bg-[repeating-linear-gradient(90deg,#111_0_12px,transparent_12px_20px)]" />
            ) : null}
            <span
              className={cn(
                "grid size-11 place-items-center rounded-full border-[4px] border-[#111] font-display text-xl font-extrabold shadow-[3px_3px_0_#111]",
                n < current
                  ? "bg-[#A3E635]"
                  : n === current
                    ? "bg-[#FF4D8D]"
                    : "bg-white",
              )}
            >
              {n}
            </span>
          </span>
        ))}
      </div>
      <p className="m-0 font-body text-sm font-extrabold tracking-[.04em]">
        {step}
      </p>
    </div>
  );
}

/* ── 1 · Title Screen MAX (#1 pushed further) ──────────────────── */

function SchemeOne({ state, mobile }: { state: State; mobile: boolean }) {
  const { t, title, step, current } = useCopy(state);
  const mood = MOOD[state];
  return (
    <main
      className="relative min-h-screen overflow-hidden bg-[#FFF7CC]"
      style={{
        backgroundImage:
          "repeating-conic-gradient(from 0deg at 30% 78%,#FFE14D 0 7deg,#FFF7CC 7deg 14deg)",
      }}
    >
      {/* pink halftone only in the corners */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(#FF4D8D_2.4px,transparent_2.9px)] bg-[length:18px_18px] [mask-image:radial-gradient(circle_at_100%_0%,#000_0_18%,transparent_34%),radial-gradient(circle_at_0%_0%,#000_0_10%,transparent_22%)]"
      />
      <div
        aria-hidden="true"
        className="absolute right-0 bottom-0 left-0 h-[120px] border-t-[8px] border-[#111] bg-[#A3E635] bg-[repeating-linear-gradient(90deg,#0000_0_40px,#0001_40px_80px)] max-[767px]:top-[350px] max-[767px]:bottom-auto max-[767px]:h-[70px]"
      />
      <div className="relative mx-auto grid min-h-screen max-w-[1440px] grid-cols-[1.15fr_1fr] max-[767px]:grid-cols-1">
        <section className="relative max-[767px]:h-[420px]">
          <p className="absolute top-12 left-16 m-0 -rotate-3 border-[4px] border-[#111] bg-white bg-[linear-gradient(90deg,#A3E635_0_12px,transparent_12px_calc(100%-12px),#A3E635_calc(100%-12px))] px-5 py-1 font-body text-[15px] font-extrabold tracking-[.16em] shadow-[5px_5px_0_#111] max-[767px]:top-5 max-[767px]:left-4 max-[767px]:text-[10px]">
            {t("academyEyebrow")}
          </p>
          <div className="absolute top-[118px] left-12 max-[767px]:top-16 max-[767px]:left-3">
            <h1 className="relative m-0 -rotate-[6deg] rounded-[24px] border-[5px] border-[#111] bg-[#FF4D8D] py-2 pr-14 pl-8 font-display text-[132px] leading-none font-extrabold text-white shadow-[12px_12px_0_#111] [-webkit-text-stroke:5px_#111] [paint-order:stroke_fill] after:absolute after:top-1/2 after:-right-[10px] after:-translate-y-1/2 after:border-y-[22px] after:border-l-[34px] after:border-y-transparent after:border-l-[#111] after:content-[''] max-[767px]:pr-9 max-[767px]:pl-5 max-[767px]:text-[62px] max-[767px]:shadow-[7px_7px_0_#111] max-[767px]:[-webkit-text-stroke:3px_#111]">
              {t("appName")}
            </h1>
            <Star
              size={mobile ? 48 : 104}
              className="-top-16 -right-16 z-10 rotate-12 max-[767px]:-top-8 max-[767px]:-right-6"
            />
            <Star
              size={mobile ? 34 : 64}
              fill="#67E8F9"
              className="-bottom-16 left-10 z-10 -rotate-12 max-[767px]:-bottom-9"
            />
            <Star
              size={mobile ? 26 : 46}
              fill="#A3E635"
              className="-top-10 left-[40%] z-10 rotate-6 max-[767px]:-top-6"
            />
          </div>
          <div className="absolute right-4 bottom-[96px] left-4 flex items-end justify-center gap-0 max-[767px]:bottom-[56px]">
            {CAST.map((id, index) => (
              <div
                key={id}
                className="relative -mx-5 transition-transform max-[767px]:-mx-[22px]"
                style={pose(state, index)}
              >
                {mood === "attentive" && index % 2 ? (
                  <Pop className="-top-4 left-1/2" />
                ) : null}
                {mood === "refused" && index === 3 ? (
                  <Sweat className="top-2 -left-2" />
                ) : null}
                <MascotFigure
                  id={id}
                  mood={mood}
                  className={cn(
                    "w-auto drop-shadow-[6px_6px_0_#1113]",
                    index === 3 ? "h-[240px]" : "h-[200px]",
                    "max-[767px]:h-[100px]",
                  )}
                />
              </div>
            ))}
          </div>
        </section>
        <section className="relative flex items-center justify-center px-12 py-14 max-[767px]:px-4 max-[767px]:pt-4 max-[767px]:pb-10">
          <div className="relative w-full max-w-[470px] rotate-[2deg] rounded-[24px] border-[5px] border-[#111] bg-white px-9 pt-[92px] pb-9 shadow-[14px_14px_0_#111] max-[767px]:rotate-0 max-[767px]:px-5 max-[767px]:pt-20">
            <span
              aria-hidden="true"
              className="absolute -top-4 left-10 h-8 w-28 -rotate-6 border-[3px] border-[#111] bg-[#67E8F9cc]"
            />
            <span
              aria-hidden="true"
              className="absolute -top-4 right-10 h-8 w-28 rotate-6 border-[3px] border-[#111] bg-[#FFE14Dcc]"
            />
            {/* the heading as the cast's speech bubble */}
            <div className="absolute -top-14 -left-14 max-[767px]:-top-10 max-[767px]:-left-1">
              <div className="relative -rotate-[5deg] rounded-[28px] border-[5px] border-[#111] bg-[#FFE14D] px-7 py-3 shadow-[8px_8px_0_#111] after:absolute after:-bottom-[26px] after:left-10 after:h-0 after:w-0 after:border-t-[26px] after:border-r-[26px] after:border-t-[#111] after:border-r-transparent after:content-['']">
                <h2 className="m-0 font-display text-[46px] leading-none font-extrabold whitespace-nowrap max-[767px]:text-[32px]">
                  {title}
                </h2>
              </div>
            </div>
            <div className="grid gap-4">
              {step ? <Steps current={current} step={step} /> : null}
              <Fields state={state} />
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

/* ── 2 · Character Select ─────────────────────────────────────── */

const SELECT = [
  { id: "scroll", bg: "#C4B5FD" },
  { id: "wreath", bg: "#FFB4C8" },
  { id: "tablet", bg: "#A3E635" },
  { id: "wave", bg: "#FFE14D" },
] as const;

function SchemeTwo({ state, mobile }: { state: State; mobile: boolean }) {
  const { t, title, step, current, register } = useCopy(state);
  const mood = MOOD[state];
  const picked = register ? current : 1;
  return (
    <main
      className="relative min-h-screen overflow-hidden bg-[#67E8F9]"
      style={{
        backgroundImage:
          "repeating-linear-gradient(-35deg,#A5F3FC 0 46px,#67E8F9 46px 92px)",
      }}
    >
      <div className="relative mx-auto flex min-h-screen max-w-[1440px] items-center gap-12 px-14 max-[767px]:flex-col max-[767px]:gap-6 max-[767px]:px-4 max-[767px]:py-6">
        <section className="relative flex-1">
          <div className="mb-8 flex items-center gap-4 max-[767px]:mb-4">
            <h1 className="m-0 flex -rotate-3 items-center gap-4 rounded-[20px] border-[5px] border-[#111] bg-white px-7 py-2 font-display text-[84px] leading-none font-extrabold shadow-[10px_10px_0_#FF4D8D,10px_10px_0_5px_#111] max-[767px]:text-[46px]">
              <BrandDot className="size-14 max-[767px]:size-9" />
              {t("appName")}
            </h1>
          </div>
          <p className="m-0 mb-6 w-max rotate-2 rounded-[10px] border-[4px] border-[#111] bg-[#FFE14D] px-4 py-1 font-body text-sm font-extrabold tracking-[.16em] shadow-[4px_4px_0_#111] max-[767px]:mb-3 max-[767px]:text-[10px]">
            {t("academyEyebrow")}
          </p>
          <div className="relative flex h-[440px] items-end max-[767px]:h-[210px]">
            {SELECT.map((card, index) => {
              const hidden = mood === "discreet";
              const chosen = index === picked && mood !== "discreet";
              const tilt = [-8, -3, 3, 8][index];
              const shake = mood === "refused" ? (index % 2 ? 10 : -10) : 0;
              return (
                <div
                  key={card.id}
                  className={cn(
                    "relative -ml-6 w-[210px] shrink-0 first:ml-0 max-[767px]:-ml-4 max-[767px]:w-[100px]",
                    chosen && "z-10",
                  )}
                  style={{
                    transform: `rotate(${tilt + shake}deg) translateY(${chosen ? -46 : index % 2 ? 10 : 22}px) scale(${chosen ? 1.1 : 1})`,
                  }}
                >
                  {chosen ? (
                    <span
                      aria-hidden="true"
                      className="absolute -top-16 left-1/2 h-0 w-0 -translate-x-1/2 border-x-[22px] border-t-[30px] border-x-transparent border-t-[#FF4D8D] drop-shadow-[3px_3px_0_#111] max-[767px]:-top-9 max-[767px]:border-x-[12px] max-[767px]:border-t-[16px]"
                    />
                  ) : null}
                  <div
                    className={cn(
                      "relative h-[340px] overflow-hidden rounded-[22px] border-[5px] border-[#111] shadow-[8px_8px_0_#111] max-[767px]:h-[160px] max-[767px]:rounded-[14px] max-[767px]:border-[3px]",
                      chosen &&
                        "outline-[6px] outline-offset-[4px] outline-[#FF4D8D]",
                    )}
                    style={{
                      backgroundColor: hidden ? "#FF4D8D" : card.bg,
                      backgroundImage: hidden
                        ? "radial-gradient(circle,#FFE14D 0 9px,transparent 10px),radial-gradient(circle,#ffffff 0 6px,transparent 7px)"
                        : "repeating-conic-gradient(from 0deg at 50% 70%,#ffffff66 0 9deg,transparent 9deg 18deg)",
                      backgroundSize: hidden ? "44px 44px" : undefined,
                      backgroundPosition: hidden ? "0 0,22px 22px" : undefined,
                    }}
                  >
                    {hidden ? null : (
                      <>
                        <MascotFigure
                          id={card.id}
                          mood={mood}
                          className="absolute bottom-[-6px] left-1/2 h-[300px] w-auto -translate-x-1/2 max-[767px]:h-[140px]"
                        />
                        {mood === "refused" && index === 1 ? (
                          <Sweat className="top-6 right-6" />
                        ) : null}
                      </>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
        <section className="relative w-[480px] max-w-full shrink-0">
          <Burst
            size={mobile ? 0 : 170}
            fill="#FF4D8D"
            className="-top-16 -right-14 rotate-12 max-[767px]:hidden"
          />
          <div className="relative overflow-hidden rounded-[24px] border-[5px] border-[#111] bg-white shadow-[14px_14px_0_#111]">
            <div className="flex items-center gap-3 border-b-[5px] border-[#111] bg-[#FFE14D] px-7 py-4">
              <h2 className="m-0 font-display text-[40px] leading-none font-extrabold max-[767px]:text-[30px]">
                {title}
              </h2>
            </div>
            <div className="grid gap-4 px-7 pt-6 pb-8 max-[767px]:px-5">
              {step ? <Steps current={current} step={step} /> : null}
              <Fields state={state} />
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

/* ── 3 · Comic Pop ────────────────────────────────────────────── */

function SchemeThree({ state }: { state: State }) {
  const { t, title, step, current } = useCopy(state);
  const mood = MOOD[state];
  const sad = mood === "refused";
  return (
    <main
      className="relative min-h-screen overflow-hidden bg-[#FF4D8D]"
      style={{
        backgroundImage: "radial-gradient(#ffffff55 3px,transparent 3.5px)",
        backgroundSize: "22px 22px",
      }}
    >
      <MoodSync mood={mood} />
      <div className="relative mx-auto grid min-h-screen max-w-[1440px] grid-cols-[1.2fr_1fr] gap-7 p-9 max-[767px]:grid-cols-1 max-[767px]:gap-5 max-[767px]:p-4">
        {/* panel 1: the cast */}
        <section
          className="relative min-h-[600px] -skew-x-2 overflow-hidden rounded-[10px] border-[6px] border-[#111] shadow-[12px_12px_0_#111] max-[767px]:min-h-[420px] max-[767px]:skew-x-0"
          style={{
            backgroundColor: sad ? "#C9D3F0" : "#FFE14D",
            backgroundImage: sad
              ? "repeating-linear-gradient(180deg,#ffffff55 0 3px,transparent 3px 26px)"
              : "repeating-conic-gradient(from 0deg at 50% 62%,#FFF7CC 0 6deg,transparent 6deg 12deg)",
          }}
        >
          <div className="absolute top-6 left-7 skew-x-2 max-[767px]:top-4 max-[767px]:left-4">
            <Burst
              size={330}
              fill="#FFFFFF"
              className="-top-24 -left-24 max-[767px]:hidden"
            />
            <div className="relative">
              <p className="m-0 mb-2 font-body text-[15px] font-extrabold tracking-[.16em] max-[767px]:text-[10px]">
                {t("academyEyebrow")}
              </p>
              <h1 className="m-0 -rotate-3 font-display text-[110px] leading-[.9] font-extrabold text-[#FF4D8D] [-webkit-text-stroke:5px_#111] [paint-order:stroke_fill] [text-shadow:8px_8px_0_#111] max-[767px]:text-[60px] max-[767px]:[-webkit-text-stroke:3px_#111] max-[767px]:[text-shadow:5px_5px_0_#111]">
                {t("appName")}
              </h1>
            </div>
          </div>
          {/* speed lines toward the form while a field is filled in */}
          {mood === "attentive" ? (
            <div
              aria-hidden="true"
              className="absolute inset-y-0 right-0 w-1/2 bg-[repeating-linear-gradient(0deg,transparent_0_22px,#1112_22px_26px)]"
            />
          ) : null}
          <div className="absolute right-[-4%] bottom-0 left-[-4%] h-[64%] skew-x-2 [&_.academy-mascots]:bottom-[-6px] [&_.academy-mascots]:w-full max-[767px]:h-[56%]">
            <AcademyMascots label={t("academyMascotsLabel")} />
          </div>
          {mood === "attentive" ? (
            <>
              <Pop className="top-[38%] left-[22%]" />
              <Pop className="top-[34%] left-[64%]" />
            </>
          ) : null}
          {sad ? (
            <>
              <Sweat className="top-[70%] left-[25%]" />
              <Sweat className="top-[66%] left-[78%]" />
            </>
          ) : null}
          {mood === "discreet" ? (
            <span
              aria-hidden="true"
              className="absolute top-[30%] right-10 font-display text-5xl font-extrabold"
            >
              ···
            </span>
          ) : null}
        </section>
        {/* panel 2: the form */}
        <section className="relative flex items-center">
          <div className="relative w-full skew-x-1 rounded-[10px] border-[6px] border-[#111] bg-white px-9 pt-28 pb-9 shadow-[12px_12px_0_#111] max-[767px]:skew-x-0 max-[767px]:px-5 max-[767px]:pt-24">
            <div className="absolute -top-10 -left-16 -skew-x-1 max-[767px]:-top-6 max-[767px]:-left-1">
              <div className="relative rounded-[50%] border-[5px] border-[#111] bg-white px-10 py-6 shadow-[8px_8px_0_#111] after:absolute after:top-[70%] after:-left-[34px] after:h-0 after:w-0 after:border-y-[14px] after:border-r-[40px] after:border-y-transparent after:border-r-[#111] after:content-['']">
                <h2 className="m-0 font-display text-[42px] leading-none font-extrabold whitespace-nowrap max-[767px]:text-[30px]">
                  {title}
                </h2>
              </div>
            </div>
            <div className="grid gap-4 -skew-x-1 max-[767px]:skew-x-0">
              {step ? <Steps current={current} step={step} /> : null}
              <Fields state={state} />
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

/* ── 4 · Title Screen MAX + character cards (2) + comic beats (3) ── */

function SchemeFour({ state, mobile }: { state: State; mobile: boolean }) {
  const { t, title, step, current, register } = useCopy(state);
  const mood = MOOD[state];
  const hidden = mood === "discreet";
  const sad = mood === "refused";
  const typing = mood === "attentive";
  const picked = register ? current : 1;
  return (
    <main
      className="relative min-h-screen overflow-hidden bg-[#FFF7CC]"
      style={{
        backgroundImage:
          "repeating-conic-gradient(from 0deg at 30% 78%,#FFE14D 0 7deg,#FFF7CC 7deg 14deg)",
      }}
    >
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(#FF4D8D_2.4px,transparent_2.9px)] bg-[length:18px_18px] [mask-image:radial-gradient(circle_at_100%_0%,#000_0_18%,transparent_34%),radial-gradient(circle_at_0%_0%,#000_0_10%,transparent_22%)]"
      />
      {/* 3's "gloomy panel": the scene turns grey-blue rain on a refusal */}
      {sad ? (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 bg-[#C9D3F0d9] bg-[repeating-linear-gradient(100deg,transparent_0_26px,#ffffff88_26px_29px)]"
        />
      ) : null}
      <div
        aria-hidden="true"
        className="absolute right-0 bottom-0 left-0 h-[110px] border-t-[8px] border-[#111] bg-[#A3E635] bg-[repeating-linear-gradient(90deg,#0000_0_40px,#0001_40px_80px)] max-[767px]:top-[392px] max-[767px]:bottom-auto max-[767px]:h-[64px]"
      />
      {/* 3's speed lines: the cast rushing towards the field being filled */}
      {typing ? (
        <div
          aria-hidden="true"
          className="pointer-events-none absolute top-[30%] left-[44%] h-[34%] w-[16%] bg-[repeating-linear-gradient(0deg,transparent_0_18px,#111_18px_22px)] [mask-image:linear-gradient(90deg,transparent,#000_40%,#000_70%,transparent)] max-[767px]:hidden"
        />
      ) : null}
      <div className="relative mx-auto grid min-h-screen max-w-[1440px] grid-cols-[1.15fr_1fr] max-[767px]:grid-cols-1">
        <section className="relative max-[767px]:h-[456px]">
          <p className="absolute top-12 left-16 z-[2] m-0 -rotate-3 border-[4px] border-[#111] bg-white bg-[linear-gradient(90deg,#A3E635_0_12px,transparent_12px_calc(100%-12px),#A3E635_calc(100%-12px))] px-5 py-1 font-body text-[15px] font-extrabold tracking-[.16em] shadow-[5px_5px_0_#111] max-[767px]:top-5 max-[767px]:left-4 max-[767px]:text-[10px]">
            {t("academyEyebrow")}
          </p>
          <div className="absolute top-[118px] left-12 max-[767px]:top-16 max-[767px]:left-3">
            {/* 3's comic burst behind the nameplate */}
            <Burst
              size={mobile ? 0 : 280}
              fill="#FFFFFF"
              className="-top-24 left-[-30px] -rotate-6 max-[767px]:hidden"
            />
            <h1 className="relative m-0 -rotate-[6deg] rounded-[24px] border-[5px] border-[#111] bg-[#FF4D8D] py-2 pr-14 pl-8 font-display text-[124px] leading-none font-extrabold text-white shadow-[12px_12px_0_#111] [-webkit-text-stroke:5px_#111] [paint-order:stroke_fill] after:absolute after:top-1/2 after:-right-[10px] after:-translate-y-1/2 after:border-y-[22px] after:border-l-[34px] after:border-y-transparent after:border-l-[#111] after:content-[''] max-[767px]:pr-9 max-[767px]:pl-5 max-[767px]:text-[62px] max-[767px]:shadow-[7px_7px_0_#111] max-[767px]:[-webkit-text-stroke:3px_#111]">
              {t("appName")}
            </h1>
            <Star
              size={mobile ? 48 : 104}
              className="-top-16 -right-16 z-10 rotate-12 max-[767px]:-top-8 max-[767px]:-right-6"
            />
            <Star
              size={mobile ? 34 : 64}
              fill="#67E8F9"
              className="-bottom-16 left-10 z-10 -rotate-12 max-[767px]:-bottom-9"
            />
            <Star
              size={mobile ? 26 : 46}
              fill="#A3E635"
              className="-top-10 left-[40%] z-10 rotate-6 max-[767px]:-top-6"
            />
          </div>
          {/* 2's character cards, standing on the stage */}
          <div className="absolute right-4 bottom-[88px] left-6 flex items-end justify-center max-[767px]:right-2 max-[767px]:bottom-auto max-[767px]:left-2 max-[767px]:top-[226px]">
            {SELECT.map((card, index) => {
              const chosen = index === picked && !hidden && !sad;
              const tilt = [-7, -2, 3, 8][index];
              const shake = sad ? (index % 2 ? 12 : -12) : 0;
              return (
                <div
                  key={card.id}
                  className={cn(
                    "relative -ml-5 w-[172px] shrink-0 first:ml-0 max-[767px]:-ml-3 max-[767px]:w-[92px]",
                    chosen && "z-10",
                  )}
                  style={{
                    transform: `rotate(${tilt + shake}deg) translateY(${chosen ? -44 : sad ? 14 : index % 2 ? 0 : 10}px) scale(${chosen ? 1.1 : 1})`,
                  }}
                >
                  {chosen ? (
                    <>
                      <span
                        aria-hidden="true"
                        className="absolute -top-14 left-1/2 z-[2] h-0 w-0 -translate-x-1/2 border-x-[20px] border-t-[28px] border-x-transparent border-t-[#FF4D8D] drop-shadow-[3px_3px_0_#111] max-[767px]:-top-8 max-[767px]:border-x-[11px] max-[767px]:border-t-[15px]"
                      />
                      {typing ? (
                        <Pop className="-top-6 -right-3 z-[3]" />
                      ) : null}
                    </>
                  ) : null}
                  {sad && index % 2 ? (
                    <Sweat className="-top-7 left-6 z-[3]" />
                  ) : null}
                  <div
                    className={cn(
                      "relative h-[270px] overflow-hidden rounded-[20px] border-[5px] border-[#111] shadow-[7px_7px_0_#111] max-[767px]:h-[150px] max-[767px]:rounded-[12px] max-[767px]:border-[3px]",
                      chosen &&
                        "outline-[6px] outline-offset-[3px] outline-[#FF4D8D] max-[767px]:outline-[4px]",
                    )}
                    style={{
                      backgroundColor: hidden
                        ? "#FF4D8D"
                        : sad
                          ? "#C9D3F0"
                          : card.bg,
                      backgroundImage: hidden
                        ? "radial-gradient(circle,#FFE14D 0 8px,transparent 9px),radial-gradient(circle,#ffffff 0 5px,transparent 6px)"
                        : "repeating-conic-gradient(from 0deg at 50% 72%,#ffffff66 0 9deg,transparent 9deg 18deg)",
                      backgroundSize: hidden ? "38px 38px" : undefined,
                      backgroundPosition: hidden ? "0 0,19px 19px" : undefined,
                    }}
                  >
                    {hidden ? (
                      <BrandDot className="absolute top-1/2 left-1/2 size-14 -translate-x-1/2 -translate-y-1/2 max-[767px]:size-8" />
                    ) : (
                      <MascotFigure
                        id={card.id}
                        mood={mood}
                        className="absolute bottom-[-6px] left-1/2 h-[236px] w-auto -translate-x-1/2 max-[767px]:h-[128px]"
                      />
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
        <section className="relative flex items-center justify-center px-12 py-14 max-[767px]:px-4 max-[767px]:pt-4 max-[767px]:pb-10">
          <div className="relative w-full max-w-[470px]">
            {/* 2's pink burst peeking out behind the card */}
            <Burst
              size={mobile ? 0 : 160}
              fill="#FF4D8D"
              className="-right-14 -bottom-14 rotate-12 max-[767px]:hidden"
            />
            <div className="relative rotate-[2deg] rounded-[24px] border-[5px] border-[#111] bg-white px-9 pt-[92px] pb-9 shadow-[14px_14px_0_#111] max-[767px]:rotate-0 max-[767px]:px-5 max-[767px]:pt-20">
              <span
                aria-hidden="true"
                className="absolute -top-4 left-10 h-8 w-28 -rotate-6 border-[3px] border-[#111] bg-[#67E8F9cc]"
              />
              <span
                aria-hidden="true"
                className="absolute -top-4 right-10 h-8 w-28 rotate-6 border-[3px] border-[#111] bg-[#FFE14Dcc]"
              />
              <div className="absolute -top-14 -left-14 max-[767px]:-top-10 max-[767px]:-left-1">
                <div className="relative -rotate-[5deg] rounded-[28px] border-[5px] border-[#111] bg-[#FFE14D] px-7 py-3 shadow-[8px_8px_0_#111] after:absolute after:-bottom-[26px] after:left-10 after:h-0 after:w-0 after:border-t-[26px] after:border-r-[26px] after:border-t-[#111] after:border-r-transparent after:content-['']">
                  <h2 className="m-0 font-display text-[46px] leading-none font-extrabold whitespace-nowrap max-[767px]:text-[32px]">
                    {title}
                  </h2>
                </div>
              </div>
              <div className="grid gap-4">
                {step ? <Steps current={current} step={step} /> : null}
                <Fields state={state} />
              </div>
            </div>
          </div>
        </section>
      </div>
    </main>
  );
}

function Proposals() {
  const params = useSearchParams();
  const scheme = params.get("s") ?? "1";
  const state = (params.get("state") ?? "login") as State;
  const mobile = params.get("m") === "1";
  return (
    <AcademyMoodProvider>
      {scheme === "4" ? (
        <SchemeFour state={state} mobile={mobile} />
      ) : scheme === "2" ? (
        <SchemeTwo state={state} mobile={mobile} />
      ) : scheme === "3" ? (
        <SchemeThree state={state} />
      ) : (
        <SchemeOne state={state} mobile={mobile} />
      )}
    </AcademyMoodProvider>
  );
}

export default function AuthProposalsPage() {
  return (
    <Suspense>
      <Proposals />
    </Suspense>
  );
}
