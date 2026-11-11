"use client";

import { useFileDrop } from "../ui/use-file-drop";

import { LIST_CARD_LIFT } from "../agent-chrome";
import { BUSY_MOTION_PRIMARY, PRESS_HIT, PRESS_MOTION } from "../ui/button";
import { useEffect, useState, type ReactNode } from "react";

import type { AffectedAgent, VoiceProfile } from "../../lib/api/platform";
import { useT } from "../../lib/i18n";
import { useSession } from "../session-provider";
import { useNoticeTrayAbove } from "../ui";

/**
 * Voice Sticker Album list (proposals/20-voices-album-v2, o1-album-v2), as
 * Tailwind classes only. The create screen keeps its old layout.
 */
export const voiceAlbum = {
  alb: "relative box-border w-full max-w-[1120px] mx-auto text-[#111] [font-family:var(--font-lexend,'Lexend'),system-ui,sans-serif] bg-[#fff8e7] [background-image:radial-gradient(#e9dfc4_1.5px,transparent_1.5px)] [background-size:22px_22px] border-4 border-solid border-[#111] rounded-[18px] shadow-[10px_10px_0_#111] pt-[34px] pr-[40px] pb-[44px] pl-[84px] min-h-[760px] max-[960px]:pt-[24px] max-[960px]:pr-[18px] max-[960px]:pb-[28px] max-[960px]:pl-[64px] min-w-0 max-[520px]:pl-[50px] max-[520px]:pr-[12px] max-[520px]:shadow-[6px_6px_0_#111] [&_*]:box-border [&_p]:m-0",
  rings:
    "absolute left-[22px] top-[30px] bottom-[30px] flex flex-col justify-around [&_i]:block [&_i]:w-[34px] [&_i]:h-[18px] [&_i]:border-4 [&_i]:border-solid [&_i]:border-[#111] [&_i]:rounded-[12px] [&_i]:bg-[#ffe14d] max-[520px]:left-[9px] max-[520px]:[&_i]:w-[28px]",
  top: "flex flex-wrap items-center gap-[18px] mb-[30px] max-[520px]:gap-[12px] max-[520px]:mb-[22px]",
  h2: "inline-block m-0 py-[6px] px-[22px] bg-[#c4b5fd] border-[3px] border-solid border-[#111] rounded-[8px] shadow-[5px_5px_0_#111] [transform:rotate(-3deg)] [font:800_44px_var(--font-bricolage,'Bricolage_Grotesque'),system-ui] leading-normal max-[520px]:![font-size:32px] max-[520px]:!px-[14px]",
  tape: "w-[70px] h-[22px] bg-[rgb(103_232_249_/_0.7)] border-2 border-solid border-[#111] [transform:rotate(8deg)]",
  pn: `inline-flex items-center gap-[6px] h-[44px] py-0 px-[18px] bg-[#ff4d8d] text-[#111] border-[3px] border-solid border-[#111] rounded-[10px] [font:800_15px_var(--font-lexend,'Lexend')] cursor-pointer disabled:cursor-not-allowed disabled:opacity-60 ${PRESS_MOTION} ${BUSY_MOTION_PRIMARY}`,
  grid: "grid grid-cols-[repeat(3,minmax(0,1fr))] gap-y-[34px] gap-x-[30px] m-0 p-0 list-none max-[960px]:grid-cols-[minmax(0,1fr)]",
  card: `relative flex flex-col gap-[10px] p-[10px] border-[3px] border-solid border-[#111] rounded-[14px] shadow-[6px_6px_0_#111] [&:nth-child(3n+1)]:[--r:-1.6deg] [&:nth-child(3n+2)]:[--r:1.2deg] [&:nth-child(3n)]:[--r:-0.6deg] bg-[#c4b5fd] data-[status=enrolling]:bg-[#fde68a] data-[status=validating]:bg-[#fde68a] ${LIST_CARD_LIFT}`,
  art: "relative grid place-items-center h-[104px] overflow-hidden border-[3px] border-solid border-[#111] rounded-[8px] [background:linear-gradient(135deg,#fff_0%,#ede9fe_30%,#fbcfe8_55%,#fff_70%,#c7f9ff_100%)]",
  wv: "flex items-center gap-[3px] h-[60px] w-[78%] [&_i]:flex-1 [&_i]:bg-[#111] [&_i]:rounded-[3px] [&_i]:min-h-[4px]",
  ty: "absolute right-[46px] bottom-[6px] [font:800_20px_var(--font-bricolage,'Bricolage_Grotesque'),system-ui] text-white [-webkit-text-stroke:2px_#111] [paint-order:stroke] [text-shadow:2px_2px_0_#111]",
  no: "absolute left-[8px] top-[6px] [font:700_12px_var(--font-space-mono,'Space_Mono'),monospace]",
  stamp:
    "absolute inset-0 grid place-items-center bg-[rgb(253_230_138_/_0.55)]",
  spin: "inline-block w-[26px] h-[26px] border-4 border-solid border-[#111] border-t-transparent rounded-[50%] animate-spin",
  plate:
    "flex flex-col gap-[8px] p-[10px] bg-white border-2 border-solid border-[#111] rounded-[8px]",
  vn: "[font:700_16px_var(--font-lexend,'Lexend')] text-inherit text-left [overflow-wrap:anywhere] [background:none] border-0 p-0 cursor-pointer disabled:cursor-not-allowed",
  nameInput:
    "[font:700_16px_var(--font-lexend,'Lexend')] border-2 border-solid border-[#111] rounded-[6px] py-[2px] px-[6px]",
  stats:
    "m-0 border-2 border-solid border-[#111] rounded-[6px] bg-[#f5f9ff] overflow-hidden [&_dt]:py-[3px] [&_dt]:px-[8px] [&_dt]:bg-[#111] [&_dt]:text-[#67e8f9] [&_dt]:[font:800_10px_var(--font-lexend,'Lexend')] [&_dt]:tracking-[1.2px] [&_dt]:uppercase [&_dd]:m-0 [&_dd]:py-[6px] [&_dd]:px-[8px] [&_dd]:min-h-[30px] [&_ol]:m-0 [&_ol]:pl-[18px] [&_ol]:[font:500_12px/1.6_var(--font-lexend,'Lexend')]",
  none: "[font:italic_500_12px_var(--font-lexend,'Lexend')] text-[#777]",
  sig: "flex items-baseline gap-[6px] min-h-[24px] pb-[2px] [border-bottom:2px_solid_#111]",
  lbl: "[font:800_10px_var(--font-lexend,'Lexend')] tracking-[1.2px] uppercase text-[#555]",
  sg: "[font:700_20px_var(--font-caveat,'Caveat'),cursive] text-[#0e7490]",
  ft: "flex items-center gap-[10px]",
  ib: `inline-grid place-items-center flex-none w-[42px] h-[42px] p-0 border-2 border-solid border-[#111] rounded-[10px] text-[#111] cursor-pointer disabled:opacity-45 disabled:shadow-none disabled:cursor-not-allowed ${PRESS_MOTION}`,
  play: "bg-[#a3e635]",
  del: "bg-[#ef4444] text-white",
  audio: "w-full",
  ghost:
    "grid place-items-center min-h-[330px] text-[#b9ae90] border-[3px] border-dashed border-[#b9ae90] rounded-[14px] [font:700_13px_var(--font-lexend,'Lexend')]",
  skel: "grid min-h-[330px] border-[3px] border-dashed border-[#b9ae90] rounded-[14px] [background:repeating-linear-gradient(-45deg,transparent_0_12px,rgb(185_174_144_/_0.18)_12px_24px)]",
  ghostFirst:
    "grid min-h-[330px] border-[3px] border-dashed border-[#111] rounded-[14px] bg-white text-[#111] gap-[12px] content-center justify-items-center text-center p-[20px] [&_p]:[font:800_18px_var(--font-bricolage,'Bricolage_Grotesque'),system-ui]",
  mic: "grid place-items-center w-[76px] h-[76px] rounded-[50%] bg-[#c4b5fd] border-[3px] border-solid border-[#111] shadow-[4px_4px_0_#111]",
} as const;

