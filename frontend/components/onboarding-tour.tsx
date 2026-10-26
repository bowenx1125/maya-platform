"use client";

import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type CSSProperties,
} from "react";
import { createPortal } from "react-dom";
import {
  inSidebar,
  revealSidebar,
  sidebarIsDrawer,
} from "../lib/sidebar-reveal";

import type { MessageKey } from "../lib/i18n";
import { finishTour, tourPendingFor } from "../lib/onboarding";
import { usePrefersReducedMotion } from "./academy/motion";
import { useT } from "../lib/i18n";
import { cn } from "../lib/utils";
import { Button } from "./ui/button";
import { GuideDialog, GuideHud } from "./ui/guide-dialog";

type Page = "home" | "group";
type Step = {
  id: string;
  target: string | null;
  title: MessageKey;
  body: MessageKey;
  /** Where the step is shown; the tour walks there itself. */
  page: Page;
  /** Shown instead when the Agents page has no Agents yet. */
  empty?: { title: MessageKey; body: MessageKey };
};

/** The walk round a new student's first home, in the order they will need it. */
const STEPS: Step[] = [
  {
    id: "welcome",
    target: null,
    title: "tourWelcomeTitle",
    body: "tourWelcomeBody",
    page: "home",
  },
  {
    id: "knowledge",
    target: '[data-tour="knowledge"]',
    title: "tourStudyformTitle",
    body: "tourStudyformBody",
    page: "home",
  },
  {
    // Step 3 of 9 opens the group's Agents page and points at its New.
    id: "new",
    target: '[data-tour="new"]',
    title: "tourNewTitle",
    body: "tourNewBody",
    page: "group",
    empty: { title: "tourNewEmptyTitle", body: "tourNewEmptyBody" },
  },
  {
    id: "brain",
    target: '[data-tour="brain"]',
    title: "tourBrainformTitle",
    body: "tourBrainformBody",
    page: "group",
  },
  {
    id: "chat",
    target: '[data-tour="chat"]',
    title: "tourChatformTitle",
    body: "tourChatformBody",
    page: "group",
  },
  {
    id: "live",
    target: '[data-tour="live"]',
    title: "tourLiveTitle",
    body: "tourLiveBody",
    page: "home",
  },
  {
    id: "guide",
    target: '[data-tour="guide"]',
    title: "tourGuideTitle",
    body: "tourGuideBody",
    page: "home",
  },
  {
    id: "group",
    target: '[data-tour="group"]',
    title: "tourGroupTitle",
    body: "tourGroupBody",
    page: "home",
  },
  {
    id: "profile",
    target: ".account-settings-card",
    title: "tourProfileTitle",
    body: "tourProfileBody",
    page: "home",
  },
];

/** The tour's place survives the walk between pages (and a reload). */
const STATE = "maya.tour.state";
type Saved = { ids: string[]; index: number; groupHref: string | null };

function readSaved(): Saved | null {
  try {
    const raw = window.sessionStorage.getItem(STATE);
    const saved = raw ? (JSON.parse(raw) as Saved) : null;
    return saved && Array.isArray(saved.ids) ? saved : null;
  } catch {
    return null;
  }
}

function writeSaved(saved: Saved | null) {
  try {
    if (saved) window.sessionStorage.setItem(STATE, JSON.stringify(saved));
    else window.sessionStorage.removeItem(STATE);
  } catch {
    // Private mode: the tour simply starts over on a reload.
  }
}

/** The group's Agents page, read from the Studyform link in the sidebar. */
function groupPageHref(): string | null {
  const link = document.querySelector<HTMLAnchorElement>(
    '[data-tour="knowledge"]',
  );
  const href = link?.getAttribute("href") ?? "";
  // #280: Studyform's Agents item opens /student/agents?group_id=…, where
  // the E2 empty card (and its New) now lives.
  return href.includes("/student/groups/") ||
    href.startsWith("/student/agents?group_id=")
    ? href.split("#")[0]
    : null;
}

function onPage(page: Page, pathname: string) {
  return page === "group"
    ? pathname.startsWith("/student/groups/") || pathname === "/student/agents"
    : pathname === "/student" || pathname === "/student/";
}

