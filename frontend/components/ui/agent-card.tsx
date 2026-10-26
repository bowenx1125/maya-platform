"use client";

import Image from "next/image";
import Link from "next/link";
import { useRef, useState, type ReactNode } from "react";

import { cn } from "../../lib/utils";
import { MascotFigure, MASCOT_IDS, type MascotId } from "../academy/mascots";
import { FitTitle } from "../fit-title";
import { IconPlus } from "../quiet-icons";
import { buttonVariants } from "./button";
import { KindSticker, RoundX } from "./error-kit";

/** Material theme of the Agent's avatar → the mascot on its card. */
const THEME_MASCOT: Record<string, MascotId> = {
  demo: "wave",
  warm_sand: "wreath",
  cool_slate: "scroll",
  civic_olive: "tablet",
};

/** The avatar's theme picks the mascot; otherwise the id hashes to one. */
export function agentMascot(id: string, materialTheme?: string | null) {
  const themed = materialTheme ? THEME_MASCOT[materialTheme] : undefined;
  if (themed) return themed;
  let hash = 0;
  for (const char of id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return MASCOT_IDS[hash % MASCOT_IDS.length];
}

export const AGENT_GRID_CLASS =
  "m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(220px,1fr))] gap-5 p-0 pt-4 pr-4 pb-5 max-[680px]:grid-cols-1 max-[680px]:gap-4";

const CARD_CLASS =
  "group/card relative flex min-h-[248px] flex-col overflow-visible rounded-[14px] border-[3px] border-border bg-surface p-2 font-body text-ink shadow-[6px_6px_0_#111] transition-[transform,box-shadow] duration-150 hover:-translate-y-0.5 focus-within:-translate-y-0.5";

/** Card tones: salmon, periwinkle, sage — title band and sunburst share one. */
const CARD_TONES = ["#F2B79A", "#C9D3F0", "#C9D9A0"] as const;

/** Deterministic tone per Agent id. */
export function agentTone(id: string, index?: number) {
  // A list passes its position so the tones cycle as the mocks draw them.
  if (index !== undefined) return CARD_TONES[index % CARD_TONES.length];
  let hash = 0;
  for (const char of id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return CARD_TONES[hash % CARD_TONES.length];
}

/** Card A on the Agents page (r2-list.mjs .tcA): one frame, 186px wide. */
const CARD_A_CLASS =
  "group/card relative block w-[186px] list-none p-0 font-body text-ink max-[767px]:w-auto";
const FRAME_A_CLASS =
  "flex flex-col overflow-hidden rounded-[12px] border-[3px] border-[#111] bg-white shadow-[5px_5px_0_#111]";
const BAND_A_CLASS =
  "relative z-[1] box-border flex h-16 items-center border-b-[3px] border-[#111] pr-[30px] pl-[27px]";
const TITLE_A_CLASS =
  "line-clamp-2 min-w-0 wrap-break-word text-left font-display text-[17px] leading-[1.15] font-extrabold text-[#111] no-underline";

const FRAME_CLASS =
  "flex flex-1 flex-col overflow-hidden rounded-[9px] border-[3px] border-border bg-surface";
const BAND_CLASS =
  "relative z-[1] flex h-16 items-center border-b-[3px] border-border px-3 pr-10";

/** The round × that deletes; the existing confirm flow runs on click. */
export function DeleteX({
  label,
  disabled,
  onClick,
}: {
  label: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <RoundX
      aria-label={label}
      disabled={disabled}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        onClick();
      }}
      className="absolute -top-3 -right-3 z-[3]"
    />
  );
}

/** [V1.0 | Public] — green for Public, grey for Private. */
function VersionStrip({
  label,
  pending,
  visibility,
  visibilityLabel,
  list = false,
}: {
  label: string;
  pending: boolean;
  visibility?: "private" | "public";
  visibilityLabel?: string;
  /** Card A: 1px 8px cells. */
  list?: boolean;
}) {
  const cell = list ? "px-2 py-px leading-[normal]" : "px-2.5 py-1";
  return (
    <span
      className="relative z-[1] inline-flex w-fit overflow-hidden rounded-md border-2 border-border text-[11px] font-extrabold leading-none shadow-[2px_2px_0_#111]"
      data-pending={pending ? "true" : "false"}
      data-visibility={visibility}
    >
      <span
        className={cn(
          "bg-surface",
          cell,
          pending && "bg-warn-bg",
          visibilityLabel && "border-r-2 border-border",
        )}
      >
        {label}
      </span>
      {visibilityLabel ? (
        <span
          className={cn(
            cell,
            visibility === "public" ? "bg-[#22C55E]" : "bg-[#E5E7EB]",
          )}
        >
          {visibilityLabel}
        </span>
      ) : null}
    </span>
  );
}