export function AlbumRings() {
  return (
    <div className={voiceAlbum.rings} aria-hidden="true">
      {Array.from({ length: 6 }, (_, index) => (
        <i key={index} />
      ))}
    </div>
  );
}

/** Decorative waveform; bar heights are fixed per card number. */
export function AlbumWave({ seed }: { seed: number }) {
  return (
    <span className={voiceAlbum.wv} aria-hidden="true">
      {Array.from({ length: 26 }, (_, i) => (
        <i
          key={i}
          style={{
            height: `${18 + Math.round(Math.abs(Math.sin(i * 1.7 + seed) * Math.cos(i * 0.6 + seed * 2)) * 62)}%`,
          }}
        />
      ))}
    </span>
  );
}

export function AlbumMic() {
  return (
    <span className={voiceAlbum.mic} aria-hidden="true">
      <svg
        width="34"
        height="34"
        viewBox="0 0 24 24"
        fill="none"
        stroke="#111"
        strokeWidth="2.4"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <rect x="9" y="3" width="6" height="11" rx="3" />
        <path d="M5 11a7 7 0 0 0 14 0M12 18v3" />
      </svg>
    </span>
  );
}

export function fileExt(filename: string | undefined): string {
  if (!filename) return "";
  const dot = filename.lastIndexOf(".");
  return dot >= 0 ? filename.slice(dot + 1).toUpperCase() : "";
}

