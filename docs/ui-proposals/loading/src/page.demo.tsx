"use client";

/*
 * Proposal 39 · loading (design only). Three schemes, each shown where the
 * product waits: a whole page, a page's content area inside the shell, and a
 * small panel. /loading-proposals?s=A|B|C&room=page|content|inline
 */

import { Suspense, type CSSProperties } from "react";
import { useSearchParams } from "next/navigation";

import { AppShell } from "../../components/app-shell";
import { MascotFigure, type MascotId } from "../../components/academy/mascots";

type Room = "page" | "content" | "inline";
const CAST: { id: MascotId; bg: string }[] = [
  { id: "scroll", bg: "#C4B5FD" },
  { id: "wreath", bg: "#FFB4C8" },
  { id: "tablet", bg: "#A3E635" },
  { id: "wave", bg: "#FFE14D" },
];

const KEYFRAMES = `
@keyframes p39-hop { 0%,55%,100%{transform:translateY(0) scale(1,1)} 12%{transform:translateY(0) scale(1.08,.9)} 30%{transform:translateY(-22%) scale(.94,1.06)} 46%{transform:translateY(0) scale(1.06,.92)} }
@keyframes p39-stripes { to { background-position: 45.2px 0 } }
@keyframes p39-run { from { transform: translateX(-110%) } to { transform: translateX(110%) } }
@keyframes p39-ground { to { background-position: -64px 0 } }
@keyframes p39-blink { 50% { opacity: .25 } }
@keyframes p39-flip { 0%,18% { transform: rotateY(0) translateY(0) } 28%,72% { transform: rotateY(180deg) translateY(-14%) } 82%,100% { transform: rotateY(360deg) translateY(0) } }
@keyframes p39-bob { 50% { transform: translateY(-6px) rotate(-2deg) } }
@media (max-width: 600px) {
  [data-room="page"] svg[data-mascot], [data-room="content"] svg[data-mascot] { height: 78px !important }
  [data-room="page"] [data-a-bubble], [data-room="content"] [data-a-bubble] { font-size: 20px !important; padding: 4px 12px !important; right: 0 !important; top: -58% !important }
  [data-room="page"] [data-c-row], [data-room="content"] [data-c-row] { gap: 8px !important }
  [data-room="page"] [data-c-card], [data-room="content"] [data-c-card] { width: 72px !important; height: 102px !important }
  [data-room="page"] [data-c-card] svg[data-mascot], [data-room="content"] [data-c-card] svg[data-mascot] { height: 88% !important }
  [data-room="page"] [data-c-label], [data-room="content"] [data-c-label] { font-size: 20px !important; padding: 4px 14px !important }
}
@media (max-width: 600px) { [data-room="page"] [data-console], [data-room="content"] [data-console] { zoom: .66 !important } }
@keyframes p39-dot { 0%,100% { background:#fff } 40%,60% { background:#FF4D8D } }
`;

function Star({ className, fill }: { className: string; fill: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={`absolute ${className}`}
      aria-hidden="true"
    >
      <path
        d="M12 1l3 7.5 8 .8-6 5.4 1.8 8L12 18.6 5.2 22.7 7 14.7 1 9.3l8-.8z"
        fill={fill}
        stroke="#111"
        strokeWidth="1.8"
        strokeLinejoin="round"
      />
    </svg>
  );
}

const SIZES: Record<Room, { cast: number; stage: number; font: number }> = {
  page: { cast: 190, stage: 420, font: 44 },
  content: { cast: 160, stage: 360, font: 38 },
  inline: { cast: 70, stage: 150, font: 18 },
};