export type AgentRename = {
  /** Accessible name of the name field ("Name"). */
  fieldLabel: string;
  /**
   * Saves the new name; resolves false when it failed (the page shows the
   * error in the notice tray and the field opens again with the typed name).
   */
  onRename: (name: string) => Promise<boolean>;
  /** The error from the last save, shown by the page in the notice tray. */
  errorId?: string;
  invalid?: boolean;
  /** The field is handed to the caller so focus can go back to it. */
  bindInput?: (input: HTMLInputElement | null) => void;
};

/**
 * One Agent (or Team) card: the mascot, the title (inline rename when the
 * viewer may edit), the version/visibility strip, "Last edited by", and the
 * round × when deleting is allowed. The whole card opens the Agent.
 */
export function AgentCard({
  id,
  name,
  href,
  label,
  pending,
  visibility,
  visibilityLabel,
  mascot,
  footer,
  caption,
  guideText,
  deleting = false,
  onDelete,
  deleteLabel,
  rename,
  variant,
  index,
}: {
  /** "list": card A of the Agents page. */
  variant?: "list";
  id: string;
  name: string;
  href: string;
  label: string;
  pending: boolean;
  visibility?: "private" | "public";
  visibilityLabel?: string;
  mascot: MascotId;
  footer?: ReactNode;
  /** A short line above the version strip (e.g. the team on teacher Home). */
  caption?: ReactNode;
  /** ui-guide hover help (last editor). */
  guideText?: string;
  deleting?: boolean;
  onDelete?: () => void;
  deleteLabel: string;
  rename?: AgentRename;
  /** Position in the list; cycles the tone. */
  index?: number;
}) {
  // Read once so the field's ref callback is not mistaken for the object.
  const bindInput = rename?.bindInput;
  const renameInvalid = rename?.invalid ?? false;
  const renameErrorId = rename?.errorId;
  const fieldLabel = rename?.fieldLabel;
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(name);
  const composing = useRef(false);
  const settled = useRef(false);

  function startEditing() {
    settled.current = false;
    setDraft(name);
    setEditing(true);
  }

  async function save() {
    if (settled.current) return;
    settled.current = true;
    setEditing(false);
    const next = draft.trim();
    if (!rename || next === name) return;
    const saved = await rename.onRename(next);
    if (!saved) {
      settled.current = false;
      setDraft(next);
      setEditing(true);
    }
  }

  const tone = agentTone(id, index);
  const listCard = variant === "list";
  const art = (
    <span
      data-card-art
      className={cn(
        "relative flex h-[150px] items-end justify-center border-b-[3px] border-border",
        listCard && "border-[#111] max-[767px]:h-[120px]",
      )}
      style={{
        backgroundColor: tone,
        backgroundImage:
          "radial-gradient(circle at 50% 60%,#fff8 0 30%,transparent 31%),repeating-conic-gradient(from 0deg at 50% 60%,#fff6 0 10deg,transparent 10deg 20deg)",
      }}
      aria-hidden="true"
    >
      <MascotFigure
        id={mascot}
        className={cn("h-[132px] w-auto", listCard && "max-[767px]:h-[104px]")}
      />
    </span>
  );
  const title = listCard ? name : <FitTitle text={name} />;
  const titleClass = listCard
    ? TITLE_A_CLASS
    : "block min-w-0 font-display text-[22px] font-extrabold leading-tight text-ink no-underline";
  const strip = (
    <span
      data-card-strip
      className={cn(
        "relative z-[1] flex flex-col items-start gap-1.5 p-2.5",
        listCard && "flex-row items-center gap-[5px] px-2.5 py-2",
      )}
    >
      {caption ? (
        <span className="max-w-full truncate text-[11px] font-bold text-[#333]">
          {caption}
        </span>
      ) : null}
      <VersionStrip
        label={label}
        pending={pending}
        visibility={visibility}
        visibilityLabel={visibilityLabel}
        list={listCard}
      />
    </span>
  );
  const foot = footer ? (
    <span
      data-card-footer
      className={
        listCard
          ? "pointer-events-none relative z-[1] mx-2.5 block border-0 border-t-2 border-dashed border-[#1116] pt-[7px] pb-[9px] text-left text-[11px] font-medium text-[#111] [line-height:normal]"
          : "pointer-events-none relative z-[1] mt-auto border-t-2 border-dashed border-[#11111144] px-2.5 py-1.5 text-[11px] font-medium text-[#333]"
      }
    >
      {footer}
    </span>
  ) : null;

  return (
    <li
      className={listCard ? CARD_A_CLASS : CARD_CLASS}
      data-agent-card={id}
      data-tone={tone}
    >
      {rename ? (
        <>
          {/* Covers the card so anywhere opens it; the title stays above. */}
          <Link
            href={href}
            aria-label={name}
            className="absolute inset-0 z-0 rounded-[14px] focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-main"
            data-ui-guide={guideText ? "agent.lastEdited" : undefined}
            data-ui-guide-text={guideText}
          />
          {/* A failed rename is a server error: the black "!" of its bubble,
              on the card corner so the frame's overflow cannot clip it. */}
          {renameInvalid ? <KindSticker kind="server" on /> : null}
          <span
            className={cn(
              listCard ? FRAME_A_CLASS : FRAME_CLASS,
              "pointer-events-none",
            )}
          >
            <span
              data-card-band
              className={cn(
                listCard ? BAND_A_CLASS : BAND_CLASS,
                "pointer-events-auto",
              )}
              style={{ backgroundColor: tone }}
            >
              {editing ? (
                <input
                  ref={bindInput}
                  autoFocus
                  aria-label={fieldLabel}
                  aria-invalid={renameInvalid || undefined}
                  aria-describedby={renameInvalid ? renameErrorId : undefined}
                  maxLength={120}
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onCompositionStart={() => (composing.current = true)}
                  onCompositionEnd={() => (composing.current = false)}
                  onBlur={() => {
                    // After a failed save, leaving the field (e.g. to Dismiss
                    // the error) keeps it open; Enter retries, Esc cancels.
                    if (!renameInvalid) void save();
                  }}
                  onKeyDown={(event) => {
                    if (composing.current || event.nativeEvent.isComposing)
                      return;
                    if (event.key === "Enter") {
                      event.preventDefault();
                      void save();
                    } else if (event.key === "Escape") {
                      event.preventDefault();
                      settled.current = true;
                      setEditing(false);
                    }
                  }}
                  className="m-0 h-10 w-full rounded-arc-s border-[3px] border-border bg-surface px-2.5 font-display text-lg font-extrabold text-ink shadow-[3px_3px_0_#FF4D8D] outline-none focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-main aria-invalid:border-err aria-invalid:bg-surface aria-invalid:shadow-[0_0_0_3px_#FFE4E4,3px_3px_0_#EF4444]"
                />
              ) : (
                <button
                  type="button"
                  className={cn(
                    titleClass,
                    "-mx-1 m-0 min-h-0 max-w-full cursor-text rounded-md border-0 bg-transparent px-1 py-0.5 text-left shadow-none hover:outline-2 hover:outline-dashed hover:outline-ink",
                    renameInvalid && "outline-[3px] outline-err",
                  )}
                  aria-describedby={renameInvalid ? renameErrorId : undefined}
                  onClick={startEditing}
                >
                  {title}
                </button>
              )}
            </span>
            {art}
            {strip}
            {foot}
          </span>
        </>
      ) : (
        <Link
          href={href}
          aria-label={name}
          className={cn(
            listCard ? FRAME_A_CLASS : FRAME_CLASS,
            "text-ink no-underline focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-main",
          )}
          data-ui-guide={guideText ? "agent.lastEdited" : undefined}
          data-ui-guide-text={guideText}
        >
          <span
            data-card-band
            className={listCard ? BAND_A_CLASS : BAND_CLASS}
            style={{ backgroundColor: tone }}
          >
            <span className={titleClass}>{title}</span>
          </span>
          {art}
          {strip}
          {foot}
        </Link>
      )}
      {onDelete ? (
        <DeleteX label={deleteLabel} disabled={deleting} onClick={onDelete} />
      ) : null}
    </li>
  );
}