/** Room left round the highlighted place, and between it and the card. */
const HALO = 8;
const GAP = 22;
const EDGE = 12;

type Side = "right" | "left" | "below" | "above" | null;
type Box = { top: number; left: number; width: number; height: number };

function shown(element: Element | null): element is HTMLElement {
  if (!(element instanceof HTMLElement)) return false;
  const box = element.getBoundingClientRect();
  return box.width > 0 && box.height > 0 && box.right > 0;
}

/**
 * Put the card beside a narrow target on the left (the sidebar), else below
 * it, else above it, else beside it on its left, else over its lower edge;
 * and point the arrow at the target's middle.
 */
export function place(
  target: Box | null,
  card: { width: number; height: number },
  viewport: { width: number; height: number },
): { left: number; top: number; side: Side; arrow: number } {
  const clamp = (value: number, low: number, high: number) =>
    Math.min(Math.max(value, low), Math.max(low, high));
  if (!target)
    return {
      left: (viewport.width - card.width) / 2,
      top: (viewport.height - card.height) / 2,
      side: null,
      arrow: 0,
    };
  const middleX = target.left + target.width / 2;
  const middleY = target.top + target.height / 2;
  const centred = clamp(
    middleX - card.width / 2,
    EDGE,
    viewport.width - card.width - EDGE,
  );
  const right = target.left + target.width + GAP;
  if (
    target.width < viewport.width / 3 &&
    right + card.width + EDGE <= viewport.width
  ) {
    const top = clamp(
      middleY - card.height / 2,
      EDGE,
      viewport.height - card.height - EDGE,
    );
    return { left: right, top, side: "right", arrow: middleY - top };
  }
  const below = target.top + target.height + GAP;
  if (below + card.height + EDGE <= viewport.height)
    return {
      left: centred,
      top: below,
      side: "below",
      arrow: middleX - centred,
    };
  const above = target.top - GAP - card.height;
  if (above >= EDGE)
    return {
      left: centred,
      top: above,
      side: "above",
      arrow: middleX - centred,
    };
  const left = target.left - GAP - card.width;
  if (left >= EDGE) {
    const top = clamp(
      middleY - card.height / 2,
      EDGE,
      viewport.height - card.height - EDGE,
    );
    return { left, top, side: "left", arrow: middleY - top };
  }
  return {
    left: centred,
    top: viewport.height - card.height - EDGE,
    side: null,
    arrow: 0,
  };
}

/**
 * Shows the tour once, to an account that has just registered. It is mounted
 * by the app shell, so it keeps going while it walks between pages.
 */
