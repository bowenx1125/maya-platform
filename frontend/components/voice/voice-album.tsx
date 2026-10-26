"use client";

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
  alb: "relative box-border w-full max-w-[1120px] mx-auto text-[#111] [font-family:var(--font-lexend,'Lexend'),system-ui,sans-serif] bg-[#fff8e7] [background-image:radial-gradient(#e9dfc4_1.5px,transparent_1.5px)] [background-size:22px_22px] border-4 border-solid border-[#111] rounded-[18px] shadow-[10px_10px_0_#111] pt-[34px] pr-[40px] pb-[44px] pl-[84px] min-h-[760px] max-[960px]:pt-[24px] max-[960px]:pr-[18px] max-[960px]:pb-[28px] max-[960px]:pl-[64px] [&_*]:box-border [&_p]:m-0",
  rings:
    "absolute left-[22px] top-[30px] bottom-[30px] flex flex-col justify-around [&_i]:block [&_i]:w-[34px] [&_i]:h-[18px] [&_i]:border-4 [&_i]:border-solid [&_i]:border-[#111] [&_i]:rounded-[12px] [&_i]:bg-[#ffe14d]",
  top: "flex items-center gap-[18px] mb-[30px]",
  h2: "inline-block m-0 py-[6px] px-[22px] bg-[#c4b5fd] border-[3px] border-solid border-[#111] rounded-[8px] shadow-[5px_5px_0_#111] [transform:rotate(-3deg)] [font:800_44px_var(--font-bricolage,'Bricolage_Grotesque'),system-ui] leading-normal",
  tape: "w-[70px] h-[22px] bg-[rgb(103_232_249_/_0.7)] border-2 border-solid border-[#111] [transform:rotate(8deg)]",
  pn: "inline-flex items-center gap-[6px] h-[44px] py-0 px-[18px] bg-[#ff4d8d] text-[#111] border-[3px] border-solid border-[#111] rounded-[10px] shadow-[4px_4px_0_#111] [font:800_15px_var(--font-lexend,'Lexend')] cursor-pointer disabled:cursor-not-allowed disabled:opacity-60",
  grid: "grid grid-cols-[repeat(3,minmax(0,1fr))] gap-y-[34px] gap-x-[30px] m-0 p-0 list-none max-[960px]:grid-cols-[minmax(0,1fr)]",
  card: "relative flex flex-col gap-[10px] p-[10px] border-[3px] border-solid border-[#111] rounded-[14px] shadow-[6px_6px_0_#111] [&:nth-child(3n+1)]:[transform:rotate(-1.6deg)] [&:nth-child(3n+2)]:[transform:rotate(1.2deg)] [&:nth-child(3n)]:[transform:rotate(-0.6deg)] bg-[#c4b5fd] data-[status=enrolling]:bg-[#fde68a] data-[status=validating]:bg-[#fde68a]",
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
  ib: "inline-grid place-items-center flex-none w-[42px] h-[42px] p-0 border-2 border-solid border-[#111] rounded-[10px] shadow-[3px_3px_0_#111] text-[#111] cursor-pointer disabled:opacity-45 disabled:shadow-none disabled:cursor-not-allowed",
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
  title,
  name,
  footer,
  audio,
}: {
  index: number;
  profile: VoiceProfile;
  agents: AffectedAgent[] | undefined;
  title: string | undefined;
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
    <li className={voiceAlbum.card} data-status={profile.status} title={title}>
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
