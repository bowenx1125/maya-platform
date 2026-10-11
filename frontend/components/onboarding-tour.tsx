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

import type { MessageKey } from "../lib/i18n";
import { finishTour, tourPendingFor } from "../lib/onboarding";
import { usePrefersReducedMotion } from "./academy/motion";
import { useT } from "./locale";
import styles from "./onboarding-tour.module.css";

type Step = { target: string | null; title: MessageKey; body: MessageKey };

/** The walk round a new student's first home, in the order they will need it. */
const STEPS: Step[] = [
  { target: null, title: "tourWelcomeTitle", body: "tourWelcomeBody" },
  {
    target: '[data-tour="knowledge"]',
    title: "tourStudyformTitle",
    body: "tourStudyformBody",
  },
  {
    target: '[data-tour="brain"]',
    title: "tourBrainformTitle",
    body: "tourBrainformBody",
  },
  {
    target: '[data-tour="chat"]',
    title: "tourChatformTitle",
    body: "tourChatformBody",
  },
  {
    target: '[data-tour="live"]',
    title: "tourLiveTitle",
    body: "tourLiveBody",
  },
  {
    target: '[data-tour="guide"]',
    title: "tourGuideTitle",
    body: "tourGuideBody",
  },
  {
    target: '[data-tour="group"]',
    title: "tourGroupTitle",
    body: "tourGroupBody",
  },
  {
    target: ".account-settings-card",
    title: "tourProfileTitle",
    body: "tourProfileBody",
  },
];

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

/** Shows the tour once, to an account that has just registered. */
export function OnboardingTour({ userId }: { userId: string }) {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    // Wait for the home to lay out: the tour points at what is on it.
    const timer = window.setTimeout(() => {
      // ?tour replays it, for showing someone round.
      const replay = new URLSearchParams(window.location.search).has("tour");
      if (replay || tourPendingFor(userId)) setOpen(true);
    }, 600);
    return () => window.clearTimeout(timer);
  }, [userId]);
  const close = useCallback(() => {
    finishTour();
    setOpen(false);
  }, []);
  return open ? createPortal(<Tour onClose={close} />, document.body) : null;
}

function Tour({ onClose }: { onClose: () => void }) {
  const t = useT();
  const reduced = usePrefersReducedMotion();
  // Places this screen does not show (a phone's folded sidebar, a student
  // with no group yet) are left out rather than pointed at in thin air.
  const [steps] = useState(() =>
    STEPS.filter(
      (step) => !step.target || shown(document.querySelector(step.target)),
    ),
  );
  const [index, setIndex] = useState(0);
  const [target, setTarget] = useState<Box | null>(null);
  const [card, setCard] = useState({ width: 360, height: 200 });
  const [viewport, setViewport] = useState({ width: 0, height: 0 });
  const cardRef = useRef<HTMLDivElement>(null);
  const nextRef = useRef<HTMLButtonElement>(null);
  const step = steps[index];
  const last = index === steps.length - 1;

  // Follow the highlighted place as the page scrolls or the window resizes.
  useLayoutEffect(() => {
    const element = step.target
      ? document.querySelector<HTMLElement>(step.target)
      : null;
    element?.scrollIntoView({
      block: "center",
      behavior: reduced ? "auto" : "smooth",
    });
    let frame = 0;
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
    measure();
    window.addEventListener("resize", measure);
    window.addEventListener("scroll", measure, true);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener("resize", measure);
      window.removeEventListener("scroll", measure, true);
    };
  }, [step, reduced]);

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
    else setIndex((current) => current + 1);
  }, [last, onClose]);
  const back = useCallback(
    () => setIndex((current) => Math.max(0, current - 1)),
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

  const spot = place(target, card, viewport);
  const ready = viewport.width > 0;
  return (
    <div className={styles.tour} data-ready={ready ? "" : undefined}>
      {/* Clicks on the dimmed page are caught here: like a game's first
          level, the way on is the card's Next. */}
      <div className={styles.shield} aria-hidden="true" />
      <div
        className={styles.spotlight}
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
      <div
        ref={cardRef}
        className={styles.card}
        role="dialog"
        aria-modal="true"
        aria-labelledby="tour-title"
        aria-describedby="tour-body"
        style={{ top: spot.top, left: spot.left }}
        data-side={spot.side ?? undefined}
      >
        {spot.side ? (
          <span
            className={styles.arrow}
            aria-hidden="true"
            style={{ "--arrow": `${spot.arrow}px` } as CSSProperties}
          >
            <svg viewBox="0 0 24 24" width="26" height="26">
              <path
                d="M20 12H5m6-6-6 6 6 6"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.4"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </span>
        ) : null}
        <ol className={styles.dots} aria-hidden="true">
          {steps.map((item, at) => (
            <li
              key={item.title}
              data-state={at === index ? "now" : at < index ? "done" : "todo"}
            />
          ))}
        </ol>
        <h2 id="tour-title" key={`title-${index}`} className={styles.title}>
          {t(step.title)}
        </h2>
        <p id="tour-body" key={`body-${index}`} className={styles.body}>
          {t(step.body)}
        </p>
        <div className={styles.actions}>
          <button type="button" className={styles.skip} onClick={onClose}>
            {t("tourSkip")}
          </button>
          <span className={styles.progress}>
            {t("tourProgress", { step: index + 1, total: steps.length })}
          </span>
          {index > 0 ? (
            <button type="button" className={styles.back} onClick={back}>
              {t("tourBack")}
            </button>
          ) : null}
          <button
            ref={nextRef}
            type="button"
            className={`primary-action ${styles.next}`}
            onClick={next}
          >
            {last ? t("tourFinish") : t("tourNext")}
          </button>
        </div>
      </div>
    </div>
  );
}