export function OnboardingTour({
  userId,
  pathname,
  navigate,
  startHere = true,
}: {
  userId: string;
  /** The current path; falls back to the window's. */
  pathname?: string;
  /** Client-side navigation; falls back to a full page load. */
  navigate?: (href: string) => void;
  /** A new tour starts only on the home it points at. */
  startHere?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const path =
    pathname ?? (typeof window === "undefined" ? "" : window.location.pathname);
  useEffect(() => {
    // A tour already under way picks up where it was.
    if (readSaved()) {
      const resume = window.setTimeout(() => setOpen(true), 0);
      return () => window.clearTimeout(resume);
    }
    if (!startHere) return;
    // Wait for the home to lay out: the tour points at what is on it.
    const timer = window.setTimeout(() => {
      // ?tour replays it, for showing someone round.
      const replay = new URLSearchParams(window.location.search).has("tour");
      if (replay || tourPendingFor(userId)) setOpen(true);
    }, 600);
    return () => window.clearTimeout(timer);
  }, [startHere, userId]);
  const close = useCallback(() => {
    finishTour();
    writeSaved(null);
    setOpen(false);
  }, []);
  const go = useCallback(
    (href: string) => {
      if (navigate) navigate(href);
      else window.location.assign(href);
    },
    [navigate],
  );
  return open
    ? createPortal(
        <Tour onClose={close} pathname={path} navigate={go} />,
        document.body,
      )
    : null;
}

function reachable(element: Element | null) {
  return shown(element) || (inSidebar(element) && sidebarIsDrawer());
}

function startSteps(): Saved {
  const groupHref = groupPageHref();
  // Places this screen does not show (a student with no group yet) are left
  // out rather than pointed at in thin air. The phone's sidebar drawer counts
  // as shown: the step opens it.
  // Steps on the group's page are kept when there is a group to open.
  const ids = STEPS.filter((step) => {
    if (!step.target) return true;
    if (step.page === "group") {
      if (!groupHref) return false;
      return (
        step.id === "new" || reachable(document.querySelector(step.target))
      );
    }
    return reachable(document.querySelector(step.target));
  }).map((step) => step.id);
  return { ids, index: 0, groupHref };
}

function Tour({
  onClose,
  pathname,
  navigate,
}: {
  onClose: () => void;
  pathname: string;
  navigate: (href: string) => void;
}) {
  const t = useT();
  const reduced = usePrefersReducedMotion();
  const [saved, setSaved] = useState<Saved>(() => readSaved() ?? startSteps());
  const steps = saved.ids
    .map((id) => STEPS.find((step) => step.id === id))
    .filter((step): step is Step => Boolean(step));
  const index = Math.min(saved.index, steps.length - 1);
  const [target, setTarget] = useState<Box | null>(null);
  const [empty, setEmpty] = useState(false);
  const [card, setCard] = useState({ width: 560, height: 220 });
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  const cardRef = useRef<HTMLDivElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const step = steps[index];
  const last = index === steps.length - 1;
  const here = !step || onPage(step.page, pathname) || !pathname;

  useEffect(() => writeSaved(saved), [saved]);

  // Walk to the page the step is on (Back walks back the same way).
  useEffect(() => {
    if (!step || here) return;
    const href = step.page === "group" ? saved.groupHref : "/student";
    if (href) navigate(href);
  }, [here, navigate, saved.groupHref, step]);

  // Follow the highlighted place as the page scrolls or the window resizes;
  // after a walk, wait for it to appear.
  useLayoutEffect(() => {
    if (!step || !here) return;
    let element: HTMLElement | null = null;
    let frame = 0;
    let tries = 0;
    let poll = 0;
    let settle = 0;
    let revealed = false;
    const measure = () => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        setViewport({ width: window.innerWidth, height: window.innerHeight });
        const box = element?.getBoundingClientRect();
        setTarget(
          box
            ? {
                top: box.top - HALO,
                left: box.left - HALO,
                width: box.width + HALO * 2,
                height: box.height + HALO * 2,
              }
            : null,
        );
        const own = cardRef.current;
        if (own) setCard({ width: own.offsetWidth, height: own.offsetHeight });
      });
    };
    const find = () => {
      element = step.target
        ? document.querySelector<HTMLElement>(step.target)
        : null;
      if (step.target && !element && tries++ < 40) {
        poll = window.setTimeout(find, 100);
        return;
      }
      if (element && inSidebar(element) && sidebarIsDrawer()) {
        // Open the phone's drawer for this step, then measure once it has
        // slid in; the cleanup below closes it again.
        revealed = true;
        revealSidebar(true);
        settle = window.setTimeout(measure, 220);
      }
      setEmpty(element?.hasAttribute("data-tour-empty") ?? false);
      element?.scrollIntoView({
        block: "center",
        behavior: reduced ? "auto" : "smooth",
      });
      measure();
    };
    find();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      cancelAnimationFrame(frame);
      window.clearTimeout(poll);
      window.clearTimeout(settle);
      if (revealed) revealSidebar(false);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [step, here, reduced]);

  useEffect(() => {
    nextRef.current?.focus();
  }, [index]);

  // Give focus back to wherever it was once the tour is over.
  useEffect(() => {
    const before = document.activeElement;
    return () => {
      if (before instanceof HTMLElement) before.focus();
    };
  }, []);

  const next = useCallback(() => {
    if (last) onClose();
    else setSaved((current) => ({ ...current, index: current.index + 1 }));
  }, [last, onClose]);
  const back = useCallback(
    () =>
      setSaved((current) => ({
        ...current,
        index: Math.max(0, current.index - 1),
      })),
    [],
  );

  useEffect(() => {
    const keys = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      else if (event.key === "ArrowRight") next();
      else if (event.key === "ArrowLeft") back();
      else if (event.key === "Tab") {
        // Focus stays on the card: the page behind it is not in play.
        const buttons = cardRef.current?.querySelectorAll("button");
        if (!buttons?.length) return;
        const first = buttons[0];
        const final = buttons[buttons.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          final.focus();
        } else if (!event.shiftKey && document.activeElement === final) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", keys);
    return () => window.removeEventListener("keydown", keys);
  }, [back, next, onClose]);

  if (!step) return null;
  const words = empty && step.empty ? step.empty : step;
  const spot = place(target, card, viewport);
  const ready = viewport.width > 0 && here;
  const glide = reduced
    ? ""
    : "transition-[top,left,width,height] duration-[460ms] ease-[cubic-bezier(0.2,0.8,0.2,1)]";
  return (
    <div
      className={cn(
        "fixed inset-0 z-[2147482000] font-body opacity-0 transition-opacity duration-200 data-[ready]:opacity-100",
      )}
      data-ready={ready ? "" : undefined}
    >
      {/* Clicks on the dimmed page are caught here: like a game's first
          level, the way on is the card's Next. */}
      <div className="absolute inset-0" aria-hidden="true" />
      <div
        className={cn(
          "pointer-events-none absolute rounded-[14px]",
          target
            ? "outline-[4px] outline-offset-4 outline-[#FF4D8D] outline-solid shadow-[0_0_0_200vmax_rgba(17,17,17,0.4)]"
            : "shadow-[0_0_0_200vmax_rgba(17,17,17,0.4)]",
          glide,
        )}
        aria-hidden="true"
        style={
          target
            ? {
                top: target.top,
                left: target.left,
                width: target.width,
                height: target.height,
              }
            : {
                top: viewport.height / 2,
                left: viewport.width / 2,
                width: 0,
                height: 0,
              }
        }
        data-empty={target ? undefined : ""}
      />
      <GuideDialog
        ref={cardRef}
        titleId="tour-title"
        bodyId="tour-body"
        className={cn("absolute", glide)}
        style={{ top: spot.top, left: spot.left }}
        side={spot.side ?? undefined}
        title={t(words.title)}
        body={t(words.body)}
        pointer={
          spot.side ? (
            // Guide v3: a white notch on the card's edge points at the target.
            <span
              aria-hidden="true"
              className={cn(
                "absolute z-[1] size-3.5 rotate-45 border-[3px] border-border bg-white",
                spot.side === "right" && "-left-[9px] border-t-0 border-r-0",
                spot.side === "left" && "-right-[9px] border-b-0 border-l-0",
                spot.side === "below" && "-top-[9px] border-r-0 border-b-0",
                spot.side === "above" && "-bottom-[9px] border-t-0 border-l-0",
              )}
              style={
                spot.side === "right" || spot.side === "left"
                  ? { top: spot.arrow - 7 }
                  : { left: spot.arrow - 7 }
              }
            />
          ) : null
        }
        hud={<GuideHud total={steps.length} index={index} />}
        actions={
          <>
            <Button
              variant="neutral"
              size="sm"
              className="m-0 h-auto min-h-0 border-0 bg-transparent px-0 py-0 text-[13px] font-semibold underline shadow-none hover:translate-0"
              onClick={onClose}
            >
              {t("tourSkip")}
            </Button>
            <span className="ml-auto text-xs font-semibold text-arc-muted">
              {t("tourProgress", {
                step: index + 1,
                total: steps.length,
              })}
            </span>
            {index > 0 ? (
              <Button
                variant="neutral"
                size="sm"
                className="m-0 h-auto min-h-0 rounded-[6px] border-2 bg-white px-3 py-[5px] text-[13px] font-bold shadow-[0_3px_0_#111]"
                onClick={back}
              >
                {t("tourBack")}
              </Button>
            ) : null}
            <Button
              ref={nextRef}
              size="sm"
              className="m-0 h-auto min-h-0 rounded-[8px] border-[3px] bg-[#FF4D8D] px-3.5 py-[5px] text-[13px] font-bold shadow-[0_4px_0_#111]"
              onClick={next}
            >
              {last ? t("tourFinish") : t("tourNext")}
            </Button>
          </>
        }
      />
    </div>
  );
}