/* ── A · Stage Show: the sign-in stage, big, the cast hopping in turn ── */
function SchemeA({ room }: { room: Room }) {
  const z = SIZES[room];
  const inline = room === "inline";
  return (
    <div
      role="status"
      className={`relative w-full overflow-hidden border-[#111] bg-[#FFF7CC] text-[#111] ${room === "page" ? "h-screen" : `rounded-[22px] border-[4px] shadow-[8px_8px_0_#111] ${room === "content" ? "h-[calc(100vh-120px)] min-h-[520px]" : ""}`}`}
      style={{
        backgroundImage:
          "repeating-conic-gradient(from 0deg at 50% 92%,#FFE14D 0 7deg,transparent 7deg 14deg)",
        height: inline ? z.stage + 64 : undefined,
      }}
    >
      <Star
        className="top-[8%] left-[10%] size-[7%] max-w-16 rotate-12"
        fill="#FFE14D"
      />
      <Star
        className="top-[14%] right-[12%] size-[5%] max-w-12 -rotate-12"
        fill="#67E8F9"
      />
      <Star className="top-[30%] left-[24%] size-[3%] max-w-8" fill="#FF4D8D" />
      <Star
        className="top-[26%] right-[28%] size-[3%] max-w-8"
        fill="#A3E635"
      />
      <div
        className={`absolute inset-x-0 bottom-0 border-t-[5px] border-[#111] bg-[#A3E635] bg-[repeating-linear-gradient(90deg,#0000_0_40px,#0001_40px_80px)] ${inline ? "h-[58px] border-t-[3px]" : "h-[24%]"}`}
      />
      <div
        className="absolute inset-x-0 flex items-end justify-center"
        style={{ bottom: inline ? 46 : "21%", gap: inline ? 2 : 18 }}
      >
        {CAST.map((cast, index) => (
          <span
            key={cast.id}
            className="relative origin-bottom"
            style={{
              animation: `p39-hop 1.1s ${index * 0.14}s infinite cubic-bezier(.3,.7,.4,1)`,
            }}
          >
            {index === 3 && !inline ? (
              <span
                data-a-bubble=""
                className="absolute -top-[46%] -right-[30%] -rotate-6 rounded-[22px] border-[4px] border-[#111] bg-white px-5 py-2 font-display font-extrabold whitespace-nowrap shadow-[6px_6px_0_#111] after:absolute after:-bottom-[18px] after:left-6 after:border-t-[18px] after:border-r-[18px] after:border-t-[#111] after:border-r-transparent after:content-['']"
                style={{ fontSize: z.font }}
              >
                Loading…
              </span>
            ) : null}
            <MascotFigure
              id={cast.id}
              className="w-auto drop-shadow-[5px_5px_0_#1112]"
            />
            <style>{`[data-room="${room}"] svg[data-mascot]{height:${z.cast}px}`}</style>
          </span>
        ))}
      </div>
      <div
        className={`absolute left-1/2 -translate-x-1/2 ${inline ? "bottom-3 w-[80%]" : "bottom-[7%] w-[46%]"}`}
      >
        <div className="flex items-center gap-3">
          {inline ? (
            <span className="-rotate-2 rounded-[8px] border-[3px] border-[#111] bg-[#FFE14D] px-2 py-0.5 font-body text-xs font-extrabold shadow-[2px_2px_0_#111]">
              Loading…
            </span>
          ) : null}
          <span
            className={`block flex-1 rounded-full border-[#111] bg-[repeating-linear-gradient(-45deg,#FF4D8D_0_16px,#FFE14D_16px_32px)] ${inline ? "h-4 border-[3px]" : "h-7 border-[4px] shadow-[4px_4px_0_#111]"}`}
            style={{
              backgroundSize: "45.2px 45.2px",
              animation: "p39-stripes .8s linear infinite",
            }}
          />
        </div>
      </div>
    </div>
  );
}

/* ── B · Handheld: a pink game console whose screen runs the cast across ── */
function SchemeB({ room }: { room: Room }) {
  const inline = room === "inline";
  const scale = room === "page" ? 1.25 : room === "content" ? 1.05 : 0.48;
  const console_ = (
    <div
      data-console=""
      className="relative mx-auto w-[520px] rounded-[40px_40px_80px_40px] border-[5px] border-[#111] bg-[#FF4D8D] p-7 pb-10 shadow-[12px_12px_0_#111]"
      style={{ zoom: scale } as CSSProperties}
    >
      <div className="mb-3 flex items-center gap-2">
        <span
          className="size-3 rounded-full border-2 border-[#111] bg-[#A3E635]"
          style={{ animation: "p39-blink 1s steps(2) infinite" }}
        />
        <span className="font-body text-xs font-extrabold tracking-[.2em] text-[#111]">
          MAYAFORM
        </span>
      </div>
      <div className="relative h-[250px] overflow-hidden rounded-[16px] border-[5px] border-[#111] bg-[#E9F7C5] bg-[linear-gradient(#0000000d_1px,transparent_1px),linear-gradient(90deg,#0000000d_1px,transparent_1px)] bg-size-[16px_16px] shadow-[inset_0_0_0_4px_#c7df8f]">
        <span
          className="absolute top-4 left-1/2 -translate-x-1/2 font-[family-name:var(--font-space-mono)] text-[30px] font-bold text-[#111]"
          style={{ animation: "p39-blink 1.2s steps(2) infinite" }}
        >
          LOADING…
        </span>
        <Star className="top-16 left-8 size-7" fill="#FFE14D" />
        <Star className="top-20 right-10 size-5" fill="#67E8F9" />
        <div
          className="absolute inset-x-0 bottom-0 h-10 border-t-[4px] border-[#111] bg-[#A3E635] bg-[repeating-linear-gradient(90deg,#111_0_6px,transparent_6px_32px)] bg-size-[64px_100%]"
          style={{ animation: "p39-ground .5s linear infinite" }}
        />
        <div
          className="absolute inset-x-0 bottom-9 flex items-end justify-center gap-2"
          style={{ animation: "p39-run 3.2s linear infinite" }}
        >
          {CAST.map((cast, index) => (
            <span
              key={cast.id}
              style={{ animation: `p39-hop .5s ${index * 0.12}s infinite` }}
              className="origin-bottom"
            >
              <MascotFigure id={cast.id} className="h-[96px] w-auto" />
            </span>
          ))}
        </div>
      </div>
      <div className="mt-7 flex items-center justify-between px-3">
        <span className="relative size-[86px]" aria-hidden="true">
          <i className="absolute top-[30px] left-0 h-[26px] w-[86px] rounded-[6px] border-[4px] border-[#111] bg-[#111]" />
          <i className="absolute top-0 left-[30px] h-[86px] w-[26px] rounded-[6px] border-[4px] border-[#111] bg-[#111]" />
        </span>
        <span className="flex gap-4" aria-hidden="true">
          <i className="size-14 rounded-full border-[4px] border-[#111] bg-[#FFE14D] shadow-[3px_3px_0_#111]" />
          <i className="mt-6 size-14 rounded-full border-[4px] border-[#111] bg-[#67E8F9] shadow-[3px_3px_0_#111]" />
        </span>
      </div>
      <div
        className="absolute right-12 bottom-6 flex -rotate-[25deg] gap-2"
        aria-hidden="true"
      >
        {[0, 1, 2, 3].map((i) => (
          <i key={i} className="h-10 w-2 rounded-full bg-[#111]/40" />
        ))}
      </div>
    </div>
  );
  return (
    <div
      role="status"
      className={`grid w-full place-items-center overflow-hidden ${room === "page" ? "h-screen bg-[#DCEBFF] bg-[linear-gradient(#0001_1px,transparent_1px),linear-gradient(90deg,#0001_1px,transparent_1px)] bg-size-[32px_32px]" : room === "content" ? "h-[calc(100vh-120px)] min-h-[520px]" : "py-2"}`}
    >
      {console_}
      {inline ? null : null}
    </div>
  );
}

/* ── C · Card Flip: the sign-in character cards flip one by one ── */
function SchemeC({ room }: { room: Room }) {
  const inline = room === "inline";
  const w = room === "page" ? 210 : room === "content" ? 180 : 74;
  const h = Math.round(w * 1.42);
  return (
    <div
      role="status"
      className={`relative grid w-full place-items-center overflow-hidden ${room === "page" ? "h-screen" : room === "content" ? "h-[calc(100vh-120px)] min-h-[520px] rounded-[22px] border-[4px] border-[#111] shadow-[8px_8px_0_#111]" : "py-4"}`}
      style={
        inline
          ? undefined
          : {
              backgroundColor: "#67E8F9",
              backgroundImage:
                "repeating-linear-gradient(-35deg,#A5F3FC 0 46px,#67E8F9 46px 92px)",
            }
      }
    >
      <div
        className="grid justify-items-center"
        style={{ gap: inline ? 10 : 36 }}
      >
        <div
          data-c-row=""
          className="flex items-end"
          style={{ gap: inline ? 6 : 22, perspective: 900 }}
        >
          {CAST.map((cast, index) => (
            <span
              key={cast.id}
              data-c-card=""
              className="relative block [transform-style:preserve-3d]"
              style={{
                width: w,
                height: h,
                animation: `p39-flip 3.2s ${index * 0.8}s infinite cubic-bezier(.5,0,.3,1)`,
              }}
            >
              <span
                className="absolute inset-0 overflow-hidden rounded-[18px] border-[#111] [backface-visibility:hidden]"
                style={{
                  borderWidth: inline ? 3 : 5,
                  boxShadow: inline ? "3px 3px 0 #111" : "8px 8px 0 #111",
                  backgroundColor: "#FF4D8D",
                  backgroundImage: inline
                    ? "radial-gradient(circle,#FFE14D 0 3px,transparent 3.5px),radial-gradient(circle,#fff 0 2px,transparent 2.5px)"
                    : "radial-gradient(circle,#FFE14D 0 9px,transparent 10px),radial-gradient(circle,#fff 0 6px,transparent 7px)",
                  backgroundSize: inline ? "20px 20px" : "44px 44px",
                  backgroundPosition: inline
                    ? "0 0,10px 10px"
                    : "0 0,22px 22px",
                }}
              >
                <span className="absolute top-1/2 left-1/2 aspect-square w-[34%] -translate-x-1/2 -translate-y-1/2 rounded-full border-[4px] border-[#111] bg-[linear-gradient(90deg,#111_50%,#FF4D8D_50%)]" />
              </span>
              <span
                className="absolute inset-0 overflow-hidden rounded-[18px] border-[#111] [backface-visibility:hidden] [transform:rotateY(180deg)]"
                style={{
                  borderWidth: inline ? 3 : 5,
                  boxShadow: inline ? "3px 3px 0 #111" : "8px 8px 0 #111",
                  backgroundColor: cast.bg,
                  backgroundImage:
                    "repeating-conic-gradient(from 0deg at 50% 72%,#ffffff66 0 9deg,transparent 9deg 18deg)",
                }}
              >
                <MascotFigure
                  id={cast.id}
                  className="absolute bottom-[-4%] left-1/2 h-[88%] w-auto -translate-x-1/2"
                />
              </span>
            </span>
          ))}
        </div>
        <div className="flex items-center" style={{ gap: inline ? 8 : 16 }}>
          <span
            data-c-label=""
            className="-rotate-2 border-[#111] bg-white font-display font-extrabold"
            style={{
              fontSize: inline ? 16 : 34,
              borderWidth: inline ? 3 : 4,
              padding: inline ? "2px 10px" : "6px 22px",
              boxShadow: inline
                ? "2px 2px 0 #111"
                : "6px 6px 0 #FF4D8D, 6px 6px 0 4px #111",
              borderRadius: inline ? 8 : 16,
            }}
          >
            Loading…
          </span>
          <span className="flex" style={{ gap: inline ? 4 : 8 }}>
            {[0, 1, 2, 3].map((i) => (
              <i
                key={i}
                className="block rounded-full border-[#111]"
                style={{
                  width: inline ? 10 : 20,
                  height: inline ? 10 : 20,
                  borderWidth: inline ? 2 : 4,
                  animation: `p39-dot 3.2s ${i * 0.8}s infinite`,
                }}
              />
            ))}
          </span>
        </div>
      </div>
    </div>
  );
}

function Scheme({ s, room }: { s: string; room: Room }) {
  const node =
    s === "B" ? (
      <SchemeB room={room} />
    ) : s === "C" ? (
      <SchemeC room={room} />
    ) : (
      <SchemeA room={room} />
    );
  return <div data-room={room}>{node}</div>;
}

function Proposals() {
  const params = useSearchParams();
  const s = params.get("s") ?? "A";
  const room = (params.get("room") ?? "page") as Room;
  return (
    <>
      <style>{KEYFRAMES}</style>
      {room === "page" ? (
        <Scheme s={s} room="page" />
      ) : room === "content" ? (
        <AppShell role="student">
          <div className="w-full px-14 pt-11 pb-10 max-[767px]:px-4 max-[767px]:pt-6">
            <Scheme s={s} room="content" />
          </div>
        </AppShell>
      ) : (
        <AppShell role="student">
          <div className="w-full max-w-[1180px] px-14 pt-11 max-[767px]:px-4">
            <section className="max-w-[440px] rounded-[18px] border-[3px] border-[#111] bg-white p-5 shadow-[6px_6px_0_#111]">
              <h2 className="m-0 mb-4 font-display text-2xl font-extrabold">
                RAG
              </h2>
              <Scheme s={s} room="inline" />
            </section>
          </div>
        </AppShell>
      )}
    </>
  );
}

export default function LoadingProposalsPage() {
  return (
    <Suspense>
      <Proposals />
    </Suspense>
  );
}
