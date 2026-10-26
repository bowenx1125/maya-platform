"use client";

import { createPortal } from "react-dom";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";

import { uiGuideText, type UiGuideKey } from "../lib/ui-guide-copy";
import { useT } from "../lib/i18n";

const tooltipId = "maya-ui-guide-tooltip";
const selector = "[data-ui-guide]";

type ActiveGuide = {
  key: UiGuideKey;
  x: number;
  y: number;
  anchor: "pointer" | "element";
  target: HTMLElement;
  pathname: string | null;
};

function guideTarget(value: EventTarget | null): HTMLElement | null {
  return value instanceof Element ? value.closest<HTMLElement>(selector) : null;
}

export function UiGuideTooltip() {
  const pathname = usePathname();
  const [active, setActive] = useState<ActiveGuide | null>(null);
  const [position, setPosition] = useState({ left: 8, top: 8 });
  const tooltipRef = useRef<HTMLDivElement>(null);
  const text = active
    ? active.target.dataset.uiGuideText?.trim() || uiGuideText(active.key)
    : null;

  useEffect(() => {
    let described: HTMLElement | null = null;
    let descriptionTarget: HTMLElement | null = null;
    let previousDescription: string | null = null;
    let currentKey: UiGuideKey | null = null;
    let currentText: string | null = null;
    let hovered: HTMLElement | null = null;
    let focused: HTMLElement | null = null;
    let focusedDescriptionElement: HTMLElement | null = null;
    let touchPinned = false;
    let pointerInput = false;

    const restoreDescription = () => {
      if (!descriptionTarget) return;
      if (previousDescription === null) {
        descriptionTarget.removeAttribute("aria-describedby");
      } else {
        descriptionTarget.setAttribute("aria-describedby", previousDescription);
      }
      described = null;
      descriptionTarget = null;
      previousDescription = null;
    };

    const hide = () => {
      restoreDescription();
      currentKey = null;
      currentText = null;
      touchPinned = false;
      hovered = null;
      focused = null;
      focusedDescriptionElement = null;
      setActive(null);
    };

    const show = (
      target: HTMLElement,
      point: { x: number; y: number; anchor: ActiveGuide["anchor"] },
      descriptionElement: HTMLElement = focused === target &&
      focusedDescriptionElement
        ? focusedDescriptionElement
        : target,
    ) => {
      const key = target.dataset.uiGuide;
      const message =
        target.dataset.uiGuideText?.trim() || (key ? uiGuideText(key) : null);
      if (!key || !message) {
        hide();
        return;
      }
      if (described !== target || descriptionTarget !== descriptionElement) {
        restoreDescription();
        previousDescription =
          descriptionElement.getAttribute("aria-describedby");
        const ids = new Set(
          (previousDescription ?? "").split(/\s+/).filter(Boolean),
        );
        ids.add(tooltipId);
        descriptionElement.setAttribute("aria-describedby", [...ids].join(" "));
        descriptionTarget = descriptionElement;
      }
      described = target;
      currentKey = key as UiGuideKey;
      currentText = message;
      setActive({ ...point, key: key as UiGuideKey, target, pathname });
    };

    const anchorPoint = (target: HTMLElement) => {
      const rect = target.getBoundingClientRect();
      return {
        x: rect.left + rect.width / 2,
        y: rect.bottom,
        anchor: "element" as const,
      };
    };

    const onPointerOver = (event: PointerEvent) => {
      if (event.pointerType === "touch") return;
      pointerInput = true;
      touchPinned = false;
      const target = guideTarget(event.target);
      if (!target) {
        hide();
        return;
      }
      if (focused !== target) {
        focused = null;
        focusedDescriptionElement = null;
      }
      hovered = target;
      show(target, { x: event.clientX, y: event.clientY, anchor: "pointer" });
    };

    const onPointerMove = (event: PointerEvent) => {
      // A fast move or removed target may skip the matching pointerout.
      onPointerOver(event);
    };

    const onPointerOut = (event: PointerEvent) => {
      if (!event.relatedTarget) {
        hide();
        return;
      }
      const target = guideTarget(event.target);
      const next = guideTarget(event.relatedTarget);
      if (!target || target !== hovered || (next && target.contains(next)))
        return;
      hide();
    };

    const onPointerDown = (event: PointerEvent) => {
      pointerInput = true;
      focused = null;
      if (
        event.pointerType !== "touch" ||
        guideTarget(event.target) !== described
      )
        hide();
    };

    const onPointerUp = (event: PointerEvent) => {
      if (event.pointerType !== "touch") return;
      const target = guideTarget(event.target);
      if (!target) return;
      if (touchPinned && described === target) {
        hide();
        return;
      }
      touchPinned = true;
      show(target, anchorPoint(target));
    };

    const onFocusIn = (event: FocusEvent) => {
      // Clicking focuses buttons too; only keyboard focus should keep help open.
      if (pointerInput) return;
      const target = guideTarget(event.target);
      if (!target) {
        hide();
        return;
      }
      focused = target;
      focusedDescriptionElement =
        event.target instanceof HTMLElement ? event.target : target;
      show(target, anchorPoint(target), focusedDescriptionElement);
    };

    const onFocusOut = (event: FocusEvent) => {
      const target = guideTarget(event.target);
      const next = guideTarget(event.relatedTarget);
      if (!target || target !== focused || (next && target.contains(next)))
        return;
      focused = null;
      focusedDescriptionElement = null;
      if (hovered !== target && !touchPinned) hide();
    };

    const onKeyDown = (event: KeyboardEvent) => {
      pointerInput = false;
      if (event.key === "Escape" && described) hide();
    };

    const onClick = () => {
      if (!touchPinned) hide();
    };
    const onVisibilityChange = () => {
      if (document.visibilityState === "hidden") hide();
    };
    const observer = new MutationObserver(() => {
      if (!described) return;
      if (
        !described.isConnected ||
        (descriptionTarget && !descriptionTarget.isConnected) ||
        described.dataset.uiGuide !== currentKey
      ) {
        hide();
        return;
      }
      const nextText =
        described.dataset.uiGuideText?.trim() || uiGuideText(currentKey);
      if (!nextText) {
        hide();
      } else if (nextText !== currentText) {
        currentText = nextText;
        setActive((current) => (current ? { ...current } : current));
      }
    });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["data-ui-guide", "data-ui-guide-text"],
    });

    document.addEventListener("pointerover", onPointerOver, true);
    document.addEventListener("pointermove", onPointerMove, true);
    document.addEventListener("pointerout", onPointerOut, true);
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("pointerup", onPointerUp, true);
    document.addEventListener("focusin", onFocusIn, true);
    document.addEventListener("focusout", onFocusOut, true);
    document.addEventListener("keydown", onKeyDown, true);
    document.addEventListener("click", onClick, true);
    document.addEventListener("scroll", hide, true);
    document.addEventListener("pointercancel", hide, true);
    document.addEventListener("visibilitychange", onVisibilityChange);
    window.addEventListener("blur", hide);
    window.addEventListener("resize", hide);
    return () => {
      observer.disconnect();
      document.removeEventListener("pointerover", onPointerOver, true);
      document.removeEventListener("pointermove", onPointerMove, true);
      document.removeEventListener("pointerout", onPointerOut, true);
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("pointerup", onPointerUp, true);
      document.removeEventListener("focusin", onFocusIn, true);
      document.removeEventListener("focusout", onFocusOut, true);
      document.removeEventListener("keydown", onKeyDown, true);
      document.removeEventListener("click", onClick, true);
      document.removeEventListener("scroll", hide, true);
      document.removeEventListener("pointercancel", hide, true);
      document.removeEventListener("visibilitychange", onVisibilityChange);
      window.removeEventListener("blur", hide);
      window.removeEventListener("resize", hide);
      hide();
    };
  }, [pathname]);

  useLayoutEffect(() => {
    const tooltip = tooltipRef.current;
    if (!active || !text || !tooltip) return;
    const size = tooltip.getBoundingClientRect();
    const edge = 8;
    const clamp = (left: number, top: number) => ({
      left: Math.max(
        edge,
        Math.min(left, window.innerWidth - size.width - edge),
      ),
      top: Math.max(
        edge,
        Math.min(top, window.innerHeight - size.height - edge),
      ),
    });
    let nextPosition: { left: number; top: number };
    const rect = active.target.getBoundingClientRect();
    const candidates =
      active.anchor === "pointer"
        ? [
            clamp(active.x + 12, active.y + 12),
            clamp(active.x + 12, active.y - size.height - 12),
            clamp(active.x - size.width - 12, active.y + 12),
            clamp(active.x - size.width - 12, active.y - size.height - 12),
            clamp(rect.left + (rect.width - size.width) / 2, rect.bottom + 10),
            clamp(
              rect.left + (rect.width - size.width) / 2,
              rect.top - size.height - 10,
            ),
            clamp(rect.right + 10, rect.top + (rect.height - size.height) / 2),
            clamp(
              rect.left - size.width - 10,
              rect.top + (rect.height - size.height) / 2,
            ),
          ]
        : [
            clamp(rect.left + (rect.width - size.width) / 2, rect.bottom + 10),
            clamp(
              rect.left + (rect.width - size.width) / 2,
              rect.top - size.height - 10,
            ),
            clamp(rect.right + 10, rect.top + (rect.height - size.height) / 2),
            clamp(
              rect.left - size.width - 10,
              rect.top + (rect.height - size.height) / 2,
            ),
            clamp(rect.left + (rect.width - size.width) / 2, rect.bottom),
            clamp(
              rect.left + (rect.width - size.width) / 2,
              rect.top - size.height,
            ),
            clamp(rect.right, rect.top + (rect.height - size.height) / 2),
            clamp(
              rect.left - size.width,
              rect.top + (rect.height - size.height) / 2,
            ),
          ];
    const controls = [
      rect,
      ...Array.from(
        document.querySelectorAll<HTMLElement>(
          'button, input, select, textarea, a[href], [role="button"], [tabindex]:not([tabindex="-1"])',
        ),
      )
        .filter((element) => element !== active.target)
        .map((element) => element.getBoundingClientRect())
        .filter((obstacle) => obstacle.width > 0 && obstacle.height > 0),
    ];
    const textObstacles = Array.from(
      document.querySelectorAll<HTMLElement>("body *"),
    )
      .filter(
        (element) =>
          element.childElementCount === 0 &&
          Boolean(element.textContent?.trim()) &&
          element !== active.target &&
          !active.target.contains(element) &&
          !tooltip.contains(element) &&
          !element.closest(
            'button, input, select, textarea, a[href], [role="button"], [tabindex]:not([tabindex="-1"])',
          ),
      )
      .map((element) => element.getBoundingClientRect())
      .filter((obstacle) => obstacle.width > 0 && obstacle.height > 0);
    const overlapArea = (
      position: { left: number; top: number },
      obstacles: DOMRect[],
    ) =>
      obstacles.reduce((total, obstacle) => {
        const width = Math.max(
          0,
          Math.min(position.left + size.width, obstacle.right) -
            Math.max(position.left, obstacle.left),
        );
        const height = Math.max(
          0,
          Math.min(position.top + size.height, obstacle.bottom) -
            Math.max(position.top, obstacle.top),
        );
        return total + width * height;
      }, 0);
    nextPosition = candidates.reduce((best, candidate) =>
      overlapArea(candidate, controls) < overlapArea(best, controls) ||
      (overlapArea(candidate, controls) === overlapArea(best, controls) &&
        overlapArea(candidate, textObstacles) <
          overlapArea(best, textObstacles))
        ? candidate
        : best,
    );
    setPosition((current) =>
      current.left === nextPosition.left && current.top === nextPosition.top
        ? current
        : nextPosition,
    );
  }, [active, text]);

  if (!active || !text || active.pathname !== pathname) return null;
  return createPortal(
    <div
      id={tooltipId}
      className="pointer-events-none fixed z-[1500] w-max max-w-[min(280px,calc(100vw-16px))] rounded-[12px] border border-(--line,#e4ddd2) bg-(--surface,#fdfaf3) px-[13px] py-2.5 text-[13px] leading-[1.5] font-normal whitespace-pre-line text-(--ink,#332d22) shadow-[0_4px_16px_rgb(52_45_30/10%)] [overflow-wrap:anywhere] motion-safe:animate-tooltip-in"
      role="tooltip"
      ref={tooltipRef}
      style={{ left: position.left, top: position.top }}
    >
      {text}
    </div>,
    document.body,
  );
}