/**
 * Creator's username. The backend does not send it yet (see
 * proposals/20-voices-album-v2/API-CHANGES.md); the row stays bound to the
 * field and shows an empty signature line until it does.
 */
export function voiceMaker(profile: VoiceProfile): string | null {
  const extra = profile as VoiceProfile & {
    owner_username?: string | null;
    created_by_username?: string | null;
  };
  return extra.owner_username || extra.created_by_username || null;
}

/** Agents using each voice, from GET /voice-profiles/{id}/affected-agents. */
export function useVoiceAgents(profiles: VoiceProfile[], enabled: boolean) {
  const { api } = useSession();
  const [agents, setAgents] = useState<Record<string, AffectedAgent[]>>({});
  const ids = enabled ? profiles.map((profile) => profile.id).join(",") : "";
  useEffect(() => {
    let live = true;
    const list = ids ? ids.split(",") : [];
    void Promise.all(
      list.map(async (id) => {
        try {
          return [id, await api.voiceAffectedAgents(id)] as const;
        } catch {
          return [id, null] as const;
        }
      }),
    ).then((rows) => {
      if (!live) return;
      const next: Record<string, AffectedAgent[]> = {};
      for (const [id, value] of rows) if (value) next[id] = value;
      setAgents(next);
    });
    return () => {
      live = false;
    };
  }, [api, ids]);
  return agents;
}

export function VoiceAlbumCard({
  index,
  profile,
  agents,
  name,
  footer,
  audio,
}: {
  index: number;
  profile: VoiceProfile;
  agents: AffectedAgent[] | undefined;
  name: ReactNode;
  footer: ReactNode;
  audio: ReactNode;
}) {
  const t = useT();
  const maker = voiceMaker(profile);
  const used = agents ?? [];
  const pending =
    profile.status === "enrolling" || profile.status === "validating";
  return (
    <li className={voiceAlbum.card} data-status={profile.status}>
      <div className={voiceAlbum.art}>
        <span className={voiceAlbum.no} aria-hidden="true">
          #{String(index + 1).padStart(2, "0")}
        </span>
        <AlbumWave seed={index + 1} />
        <span className={voiceAlbum.ty} aria-hidden="true">
          {fileExt(profile.source_filename)}
        </span>
        {pending ? (
          <span className={voiceAlbum.stamp} aria-hidden="true">
            <i className={voiceAlbum.spin} />
          </span>
        ) : null}
      </div>
      <div className={voiceAlbum.plate}>
        {name}
        <dl className={voiceAlbum.stats}>
          <dt>{t("voiceUsedBy")}</dt>
          <dd>
            {used.length ? (
              <ol>
                {used.map((agent) => (
                  <li key={agent.agent_id}>{agent.name}</li>
                ))}
              </ol>
            ) : (
              <span className={voiceAlbum.none}>{t("voiceNoAgentsYet")}</span>
            )}
          </dd>
        </dl>
        <p className={voiceAlbum.sig}>
          <span className={voiceAlbum.lbl}>{t("voiceMadeBy")}</span>{" "}
          {maker ? <span className={voiceAlbum.sg}>@{maker}</span> : null}
        </p>
      </div>
      <div className={voiceAlbum.ft}>{footer}</div>
      {audio}
    </li>
  );
}

