"use client";

import { createPortal } from "react-dom";
import { useEffect, useLayoutEffect, useRef, useState } from "react";

import { uiGuideText, type UiGuideKey } from "../lib/ui-guide-copy";
import { useLocale } from "./locale";
import styles from "./ui-guide-tooltip.module.css";

const tooltipId = "maya-ui-guide-tooltip";
const selector = "[data-ui-guide]";

type ActiveGuide = {
  key: UiGuideKey;
  x: number;
  y: number;
  anchor: "pointer" | "element";
  target: HTMLElement;
};

function guideTarget(value: EventTarget | null): HTMLElement | null {
  return value instanceof Element ? value.closest<HTMLElement>(selector) : null;
}

export function UiGuideTooltip() {
  const { locale } = useLocale();
  const [active, setActive] = useState<ActiveGuide | null>(null);
  const [position, setPosition] = useState({ left: 8, top: 8 });
  const tooltipRef = useRef<HTMLDivElement>(null);
  const localeRef = useRef(locale);
  const text = active ? uiGuideText(active.key, locale) : null;

  useEffect(() => {
    let described: HTMLElement | null = null;
    let descriptionTarget: HTMLElement | null = null;
    let previousDescription: string | null = null;
    let currentKey: UiGuideKey | null = null;
    let hovered: HTMLElement | null = null;
    let focused: HTMLElement | null = null;
    let focusedDescriptionElement: HTMLElement | null = null;
    let touchPinned = false;

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
      touchPinned = false;
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
      if (!key || !uiGuideText(key, localeRef.current)) return;
      if (descriptionTarget !== descriptionElement) {
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
      setActive({ ...point, key: key as UiGuideKey, target });
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
      const target = guideTarget(event.target);
      if (!target) return;
      hovered = target;
      show(target, { x: event.clientX, y: event.clientY, anchor: "pointer" });
    };

    const onPointerMove = (event: PointerEvent) => {
      if (event.pointerType === "touch") return;
      const target = guideTarget(event.target);
      if (target && target === hovered && currentKey) {
        show(target, { x: event.clientX, y: event.clientY, anchor: "pointer" });
      }
    };

    const onPointerOut = (event: PointerEvent) => {
      const target = guideTarget(event.target);
      const next = guideTarget(event.relatedTarget);
      if (!target || target !== hovered || (next && target.contains(next)))
        return;
      hovered = null;
      if (described === target && focused !== target && !touchPinned) hide();
    };

    const onPointerDown = (event: PointerEvent) => {
      if (touchPinned && guideTarget(event.target) !== described) hide();
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
      const target = guideTarget(event.target);
      if (!target) return;
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
      if (event.key === "Escape" && described) hide();
    };

    document.addEventListener("pointerover", onPointerOver, true);
    document.addEventListener("pointermove", onPointerMove, true);
    document.addEventListener("pointerout", onPointerOut, true);
    document.addEventListener("pointerdown", onPointerDown, true);
    document.addEventListener("pointerup", onPointerUp, true);
    document.addEventListener("focusin", onFocusIn, true);
    document.addEventListener("focusout", onFocusOut, true);
    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("pointerover", onPointerOver, true);
      document.removeEventListener("pointermove", onPointerMove, true);
      document.removeEventListener("pointerout", onPointerOut, true);
      document.removeEventListener("pointerdown", onPointerDown, true);
      document.removeEventListener("pointerup", onPointerUp, true);
      document.removeEventListener("focusin", onFocusIn, true);
      document.removeEventListener("focusout", onFocusOut, true);
      document.removeEventListener("keydown", onKeyDown, true);
      restoreDescription();
    };
  }, []);

  useLayoutEffect(() => {
    localeRef.current = locale;
  }, [locale]);

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
          ];
    const obstacles = [
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
    const overlapArea = (position: { left: number; top: number }) =>
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
      overlapArea(candidate) < overlapArea(best) ? candidate : best,
    );
    setPosition((current) =>
      current.left === nextPosition.left && current.top === nextPosition.top
        ? current
        : nextPosition,
    );
  }, [active, text]);

  useEffect(() => {
    const reposition = () => {
      setActive((current) => (current ? { ...current } : null));
    };
    window.addEventListener("resize", reposition);
    document.addEventListener("scroll", reposition, true);
    return () => {
      window.removeEventListener("resize", reposition);
      document.removeEventListener("scroll", reposition, true);
    };
  }, []);

  if (!active || !text) return null;
  return createPortal(
    <div
      id={tooltipId}
      className={styles.tooltip}
      role="tooltip"
      ref={tooltipRef}
      style={{ left: position.left, top: position.top }}
    >
      {text}
    </div>,
    document.body,
  );
}
