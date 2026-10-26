"use client";

import Link from "next/link";
import { useRef, useState, type ReactNode } from "react";

import { cn } from "../../lib/utils";
import { MascotFigure, MASCOT_IDS, type MascotId } from "../academy/mascots";
import { FitTitle } from "../fit-title";
import { IconClose } from "../quiet-icons";

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
export function agentTone(id: string) {
  let hash = 0;
  for (const char of id) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  return CARD_TONES[hash % CARD_TONES.length];
}

const FRAME_CLASS =
  "flex flex-1 flex-col overflow-hidden rounded-[9px] border-[3px] border-border bg-surface";
const BAND_CLASS =
  "relative z-[1] flex h-16 items-center border-b-[3px] border-border px-3 pr-10";

/** The round × that deletes; the existing confirm flow runs on click. */
function DeleteX({
  label,
  disabled,
  onClick,
}: {
  label: string;
  disabled?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={(event) => {
        event.preventDefault();
        event.stopPropagation();
        onClick();
      }}
      className="absolute -top-3 -right-3 z-[3] m-0 inline-grid size-8 min-h-0 cursor-pointer place-items-center rounded-full border-[3px] border-border bg-surface p-0 text-ink shadow-[2px_2px_0_#111] hover:bg-err hover:text-white focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-main disabled:cursor-not-allowed disabled:opacity-50"
    >
      <IconClose size={14} />
    </button>
  );
}