/**
 * E2 Spotlight empty state (r2-list.mjs .eE2): a 250px yellow card A holds
 * the existing empty copy and "+ New"; two dashed card-A ghosts fan out
 * behind at ±170px, ±8deg, over a pale sun.
 */
export function AgentsEmpty({
  title,
  newHref,
  newLabel,
}: {
  title: string;
  newHref?: string;
  newLabel: string;
  /** Kept for callers; E2 always shows two fanned ghosts. */
  ghosts?: number;
}) {
  return (
    <div className="block [background:radial-gradient(ellipse_at_50%_100%,#FFE14D55_0_30%,transparent_31%)]">
      <div className="relative flex h-[470px] items-start justify-center pt-[18px] max-[767px]:h-[420px]">
        <GhostSlot fan="left" art="/agents/ghost-m1.webp" />
        <GhostSlot fan="right" art="/agents/ghost-m3.webp" />
        <div className="relative z-[2] box-border w-[250px] overflow-hidden rounded-[12px] border-[3px] border-[#111] bg-white shadow-[8px_8px_0_#111] max-[767px]:w-[220px]">
          <div className="flex h-[78px] items-center border-b-[3px] border-[#111] bg-[#FFE14D] px-3">
            <p className="m-0 text-left font-display text-2xl font-extrabold text-[#111]">
              {title}
            </p>
          </div>
          <div className="grid h-[220px] place-items-center bg-[#FF4D8D33] [background-image:radial-gradient(circle_at_50%_50%,#fff9_0_30%,transparent_31%),repeating-conic-gradient(from_0deg_at_50%_50%,#FFE14D88_0_10deg,transparent_10deg_20deg)]" />
          <div className="flex justify-center border-t-[3px] border-[#111] p-4">
            {newHref ? (
              <Link
                href={newHref}
                aria-label={newLabel}
                data-tour="new"
                data-tour-empty="true"
                className={AGENTS_NEW_CLASS}
              >
                <IconPlus size={16} />
                {newLabel}
              </Link>
            ) : null}
          </div>
        </div>
      </div>
    </div>
  );
}

