"use client";

import { LIST_CARD_LIFT } from "../agent-chrome";
import type { ReactNode } from "react";

import type { AffectedAgent, KnowledgeDocument } from "../../lib/api/platform";
import { useT } from "../../lib/i18n";
import { Button, PRESS_MOTION, WORKSPACE_ACTION_SIZE } from "../ui/button";

const PATHS = {
  doc: "M6 3h9l4 4v14H6zM14 3v5h5",
  download: "M12 4v11m-5-5 5 5 5-5M5 20h14",
  close: "M6 6l12 12M18 6L6 18",
  refresh: "M20 11a8 8 0 1 0-2 5.3M20 5v6h-6",
  plus: "M12 5v14M5 12h14",
  upload: "M12 20V8m-5 5 5-5 5 5M5 4h14",
} as const;

export function AlbumIcon({
  name,
  size = 18,
  stroke = 2.4,
}: {
  name: keyof typeof PATHS;
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
      <path d={PATHS[name]} />
    </svg>
  );
}

/**
 * Sticker Album RAG page (proposals/18-rag-album-final, Card B), as
 * Tailwind classes. Variants that the old stylesheet combined (card tone,
 * big card, danger button, first ghost) are whole strings here.
 */
export const albumStyles = {
  alb: "relative box-border w-full max-w-[1120px] mx-auto text-[#111] [font-family:var(--font-lexend,'Lexend'),system-ui,sans-serif] bg-[#fff8e7] [background-image:radial-gradient(#e9dfc4_1.5px,transparent_1.5px)] [background-size:22px_22px] border-4 border-solid border-[#111] rounded-[18px] shadow-[10px_10px_0_#111] pt-[34px] pr-[40px] pb-[40px] pl-[84px] max-[960px]:pt-[24px] max-[960px]:pr-[18px] max-[960px]:pb-[28px] max-[960px]:pl-[64px] min-w-0 max-[520px]:pl-[50px] max-[520px]:pr-[12px] max-[520px]:shadow-[6px_6px_0_#111] [&_*]:box-border [&_*::before]:box-border [&_*::after]:box-border [&_p]:m-0",
  rings:
    "absolute left-[22px] top-[30px] bottom-[30px] flex flex-col justify-around [&_i]:block [&_i]:w-[34px] [&_i]:h-[18px] [&_i]:border-4 [&_i]:border-solid [&_i]:border-[#111] [&_i]:rounded-[12px] [&_i]:bg-[#ffe14d] max-[520px]:left-[9px] max-[520px]:[&_i]:w-[28px]",
  top: "flex flex-wrap items-center gap-[18px] mb-[30px] max-[520px]:gap-[12px] max-[520px]:mb-[22px] [&_h2]:inline-block [&_h2]:m-0 [&_h2]:py-[6px] [&_h2]:px-[22px] [&_h2]:bg-[#67e8f9] [&_h2]:border-[3px] [&_h2]:border-solid [&_h2]:border-[#111] [&_h2]:rounded-[8px] [&_h2]:shadow-[5px_5px_0_#111] [&_h2]:[transform:rotate(-3deg)] [&_h2]:[font:800_44px_var(--font-bricolage,'Bricolage_Grotesque'),system-ui] [&_h2]:leading-normal max-[520px]:[&_h2]:![font-size:32px] max-[520px]:[&_h2]:!px-[14px]",
  tape: "w-[70px] h-[22px] bg-[rgb(255_77_141_/_0.55)] border-2 border-solid border-[#111] [transform:rotate(8deg)]",
  sp: "flex-1",
  count: "[font:800_16px_var(--font-lexend,'Lexend')]",
  grid: "grid grid-cols-[repeat(3,minmax(0,1fr))] gap-y-[34px] gap-x-[30px] m-0 p-0 list-none max-[960px]:grid-cols-[minmax(0,1fr)]",
  card: `relative flex flex-col gap-[10px] p-[10px] border-[3px] border-solid border-[#111] rounded-[14px] shadow-[6px_6px_0_#111] [&:nth-child(3n+1)]:[--r:-1.6deg] [&:nth-child(3n+2)]:[--r:1.2deg] [&:nth-child(3n)]:[--r:-0.6deg] bg-[#67e8f9] ${LIST_CARD_LIFT}`,
  cardFailed: `relative flex flex-col gap-[10px] p-[10px] border-[3px] border-solid border-[#111] rounded-[14px] shadow-[6px_6px_0_#111] [&:nth-child(3n+1)]:[--r:-1.6deg] [&:nth-child(3n+2)]:[--r:1.2deg] [&:nth-child(3n)]:[--r:-0.6deg] bg-[#fca5a5] ${LIST_CARD_LIFT}`,
  cardPending: `relative flex flex-col gap-[10px] p-[10px] border-[3px] border-solid border-[#111] rounded-[14px] shadow-[6px_6px_0_#111] [&:nth-child(3n+1)]:[--r:-1.6deg] [&:nth-child(3n+2)]:[--r:1.2deg] [&:nth-child(3n)]:[--r:-0.6deg] bg-[#fde68a] ${LIST_CARD_LIFT}`,
  cardBig:
    "relative flex flex-col gap-[10px] p-[10px] border-[3px] border-solid border-[#111] rounded-[14px] shadow-[6px_6px_0_#111] [&:nth-child(3n+1)]:[transform:rotate(-1.6deg)] [&:nth-child(3n+2)]:[transform:rotate(1.2deg)] [&:nth-child(3n)]:[transform:rotate(-0.6deg)] bg-[#67e8f9] [transform:rotate(-2deg)]",
  art: "relative grid place-items-center border-[3px] border-solid border-[#111] rounded-[8px] [background:linear-gradient(135deg,#fff_0%,#c7f9ff_30%,#fbcfe8_55%,#fff_70%,#bae6fd_100%)] h-[96px]",
  artBig:
    "relative grid place-items-center border-[3px] border-solid border-[#111] rounded-[8px] [background:linear-gradient(135deg,#fff_0%,#c7f9ff_30%,#fbcfe8_55%,#fff_70%,#bae6fd_100%)] h-[240px]",
  ty: "[font:800_34px_var(--font-bricolage,'Bricolage_Grotesque'),system-ui] text-white [-webkit-text-stroke:2.5px_#111] [paint-order:stroke] [text-shadow:3px_3px_0_#111]",
  tyBig:
    "[font:800_64px_var(--font-bricolage,'Bricolage_Grotesque'),system-ui] text-white [-webkit-text-stroke:2.5px_#111] [paint-order:stroke] [text-shadow:3px_3px_0_#111]",
  no: "absolute left-[8px] top-[6px] [font:700_12px_var(--font-space-mono,'Space_Mono'),monospace]",
  cnt: "absolute right-[8px] bottom-[6px] grid place-items-center w-[30px] h-[30px] rounded-[50%] bg-[#ff4d8d] text-white border-2 border-solid border-[#111] shadow-[2px_2px_0_#111] [font:800_14px_var(--font-bricolage,'Bricolage_Grotesque'),system-ui]",
  plate:
    "flex flex-col gap-[8px] min-h-[92px] p-[10px] bg-white border-2 border-solid border-[#111] rounded-[8px]",
  fn: "[font:700_16px_var(--font-lexend,'Lexend')] text-inherit text-left [overflow-wrap:anywhere] whitespace-normal [background:none] border-0 p-0 no-underline cursor-pointer",
  renameInput:
    "[font:700_16px_var(--font-lexend,'Lexend')] border-2 border-solid border-[#111] rounded-[6px] py-[2px] px-[6px]",
  stkWarn:
    "inline-flex items-center gap-[6px] w-fit py-[3px] px-[8px] border-2 border-solid border-[#111] rounded-[4px] [font:600_12px_var(--font-lexend,'Lexend')] bg-[#fff7cc]",
  stkBad:
    "inline-flex items-center gap-[6px] w-fit py-[3px] px-[8px] border-2 border-solid border-[#111] rounded-[4px] [font:600_12px_var(--font-lexend,'Lexend')] bg-[#ffe4e4] text-[#b91c1c]",
  spin: "inline-block w-[10px] h-[10px] border-2 border-solid border-[#111] border-t-transparent rounded-[50%]",
  stats:
    "m-0 border-2 border-solid border-[#111] rounded-[6px] bg-[#f5f9ff] overflow-hidden [&_dt]:py-[3px] [&_dt]:px-[8px] [&_dt]:bg-[#111] [&_dt]:text-[#67e8f9] [&_dt]:[font:800_10px_var(--font-lexend,'Lexend')] [&_dt]:tracking-[1.2px] [&_dt]:uppercase [&_dd]:m-0 [&_dd]:py-[6px] [&_dd]:px-[8px] [&_ol]:m-0 [&_ol]:pl-[18px] [&_ol]:[font:600_12px/1.6_var(--font-lexend,'Lexend')]",
  none: "[font:italic_600_12px_var(--font-lexend,'Lexend')] text-[#777]",
  sig: "flex items-baseline gap-[6px] min-h-[24px] pb-[2px] [border-bottom:2px_solid_#111]",
  lbl: "[font:800_10px_var(--font-lexend,'Lexend')] tracking-[1.2px] uppercase text-[#555]",
  sg: "[font:700_18px_var(--font-bricolage,'Bricolage_Grotesque'),cursive] text-[#0e7490]",
  ft: "flex items-center gap-[10px]",
  ib: `!inline-grid !place-items-center !flex-none !w-[40px] !h-[40px] !p-0 !border-2 !border-solid !border-[#111] !rounded-[10px] !bg-white !text-[#111] hover:!bg-white ${PRESS_MOTION}`,
  ibDel: `!inline-grid !place-items-center !flex-none !w-[40px] !h-[40px] !p-0 !border-2 !border-solid !border-[#111] !rounded-[10px] !bg-[#ef4444] !text-white hover:!bg-[#ef4444] hover:!text-white ${PRESS_MOTION}`,
  fb: "absolute left-[-14px] top-[22px] block py-[2px] px-[8px] bg-[#ef4444] text-white border-2 border-solid border-[#111] rounded-[4px] shadow-[2px_2px_0_#111] [font:800_14px_var(--font-lexend,'Lexend')] capitalize [rotate:-12deg] cursor-help",
  ghost:
    "grid place-items-center min-h-[300px] text-[#b9ae90] border-[3px] border-dashed border-[#b9ae90] rounded-[14px]",
  ghostFirst:
    "grid place-items-center min-h-[300px] border-[3px] border-dashed rounded-[14px] content-center justify-items-center gap-[14px] text-[#111] bg-white border-[#111] [&_p]:py-[4px] [&_p]:px-[14px] [&_p]:bg-[#ffe14d] [&_p]:border-[3px] [&_p]:border-solid [&_p]:border-[#111] [&_p]:rounded-[6px] [&_p]:shadow-[4px_4px_0_#111] [&_p]:[transform:rotate(-2deg)] [&_p]:[font:800_24px_var(--font-bricolage,'Bricolage_Grotesque'),system-ui]",
  spread:
    "grid grid-cols-[330px_minmax(0,1fr)] gap-[40px] items-start max-[960px]:grid-cols-[minmax(0,1fr)]",
  pack: "upload-tile relative flex flex-col items-center justify-center gap-[14px] h-[440px] max-[960px]:h-[260px] border-4 border-solid border-[#111] rounded-[14px_14px_18px_18px] shadow-[8px_8px_0_#111] [background:repeating-conic-gradient(from_0deg_at_50%_50%,#ff4d8d_0_10deg,#ff7aae_10deg_20deg)] [transform:rotate(-2deg)] cursor-pointer before:content-[''] after:content-[''] before:absolute after:absolute before:left-[-4px] after:left-[-4px] before:right-[-4px] after:right-[-4px] before:h-[22px] after:h-[22px] before:border-4 after:border-4 before:border-solid after:border-solid before:border-[#111] after:border-[#111] before:[background:repeating-linear-gradient(90deg,#fff_0_10px,#e5e7eb_10px_20px)] after:[background:repeating-linear-gradient(90deg,#fff_0_10px,#e5e7eb_10px_20px)] before:top-[-4px] before:rounded-[14px_14px_0_0] after:bottom-[-4px] after:rounded-[0_0_18px_18px]",
  disc: "upload-tile-disc grid place-items-center w-[130px] h-[130px] rounded-[50%] bg-[#ffe14d] border-4 border-solid border-[#111] shadow-[5px_5px_0_#111]",
  types:
    "flex gap-[8px] [&_i]:py-[2px] [&_i]:px-[8px] [&_i]:bg-white [&_i]:border-2 [&_i]:border-solid [&_i]:border-[#111] [&_i]:rounded-[4px] [&_i]:shadow-[2px_2px_0_#111] [&_i]:[font:normal_800_12px_var(--font-lexend,'Lexend')]",
  blank:
    "p-[14px] bg-[#67e8f9] border-[3px] border-solid border-[#111] rounded-[16px] shadow-[8px_8px_0_#111] [transform:rotate(0.8deg)]",
  in: "flex flex-col gap-[16px] p-[18px] bg-white border-[3px] border-solid border-[#111] rounded-[10px]",
  eb: "[font:800_12px_var(--font-lexend,'Lexend')] tracking-[2px] uppercase text-[#0e7490]",
  nm: "m-0 [font:800_30px_var(--font-bricolage,'Bricolage_Grotesque'),system-ui] [overflow-wrap:anywhere]",
  nmBig:
    "m-0 [font:800_24px_var(--font-bricolage,'Bricolage_Grotesque'),system-ui] [overflow-wrap:anywhere]",
  fl: "flex flex-col gap-[8px] [font:700_13px_var(--font-lexend,'Lexend')] [&>span:first-child]:text-[#111] [&>span:first-child]:[font:800_20px/1.1_var(--font-bricolage,'Bricolage_Grotesque'),system-ui] [&_input]:py-[10px] [&_input]:px-[12px] [&_input]:text-[#111] [&_input]:bg-white [&_input]:border-[3px] [&_input]:border-solid [&_input]:border-[#111] [&_input]:rounded-[10px] [&_input]:shadow-[3px_3px_0_#111] [&_input]:[font:500_15px_var(--font-lexend,'Lexend')] [&_input]:resize-y [&_textarea]:py-[10px] [&_textarea]:px-[12px] [&_textarea]:text-[#111] [&_textarea]:bg-white [&_textarea]:border-[3px] [&_textarea]:border-solid [&_textarea]:border-[#111] [&_textarea]:rounded-[10px] [&_textarea]:shadow-[3px_3px_0_#111] [&_textarea]:[font:500_15px_var(--font-lexend,'Lexend')] [&_textarea]:resize-y [&_select]:py-[10px] [&_select]:px-[12px] [&_select]:text-[#111] [&_select]:bg-white [&_select]:border-[3px] [&_select]:border-solid [&_select]:border-[#111] [&_select]:rounded-[10px] [&_select]:shadow-[3px_3px_0_#111] [&_select]:[font:500_15px_var(--font-lexend,'Lexend')] [&_select]:resize-y",
  page2:
    "py-[28px] px-[34px] bg-white [background-image:repeating-linear-gradient(0deg,transparent_0_31px,#dcebff_31px_33px)] border-[3px] border-solid border-[#111] rounded-[12px] shadow-[6px_6px_0_#111] [&_h1]:mt-0 [&_h1]:mx-0 [&_h1]:mb-[12px] [&_h1]:[font:800_30px_var(--font-bricolage,'Bricolage_Grotesque'),system-ui] [&_h2]:mt-[22px] [&_h2]:mx-0 [&_h2]:mb-[8px] [&_h2]:[font:800_20px_var(--font-bricolage,'Bricolage_Grotesque'),system-ui] [&_li]:[font:400_16px/1.6_var(--font-lexend,'Lexend')] [&_p]:[font:400_16px/1.6_var(--font-lexend,'Lexend')] [&_blockquote]:my-[14px] [&_blockquote]:mx-0 [&_blockquote]:py-[10px] [&_blockquote]:px-[14px] [&_blockquote]:bg-[#fff7cc] [&_blockquote]:border-2 [&_blockquote]:border-solid [&_blockquote]:border-[#111] [&_blockquote]:rounded-[8px] [&_blockquote]:shadow-[3px_3px_0_#111]",
} as const;

