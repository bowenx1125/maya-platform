"use client";

import { createPortal } from "react-dom";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";

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
  pathname: string | null;
};

function guideTarget(value: EventTarget | null): HTMLElement | null {
  return value instanceof Element ? value.closest<HTMLElement>(selector) : null;
}

export function UiGuideTooltip() {
  const { locale } = useLocale();
  const pathname = usePathname();
  const [active, setActive] = useState<ActiveGuide | null>(null);
  const [position, setPosition] = useState({ left: 8, top: 8 });
  const tooltipRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let described: HTMLElement | null = null;
    let previousDescription: string | null = null;
    let currentKey: UiGuideKey | null = null;
    let hovered: HTMLElement | null = null;
    let focused: HTMLElement | null = null;
    let touchPinned = false;
    let pointerInput = false;

    const restoreDescription = () => {
      if (!described) return;
      if (previousDescription === null) {
        described.removeAttribute("aria-describedby");
      } else {
        described.setAttribute("aria-describedby", previousDescription);
      }
      described = null;
      previousDescription = null;
    };

    const hide = () => {
      restoreDescription();
      currentKey = null;
      touchPinned = false;
      hovered = null;
      focused = null;
      setActive(null);
    };

    const show = (
      target: HTMLElement,
      point: { x: number; y: number; anchor: ActiveGuide["anchor"] },
    ) => {
      const key = target.dataset.uiGuide;
      if (!key || !uiGuideText(key, locale)) {
        hide();
        return;
      }
      if (described !== target) {
        restoreDescription();
        previousDescription = target.getAttribute("aria-describedby");
        const ids = new Set(
          (previousDescription ?? "").split(/\s+/).filter(Boolean),
        );
        ids.add(tooltipId);
        target.setAttribute("aria-describedby", [...ids].join(" "));
        described = target;
      }
      currentKey = key as UiGuideKey;
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
      focused = null;
      touchPinned = false;
      const target = guideTarget(event.target);
      if (!target) {
        hide();
        return;
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
      if (!target || target.dataset.uiGuideTouch !== "true") return;
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
      show(target, anchorPoint(target));
    };

    const onFocusOut = (event: FocusEvent) => {
      const target = guideTarget(event.target);
      const next = guideTarget(event.relatedTarget);
      if (!target || target !== focused || (next && target.contains(next)))
        return;
      focused = null;
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
      if (
        described &&
        (!described.isConnected || described.dataset.uiGuide !== currentKey)
      )
        hide();
    });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ["data-ui-guide"],
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
      observer.disconnect();
      hide();
    };
  }, [locale, pathname]);

  useLayoutEffect(() => {
    const tooltip = tooltipRef.current;
    if (!active || !tooltip) return;
    const size = tooltip.getBoundingClientRect();
    const edge = 8;
    let left: number;
    let top: number;
    if (active.anchor === "pointer") {
      left = active.x + 12;
      if (left + size.width + edge > window.innerWidth) {
        left = active.x - size.width - 12;
      }
      top = active.y + 12;
      if (top + size.height + edge > window.innerHeight) {
        top = active.y - size.height - 12;
      }
    } else {
      const rect = active.target.getBoundingClientRect();
      left = rect.left + (rect.width - size.width) / 2;
      top = rect.bottom + 10;
      if (top + size.height + edge > window.innerHeight) {
        top = rect.top - size.height - 10;
      }
    }
    setPosition({
      left: Math.max(
        edge,
        Math.min(left, window.innerWidth - size.width - edge),
      ),
      top: Math.max(
        edge,
        Math.min(top, window.innerHeight - size.height - edge),
      ),
    });
  }, [active]);

  const text = active ? uiGuideText(active.key, locale) : null;
  if (!active || !text || active.pathname !== pathname) return null;
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