/**
 * A dashed card-A ghost fanned behind the spotlight card. As rendered in the
 * approved E2 mock, its parts sit in one row (band, art, strip, rule).
 */
function GhostSlot({
  fan,
  art,
}: {
  fan: "left" | "right";
  /** The E2 mock's own silhouette art (proposals m1 / m3). */
  art: string;
}) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "absolute top-11 box-border flex w-[186px] rounded-[12px] border-[3px] border-dashed border-[#1155] bg-white max-[767px]:w-[150px]",
        fan === "left"
          ? "translate-x-[-170px] rotate-[-8deg] max-[767px]:translate-x-[-90px]"
          : "translate-x-[170px] rotate-[8deg] max-[767px]:translate-x-[90px]",
      )}
    >
      <div className="flex h-16 items-center border-0 border-b-[3px] border-dashed border-[#1133] px-3">
        <i
          className={cn(
            "block h-3 w-1 rounded-[4px] bg-[#111]",
            // Per-breakpoint nudge so the tick lands where the E2 mock draws it.
            fan === "left" &&
              "translate-x-[5px] translate-y-[41px] max-[767px]:translate-x-[6px] max-[767px]:translate-y-[27px]",
          )}
        />
      </div>
      <div className="flex h-[150px] items-end justify-center border-0 border-b-[3px] border-dashed border-[#1133] [background:repeating-conic-gradient(from_0deg_at_50%_60%,#11111100_0_10deg,#1111110d_10deg_20deg)] max-[767px]:h-[120px]">
        <Image
          src={art}
          alt=""
          width={256}
          height={256}
          className="h-[132px] w-auto opacity-[.08] brightness-0 max-[767px]:h-[104px]"
        />
      </div>
      <div className="mx-2.5 my-2 flex">
        <i className="block h-4 w-[38px] rounded-[5px] border-2 border-dashed border-[#1133]" />
        <i className="block h-4 w-[50px] rounded-[5px] border-2 border-l-0 border-dashed border-[#1133]" />
      </div>
      <div className="mx-2.5 border-0 border-t-2 border-dashed border-[#1122] pt-[7px] pb-2.5">
        <i
          className={cn(
            "block h-2 w-1 rounded-[4px] bg-[#111]",
            fan === "right" &&
              "translate-x-[24px] translate-y-[60px] max-[767px]:translate-x-[24px] max-[767px]:translate-y-[46px]",
          )}
        />
      </div>
      <span className="absolute -top-[11px] -right-[11px] size-[26px] rounded-full border-[3px] border-dashed border-[#1144] bg-white" />
    </div>
  );
}

/** "+ New" on the Agents page (R2 .newbtn: shared Button default). */
export const AGENTS_NEW_CLASS =
  "box-border inline-flex h-10 items-center gap-1.5 rounded-[10px] border-[3px] border-[#111] bg-[#FF4D8D] px-4 font-body text-sm leading-none font-bold text-[#111] no-underline shadow-[6px_6px_0_#111] [&_svg]:size-4 [&_svg]:stroke-3";

/** Header New: the page's New button next to the page title ("+ New"). */
export function NewButton({
  href,
  label,
  className,
  tour = true,
}: {
  href: string;
  label: string;
  className?: string;
  tour?: boolean;
}) {
  return (
    <Link
      href={href}
      aria-label={label}
      data-tour={tour ? "new" : undefined}
      className={cn(
        buttonVariants({ variant: "default" }),
        "gap-1.5 font-display text-base font-extrabold no-underline",
        className,
      )}
    >
      <IconPlus size={16} />
      {label}
    </Link>
  );
}