/** The album page class (the RAG page's <main>): dotted paper. */
export const ragAlbumClass = albumStyles.alb;

/** The ring binder down the album's left edge. */
export function AlbumRings() {
  return (
    <div className={albumStyles.rings} aria-hidden="true">
      {Array.from({ length: 7 }, (_, index) => (
        <i key={index} />
      ))}
    </div>
  );
}

/** Pink "+ New": the same accessible name as the old ModulePlus. */
export function AlbumPlus({
  label,
  onClick,
  disabled,
  busy,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  busy?: boolean;
}) {
  return (
    <Button
      className={WORKSPACE_ACTION_SIZE}
      aria-label={label}
      busy={busy}
      disabled={disabled}
      onClick={onClick}
    >
      {busy ? (
        <span className="spinner" aria-hidden="true" />
      ) : (
        <AlbumIcon name="plus" size={16} stroke={3} />
      )}
      <span aria-hidden="true">New</span>
    </Button>
  );
}

export function AlbumIconButton({
  icon,
  label,
  guide,
  danger,
  disabled,
  onClick,
}: {
  icon: keyof typeof PATHS;
  label: string;
  guide: string;
  danger?: boolean;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <Button
      variant="noShadow"
      size="icon"
      className={danger ? albumStyles.ibDel : albumStyles.ib}
      aria-label={label}
      data-ui-guide={guide}
      disabled={disabled}
      onClick={onClick}
    >
      <AlbumIcon name={icon} />
    </Button>
  );
}