/**
 * Error state: lift the shared U3 tray (its own useNoticeTrayAbove) so it
 * sits inside the album frame, above the bottom-right corner, as approved.
 */
export function AlbumTrayAnchor() {
  const [anchor, setAnchor] = useState<HTMLSpanElement | null>(null);
  useNoticeTrayAbove(anchor);
  return (
    <span
      ref={setAnchor}
      aria-hidden="true"
      className="pointer-events-none absolute right-0 bottom-[41px] h-0 w-0"
    />
  );
}

/**
 * Create screen (proposals/24-voices-req-label/p2-tab): record player
 * b-disc-v2 with the H1 sleeve label, a flat pink edge strip instead of the
 * mini disc. Decoration is aria-hidden; coordinates follow the mockup stage.
 */
const KNOB =
  "absolute w-[30px] h-[30px] rounded-[50%] border-[3px] border-solid border-[#111] shadow-[2px_2px_0_#111]";
const EQ_HEIGHTS = [30, 60, 45, 90, 70, 40, 85, 55, 25, 65];
const EQ_COLORS = ["#FF4D8D", "#FFE14D", "#A3E635", "#67E8F9"];
const ZIG = "M2 18 12 4 22 18 32 4 42 18 52 4 62 18";

function CreateDeco({ hasFile }: { hasFile: boolean }) {
  return (
    <div
      className="pointer-events-none absolute inset-0 z-0 @max-[48rem]:[zoom:0.57]"
      aria-hidden="true"
    >
      <span className="absolute top-0 left-0 h-[430px] w-[470px] rounded-[22px] border-4 border-solid border-[#111] bg-[#ff4d8d] shadow-[8px_8px_0_#111] before:absolute before:inset-[14px] before:rounded-[14px] before:border-[3px] before:border-dashed before:border-[rgb(17_17_17_/_0.35)] before:content-['']" />
      <span className={`${KNOB} top-[360px] left-[400px] bg-[#67e8f9]`} />
      <span className={`${KNOB} top-[375px] left-[30px] bg-[#a3e635]`} />
      <span className="absolute top-[16px] left-[384px] h-[48px] w-[48px] rounded-[50%] border-4 border-solid border-[#111] bg-[#ffe14d]" />
      <span
        className={`absolute top-[30px] left-[400px] h-[230px] w-[16px] origin-[8px_8px] rounded-[8px] border-[3px] border-solid border-[#111] bg-[#e5e7eb] ${hasFile ? "[transform:rotate(34deg)]" : "[transform:rotate(18deg)]"}`}
      />
      <span className="absolute top-[330px] left-[870px] @max-[48rem]:top-auto @max-[48rem]:bottom-[10px] @max-[48rem]:left-[330px] h-[110px] w-[110px] rounded-[50%] border-4 border-solid border-[#111] shadow-[5px_5px_0_#111] [background:radial-gradient(circle,#111_0_14%,#4b5563_15%_40%,#111_41%_46%,#9ca3af_47%_100%)]" />
      <span className="absolute top-[390px] left-[560px] @max-[48rem]:top-auto @max-[48rem]:bottom-[20px] @max-[48rem]:left-[10px] flex h-[70px] items-end gap-[5px]">
        {EQ_HEIGHTS.map((height, index) => (
          <i
            key={index}
            className="w-[12px] rounded-[3px] border-2 border-solid border-[#111]"
            style={{
              height: `${hasFile ? height : 12}%`,
              background: EQ_COLORS[index % 4],
            }}
          />
        ))}
      </span>
      <svg
        className="absolute top-[10px] left-[1000px] @max-[48rem]:top-[-22px] @max-[48rem]:left-[330px] [transform:rotate(14deg)]"
        width="44"
        height="44"
        viewBox="0 0 24 24"
      >
        <path
          d="M12 1l3 7.5 8 .8-6 5.4 1.8 8L12 18.6 5.2 22.7 7 14.7 1 9.3l8-.8z"
          fill="#FFE14D"
          stroke="#111"
          strokeWidth="1.8"
          strokeLinejoin="round"
        />
      </svg>
      <i className="absolute top-[20px] left-[520px] @max-[48rem]:top-[150px] @max-[48rem]:left-[440px] h-[24px] w-[24px] rounded-[50%] border-[3px] border-solid border-[#111] bg-[#67e8f9]" />
      <i className="absolute top-[250px] left-[960px] @max-[48rem]:top-auto @max-[48rem]:bottom-[40px] @max-[48rem]:left-[200px] h-[26px] w-[26px] rounded-[6px] border-[3px] border-solid border-[#111] bg-[#c4b5fd] [transform:rotate(18deg)]" />
      <svg
        className="absolute top-[350px] left-[700px] @max-[48rem]:top-auto @max-[48rem]:bottom-[100px] @max-[48rem]:left-[230px] [transform:rotate(-6deg)]"
        width="70"
        height="22"
        viewBox="0 0 70 22"
      >
        <path
          d={ZIG}
          fill="none"
          stroke="#111"
          strokeWidth="7"
          strokeLinejoin="round"
        />
        <path
          d={ZIG}
          fill="none"
          stroke="#67E8F9"
          strokeWidth="3.5"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}

export function VoiceAlbumCreate({
  fileName,
  input,
  requirement,
  consent,
  consentAction,
  busy,
  disabled,
  onFile,
}: {
  fileName: string | null;
  /** The sr-only file input (aria-label + aria-describedby set by the caller). */
  input: ReactNode;
  requirement: string;
  consent: string;
  busy?: boolean;
  disabled?: boolean;
  onFile?: (file: File) => void;
  /**
   * Makes the consent card the create button (Agent page: confirming consent
   * is the create step there, with no header Done).
   */
  consentAction?: {
    onConfirm: () => void;
    disabled: boolean;
    busy: boolean;
    describedBy?: string;
  };
}) {
  const hasFile = Boolean(fileName);
  const fileDrop = useFileDrop({ busy, disabled, onFile });
  const consentCard = `flex items-start gap-[12px] rounded-[14px] border-[3px] border-[#111] px-[22px] py-[20px] @max-[48rem]:px-[16px] @max-[48rem]:py-[16px] @max-[48rem]:text-[18px] [font:800_22px/1.35_var(--font-bricolage,'Bricolage_Grotesque'),system-ui] ${hasFile ? "border-solid bg-white text-[#111] shadow-[6px_6px_0_#111]" : "border-dashed bg-transparent text-[#9ca3af]"}`;
  // Sized by the room it gets, not the window: the Voices page draws it wide,
  // the narrow Voice card on an Agent page gets the compact record player.
  return (
    <div className="@container">
      <div className="relative grid @max-[22rem]:[zoom:0.75] grid-cols-[auto_1fr] items-center gap-[56px] px-[30px] pt-[20px] pb-[30px] @max-[48rem]:grid-cols-[minmax(0,1fr)] @max-[48rem]:gap-[26px] @max-[48rem]:px-0 @max-[48rem]:pt-[4px] @max-[48rem]:pb-[96px] [&>*:not([aria-hidden])]:relative [&>*:not([aria-hidden])]:z-[1]">
        <CreateDeco hasFile={hasFile} />
        <label
          aria-busy={busy || undefined}
          data-kind="voice"
          data-has-file={hasFile || undefined}
          {...fileDrop}
          className={`upload-tile mt-[44px] ml-[44px] grid h-[340px] w-[340px] @max-[48rem]:mt-[25px] @max-[48rem]:ml-[25px] @max-[48rem]:mb-[30px] @max-[48rem]:h-[194px] @max-[48rem]:w-[194px] cursor-pointer place-items-center rounded-[50%] border-4 border-solid border-[#111] [background:repeating-radial-gradient(circle,#111_0_3px,#2a2a2a_3px_7px)] ${hasFile ? "shadow-[8px_8px_0_#111,0_0_0_10px_#a3e635]" : "shadow-[8px_8px_0_#111]"}`}
        >
          <span
            className={`upload-tile-disc grid h-[150px] w-[150px] @max-[48rem]:h-[88px] @max-[48rem]:w-[88px] @max-[48rem]:p-[8px] place-items-center rounded-[50%] border-4 border-solid border-[#111] p-[14px] text-center ${hasFile ? "bg-[#ff4d8d]" : "bg-[#ffe14d]"}`}
          >
            {fileName && !busy ? (
              <b
                className="[font:800_15px/1.25_var(--font-lexend,'Lexend')] @max-[48rem]:text-[12px] [overflow-wrap:anywhere]"
                aria-live="polite"
              >
                {fileName}
              </b>
            ) : (
              <svg
                width="48"
                height="48"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.8"
                strokeLinecap="round"
                strokeLinejoin="round"
                aria-hidden="true"
              >
                <path d="M12 20V8m-5 5 5-5 5 5M5 4h14" />
              </svg>
            )}
          </span>
          {input}
        </label>
        <div className="flex flex-col gap-[18px]">
          <div className="relative mt-[6px] mb-[4px] ml-[18px] max-w-[520px] self-start @max-[48rem]:ml-[12px] @max-[48rem]:max-w-none @max-[48rem]:self-stretch @max-[48rem]:pl-[40px] @max-[48rem]:pr-[16px] @max-[48rem]:py-[16px] rounded-[6px_22px_6px_6px] border-[3px] border-solid border-[#111] bg-[#fff8e7] py-[18px] pr-[22px] pl-[48px] shadow-[6px_6px_0_#111] [transform:rotate(-1.5deg)]">
            <span
              className="absolute top-[-3px] bottom-[-3px] left-[-3px] w-[24px] rounded-[6px_0_0_6px] border-[3px] border-solid border-[#111] bg-[#ff4d8d]"
              aria-hidden="true"
            />
            <span
              className="absolute top-[-13px] left-[46%] h-[22px] w-[84px] border-2 border-solid border-[#111] bg-[rgb(103_232_249_/_0.75)] [transform:rotate(-6deg)]"
              aria-hidden="true"
            />
            <p
              id="voice-sample-req"
              className="[font:700_17px/1.45_var(--font-lexend,'Lexend')] @max-[48rem]:text-[15px] text-[#111]"
            >
              {requirement}
            </p>
            <span
              className="absolute right-[14px] bottom-[10px] flex h-[16px] items-end gap-[3px]"
              aria-hidden="true"
            >
              {[6, 12, 9, 16, 7, 13].map((height, index) => (
                <i
                  key={index}
                  className="w-[4px] rounded-[2px] bg-[#ff4d8d]"
                  style={{ height }}
                />
              ))}
            </span>
          </div>
          {consentAction ? (
            <button
              type="button"
              id="voice-consent-text"
              className={`${consentCard} ${hasFile ? "cursor-pointer" : "cursor-not-allowed"} text-left transition-[translate,box-shadow] duration-150 ease-[cubic-bezier(.2,.8,.2,1)] enabled:hover:-translate-y-0.5 enabled:active:translate-y-1.5 enabled:active:shadow-none motion-reduce:transition-none motion-reduce:enabled:hover:translate-y-0 motion-reduce:enabled:active:translate-y-0 ${PRESS_HIT}`}
              disabled={consentAction.disabled}
              aria-busy={consentAction.busy || undefined}
              aria-describedby={consentAction.describedBy}
              onClick={consentAction.onConfirm}
            >
              <span
                className={`mt-[2px] grid h-[30px] w-[30px] flex-none place-items-center rounded-[8px] border-[3px] border-solid border-[#111] text-[#111] ${hasFile ? "bg-[#67e8f9]" : "bg-[#e5e7eb]"}`}
                aria-hidden="true"
              >
                {consentAction.busy ? (
                  <span className="spinner" aria-hidden="true" />
                ) : hasFile ? (
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.4"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="m5 12 4 4L19 6" />
                  </svg>
                ) : null}
              </span>
              <span>{consent}</span>
            </button>
          ) : (
            <p id="voice-consent-text" className={consentCard}>
              <span
                className={`mt-[2px] grid h-[30px] w-[30px] flex-none place-items-center rounded-[8px] border-[3px] border-solid border-[#111] text-[#111] ${hasFile ? "bg-[#67e8f9]" : "bg-[#e5e7eb]"}`}
                aria-hidden="true"
              >
                {hasFile ? (
                  <svg
                    width="16"
                    height="16"
                    viewBox="0 0 24 24"
                    fill="none"
                    stroke="currentColor"
                    strokeWidth="2.4"
                    strokeLinecap="round"
                    strokeLinejoin="round"
                  >
                    <path d="m5 12 4 4L19 6" />
                  </svg>
                ) : null}
              </span>
              <span>{consent}</span>
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