/** [V1.0 | Public] — green for Public, grey for Private. */
function VersionStrip({
  label,
  pending,
  visibility,
  visibilityLabel,
}: {
  label: string;
  pending: boolean;
  visibility?: "private" | "public";
  visibilityLabel?: string;
}) {
  return (
    <span
      className="relative z-[1] inline-flex w-fit overflow-hidden rounded-md border-2 border-border text-[11px] font-extrabold leading-none shadow-[2px_2px_0_#111]"
      data-pending={pending ? "true" : "false"}
      data-visibility={visibility}
    >
      <span
        className={cn(
          "bg-surface px-2.5 py-1",
          pending && "bg-warn-bg",
          visibilityLabel && "border-r-2 border-border",
        )}
      >
        {label}
      </span>
      {visibilityLabel ? (
        <span
          className={cn(
            "px-2.5 py-1",
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
}: {
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

  const tone = agentTone(id);
  const art = (
    <span
      data-card-art
      className="relative flex h-[150px] items-end justify-center border-b-[3px] border-border"
      style={{
        backgroundColor: tone,
        backgroundImage:
          "radial-gradient(circle at 50% 60%,#fff8 0 30%,transparent 31%),repeating-conic-gradient(from 0deg at 50% 60%,#fff6 0 10deg,transparent 10deg 20deg)",
      }}
      aria-hidden="true"
    >
      <MascotFigure id={mascot} className="h-[132px] w-auto" />
    </span>
  );
  const title = <FitTitle text={name} />;
  const titleClass =
    "block min-w-0 font-display text-[22px] font-extrabold leading-tight text-ink no-underline";
  const strip = (
    <span data-card-strip className="relative z-[1] flex flex-col items-start gap-1.5 p-2.5">
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
      />
    </span>
  );
  const foot = footer ? (
    <span
      data-card-footer
      className="pointer-events-none relative z-[1] mt-auto border-t-2 border-dashed border-[#11111144] px-2.5 py-1.5 text-[11px] font-medium text-[#333]"
    >
      {footer}
    </span>
  ) : null;

  return (
    <li className={CARD_CLASS} data-agent-card={id} data-tone={tone}>
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
          <span className={cn(FRAME_CLASS, "pointer-events-none")}>
            <span data-card-band className={cn(BAND_CLASS, "pointer-events-auto")} style={{ backgroundColor: tone }}>
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
                  className="m-0 h-10 w-full rounded-arc-s border-[3px] border-border bg-surface px-2.5 font-display text-lg font-extrabold text-ink shadow-[3px_3px_0_#FF4D8D] outline-none focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-main aria-invalid:border-err aria-invalid:bg-err-bg"
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
            FRAME_CLASS,
            "text-ink no-underline focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-main",
          )}
          data-ui-guide={guideText ? "agent.lastEdited" : undefined}
          data-ui-guide-text={guideText}
        >
          <span data-card-band className={BAND_CLASS} style={{ backgroundColor: tone }}>
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

/** Sunburst behind the empty card's mascot. */
function Sunburst() {
  return (
    <svg
      viewBox="0 0 200 200"
      className="absolute inset-0 size-full"
      aria-hidden="true"
      preserveAspectRatio="xMidYMid slice"
    >
      {Array.from({ length: 16 }, (_, index) => (
        <path
          key={index}
          d="M100 100 L92 -40 L108 -40 Z"
          fill="#ffffff66"
          transform={`rotate(${index * 22.5} 100 100)`}
        />
      ))}
    </svg>
  );
}

/**
 * Canonical empty state: a lime card that says so and holds New, then dashed
 * ghost slots (with ghost ×) showing where the cards will go.
 */
export function AgentsEmpty({
  title,
  newHref,
  newLabel,
  ghosts = 3,
}: {
  title: string;
  newHref?: string;
  newLabel: string;
  ghosts?: number;
}) {
  return (
    <ul className={AGENT_GRID_CLASS}>
      <li className="relative flex min-h-[248px] flex-col rounded-[14px] border-[3px] border-border bg-studyform p-2 font-body text-ink shadow-[6px_6px_0_#111]">
        <div className="flex flex-1 flex-col overflow-hidden rounded-[9px] border-[3px] border-border bg-studyform">
          <p className="m-0 flex h-16 items-center border-b-[3px] border-border px-3 font-display text-xl font-extrabold">
            {title}
          </p>
          <div className="relative grid min-h-[200px] flex-1 place-items-center p-5">
            <Sunburst />
            {newHref ? (
              <Link
                href={newHref}
                aria-label={newLabel}
                data-tour="new"
                data-tour-empty="true"
                className="relative inline-flex h-10 items-center rounded-arc-s border-[3px] border-border bg-main px-5 font-display text-base font-extrabold text-ink no-underline shadow-arc-s transition-transform hover:translate-x-[3px] hover:translate-y-[3px] hover:shadow-none focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-ink"
              >
                {newLabel}
              </Link>
            ) : null}
          </div>
        </div>
      </li>
      {Array.from({ length: ghosts }, (_, index) => (
        <GhostSlot key={index} narrowHidden={index > 0} />
      ))}
    </ul>
  );
}

/** A dashed placeholder card: grey skeleton of where an Agent will sit. */
function GhostSlot({ narrowHidden }: { narrowHidden: boolean }) {
  return (
    <li
      aria-hidden="true"
      className={cn(
        "relative flex min-h-[248px] flex-col rounded-[14px] border-[3px] border-dashed border-[#11111133] p-2",
        narrowHidden && "max-[680px]:hidden",
      )}
    >
      <span className="flex flex-1 flex-col rounded-[9px] border-[3px] border-dashed border-[#11111155]">
        <span className="flex h-16 items-center border-b-[3px] border-dashed border-[#11111133] px-3">
          <span className="block h-3 w-3/5 rounded-full bg-[#0000000f]" />
        </span>
        <span className="flex h-[150px] items-end justify-center border-b-[3px] border-dashed border-[#11111133]">
          <span className="block h-[96px] w-[72px] rounded-t-full bg-[#0000000f]" />
        </span>
        <span className="flex p-2.5">
          <span className="inline-flex h-5 overflow-hidden rounded-md border-2 border-dashed border-[#11111133]">
            <span className="w-11" />
            <span className="w-14 border-l-2 border-dashed border-[#11111133] bg-[#0000000a]" />
          </span>
        </span>
        <span className="mt-auto block border-t-2 border-dashed border-[#11111122] px-2.5 py-2">
          <span className="block h-2 w-[70%] rounded-full bg-[#0000000f]" />
        </span>
      </span>
      <span className="absolute -top-3 -right-3 size-8 rounded-full border-[3px] border-dashed border-[#11111133] bg-surface" />
    </li>
  );
}

/** Header New: the page's New button next to the page title. */
export function NewButton({
  href,
  label,
  className,
}: {
  href: string;
  label: string;
  className?: string;
}) {
  return (
    <Link
      href={href}
      aria-label={label}
      data-tour="new"
      className={cn(
        "inline-flex h-10 items-center rounded-full border-[3px] border-border bg-main px-5 font-display text-base font-extrabold text-ink no-underline shadow-arc-s transition-transform hover:translate-x-[3px] hover:translate-y-[3px] hover:shadow-none focus-visible:outline-[3px] focus-visible:outline-offset-2 focus-visible:outline-ink",
        className,
      )}
    >
      {label}
    </Link>
  );
}