export function fileExt(filename: string): string {
  const dot = filename.lastIndexOf(".");
  return dot >= 0 ? filename.slice(dot + 1).toUpperCase() : "";
}

/**
 * Agents using each RAG, read straight from the library list response
 * (`used_by_agents`, filled by GET /groups/{id}/knowledge-documents and
 * GET /courses/{id}/workspace-documents). No per-card request.
 */
export function ragAgents(document: KnowledgeDocument): AffectedAgent[] {
  return document.used_by_agents ?? [];
}

/** Last editor's username, else the uploader's; null leaves the line empty. */
export function lastEditor(document: KnowledgeDocument): string | null {
  return document.last_edited_by_username || document.owner_username || null;
}

/** Card B: art, plate (title, status, Used by, Last edited by), footer. */
export function RagCard({
  index,
  document,
  tone,
  agents,
  title,
  status,
  footer,
  badge,
  onOpen,
  openLabel,
}: {
  index: number;
  document: KnowledgeDocument;
  tone: "" | "failed" | "pending";
  agents: AffectedAgent[] | undefined;
  title: ReactNode;
  status: ReactNode;
  footer: ReactNode;
  badge: ReactNode;
  onOpen?: () => void;
  openLabel?: string;
}) {
  const t = useT();
  const editor = lastEditor(document);
  const used = agents ?? [];
  return (
    <li
      className={
        tone === "failed"
          ? albumStyles.cardFailed
          : tone === "pending"
            ? albumStyles.cardPending
            : albumStyles.card
      }
    >
      {onOpen ? (
        <button
          type="button"
          aria-label={openLabel ?? document.source_filename}
          className="absolute inset-0 z-0 cursor-pointer rounded-[inherit] border-0 bg-transparent p-0"
          onClick={onOpen}
        />
      ) : null}
      <div className="pointer-events-none relative z-[1]">
        <div className={albumStyles.art}>
          <span className={albumStyles.no} aria-hidden="true">
            #{String(index + 1).padStart(2, "0")}
          </span>
          <span className={albumStyles.ty} aria-hidden="true">
            {fileExt(document.source_filename)}
          </span>
          <span className={albumStyles.cnt} aria-hidden="true">
            {used.length}
          </span>
        </div>
        <div className={`${albumStyles.plate} pointer-events-auto`}>
          {title}
          {status}
          <dl className={albumStyles.stats}>
            <dt>{t("ragUsedBy")}</dt>
            <dd>
              {used.length ? (
                <ol>
                  {used.map((agent) => (
                    <li key={agent.agent_id}>{agent.name}</li>
                  ))}
                </ol>
              ) : (
                <span className={albumStyles.none}>{t("ragNoAgentsYet")}</span>
              )}
            </dd>
          </dl>
          <p className={albumStyles.sig}>
            <span className={albumStyles.lbl}>{t("ragLastEditedBy")}</span>{" "}
            {editor ? <span className={albumStyles.sg}>@{editor}</span> : null}
          </p>
        </div>
      </div>
      <div className={`${albumStyles.ft} pointer-events-auto relative z-[1]`}>
        {footer}
      </div>
      <span className="pointer-events-none relative z-[1]">{badge}</span>
    </li>
  );
}
