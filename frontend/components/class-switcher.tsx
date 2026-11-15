"use client";

import {
  useEffect,
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";
import { ErrorNotice } from "./ui";
import {
  BUSY_MOTION,
  BUSY_MOTION_PRIMARY,
  PRESS_HIT,
  PRESS_MOTION,
} from "./ui/button";
import { teacherEnterInProgress } from "../lib/teacher-visit";
import { useTeacherClasses } from "./use-teacher-classes";
import styles from "./class-switcher.module.css";

type Course = { id: string; name: string };

const FOCUS =
  "focus-visible:outline-[3px] focus-visible:outline-[#111] focus-visible:outline-offset-2";
const KEY = `relative min-h-11 min-w-11 cursor-pointer border-[3px] border-[#111] bg-white text-ink font-extrabold ${FOCUS} ${PRESS_MOTION} ${PRESS_HIT}`;

export function classLabel(name: string): string {
  return name.match(/\d+/)?.[0] ?? name;
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg
      aria-hidden="true"
      viewBox="0 0 24 24"
      width="16"
      height="16"
      className={`shrink-0 transition-transform duration-150 ease-[cubic-bezier(.2,.8,.2,1)] motion-reduce:transition-none ${open ? "rotate-180" : ""}`}
    >
      <path
        d="m6 9 6 6 6-6"
        fill="none"
        stroke="currentColor"
        strokeWidth="2.6"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

function ClassMenu({
  id,
  open,
  classes,
  current,
  busy,
  choose,
  close,
  menuRef,
}: {
  id: string;
  open: boolean;
  classes: Course[];
  current?: Course;
  busy: string | null;
  choose: (id: string) => Promise<void>;
  close: (returnFocus?: boolean) => void;
  menuRef: React.RefObject<HTMLDivElement | null>;
}) {
  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const items = Array.from(
      event.currentTarget.querySelectorAll<HTMLButtonElement>(
        '[role="menuitemradio"]',
      ),
    );
    const index = items.indexOf(document.activeElement as HTMLButtonElement);
    let next: number;
    switch (event.key) {
      case "ArrowDown":
        next = (index + 1) % items.length;
        break;
      case "ArrowUp":
        next = (index - 1 + items.length) % items.length;
        break;
      case "Home":
        next = 0;
        break;
      case "End":
        next = items.length - 1;
        break;
      case "Escape":
        event.preventDefault();
        event.stopPropagation();
        close(true);
        return;
      case "Tab":
        close();
        return;
      default:
        return;
    }
    event.preventDefault();
    items[next]?.focus();
  }
  return (
    <div
      ref={menuRef}
      id={id}
      role="menu"
      aria-label="Classes"
      data-testid="class-switcher-menu"
      inert={!open}
      className={`${styles.menu} grid rounded-[10px] border-[3px] border-[#111] bg-white p-2 shadow-[0_6px_0_#111] transition-[opacity,translate,visibility] ease-[cubic-bezier(.2,.8,.2,1)] ${open ? "visible translate-y-0 opacity-100 duration-150" : "invisible -translate-y-1 opacity-0 duration-[80ms]"} motion-reduce:translate-y-0`}
      onKeyDown={onKeyDown}
    >
      {classes.map((item) => {
        const selected = item.id === current?.id;
        return (
          <div key={item.id} className={styles.menuSlot}>
            <button
              type="button"
              role="menuitemradio"
              aria-checked={selected}
              aria-busy={busy === item.id || undefined}
              aria-disabled={busy !== null || undefined}
              tabIndex={open && selected ? 0 : -1}
              data-testid={`class-switcher-item-${item.id}`}
              title={item.name}
              className={`relative flex min-h-11 w-full min-w-0 cursor-pointer items-center gap-2 rounded-[6px] border-[3px] border-[#111] px-2 text-left text-sm font-extrabold ${FOCUS} ${PRESS_MOTION} ${PRESS_HIT} hover:bg-[#FFF7CC] active:bg-[#FFF7CC] ${selected ? `bg-main ${BUSY_MOTION_PRIMARY}` : `bg-white ${BUSY_MOTION}`}`}
              onClick={() => {
                if (busy || teacherEnterInProgress()) return;
                close(true);
                void choose(item.id);
              }}
            >
              {busy === item.id ? (
                <span className="spinner shrink-0" aria-hidden="true" />
              ) : (
                <span className="w-4 shrink-0" aria-hidden="true">
                  {selected ? "✓" : ""}
                </span>
              )}
              <span className="min-w-0 flex-1 truncate">{item.name}</span>
              {selected ? <span className="text-[10px]">Current</span> : null}
            </button>
          </div>
        );
      })}
    </div>
  );
}

export function ClassSwitcher({
  collapsed,
  mobile,
  homeLink,
}: {
  collapsed: boolean;
  mobile: boolean;
  homeLink: (
    label?: ReactNode,
    className?: string,
    title?: string,
  ) => ReactNode;
}) {
  const { classes, current, multiple, busy, error, choose } =
    useTeacherClasses();
  const [open, setOpen] = useState(false);
  const [present, setPresent] = useState(open);
  const rootRef = useRef<HTMLDivElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);
  const pendingFocus = useRef(false);
  // open in state lags a blur that flushes before click. The ref is the
  // value the trigger click toggles, including that same press.
  const openRef = useRef(false);
  // Set for the whole trigger press. Focus sits in the menu after open, so
  // the press blurs that item (relatedTarget is often null) and the root
  // blur would close and re-render before click, which then saw open=false
  // and opened the menu again.
  const pressedTrigger = useRef(false);
  const id = useId();
  const name = current ? classLabel(current.name) : "";
  const numericName = /^\d+$/.test(name);
  const title = current ? `Mayaform-${name}` : "Mayaform";
  const capsule = !collapsed;

  function close(returnFocus = false) {
    pendingFocus.current = false;
    openRef.current = false;
    setOpen(false);
    if (returnFocus) triggerRef.current?.focus();
  }
  function show(focus: boolean) {
    pendingFocus.current = focus;
    openRef.current = true;
    setPresent(true);
    setOpen(true);
  }
  useEffect(() => {
    if (!open || !pendingFocus.current || !classes.length) return;
    menuRef.current
      ?.querySelector<HTMLButtonElement>('[aria-checked="true"]')
      ?.focus();
    pendingFocus.current = false;
  }, [open, classes]);
  useEffect(() => {
    if (!open) return;
    function outside(event: PointerEvent) {
      if (pressedTrigger.current) return;
      if (!rootRef.current?.contains(event.target as Node)) close();
    }
    function escape(event: globalThis.KeyboardEvent) {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      close(true);
    }
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  const singleClassLabel = (
    <span className={styles.lockup}>
      <span className={styles.lockupBrand}>Mayaform</span>
      {current ? (
        <>
          <span className={styles.lockupHyphen}>-</span>
          <span
            className={styles.lockupSuffix}
            data-numeric={numericName || undefined}
            title={current.name}
          >
            {name}
          </span>
        </>
      ) : null}
    </span>
  );
  const homeClass = `${KEY} isolate flex items-center gap-1.5 font-display font-extrabold no-underline aria-[current=page]:bg-main px-2 text-lg ${BUSY_MOTION_PRIMARY} size-11 justify-center rounded-[10px] p-0`;
  const trigger = multiple ? (
    <button
      ref={triggerRef}
      type="button"
      aria-haspopup="menu"
      aria-expanded={open}
      aria-controls={id}
      aria-label={collapsed ? `Class ${name}` : `Class ${name}, switch class`}
      aria-busy={busy !== null || undefined}
      aria-disabled={busy !== null || undefined}
      data-testid="class-switcher-trigger"
      data-numeric={numericName || undefined}
      title={current?.name}
      className={
        capsule
          ? `${styles.capsuleTrigger} ${styles.segmentTrigger} relative flex min-h-11 min-w-11 cursor-pointer items-center justify-center gap-1 text-sm font-extrabold ${PRESS_HIT}`
          : `${KEY} ${BUSY_MOTION} ${styles.roundKey} rounded-full flex h-11 w-11 flex-col items-center justify-center gap-0 text-[10px] leading-tight`
      }
      onPointerDown={(event) => {
        if (event.button !== 0) return;
        pressedTrigger.current = true;
        // pointerup on the button does not fire when the pointer is
        // released outside it, which left this flag stuck true.
        const end = () => {
          pressedTrigger.current = false;
          window.removeEventListener("pointerup", end);
          window.removeEventListener("pointercancel", end);
        };
        window.addEventListener("pointerup", end);
        window.addEventListener("pointercancel", end);
      }}
      onClick={() => {
        pressedTrigger.current = false;
        if (busy) return;
        if (openRef.current) close();
        else show(true);
      }}
      onKeyDown={(event) => {
        if (!["ArrowDown", "ArrowUp", "Enter", " "].includes(event.key)) return;
        event.preventDefault();
        if (!busy) show(true);
      }}
    >
      {busy ? <span className="spinner shrink-0" aria-hidden="true" /> : null}
      <span title={current?.name} className="min-w-0 truncate max-w-full">
        {name}
      </span>
      {!collapsed ? (
        <span className="contents">
          <Chevron open={open} />
        </span>
      ) : null}
    </button>
  ) : null;

  return (
    <div
      ref={rootRef}
      data-class-switcher
      className={`relative min-w-0 ${mobile ? "contents" : "w-full"}`}
      onBlur={(event) => {
        if (pressedTrigger.current) return;
        if (!event.currentTarget.contains(event.relatedTarget as Node | null))
          close();
      }}
    >
      <div
        aria-busy={(capsule && busy !== null) || undefined}
        data-long-name={
          (capsule && !numericName && name.length > 12) || undefined
        }
        className={
          collapsed
            ? "grid justify-items-center gap-3"
            : `${styles.capsule} ${styles.segmented} relative flex min-w-0 rounded-full border-[3px] border-[#111] bg-white ${PRESS_MOTION} ${PRESS_HIT} ${BUSY_MOTION} after:pointer-events-none`
        }
      >
        {homeLink(
          !multiple ? (
            singleClassLabel
          ) : (
            <span className="block truncate">Mayaform</span>
          ),
          collapsed
            ? `${homeClass} ${styles.roundKey} rounded-full!`
            : `${styles.capsuleHome} relative isolate flex min-h-11 min-w-11 flex-1 items-center gap-1.5 px-2 font-display font-extrabold text-ink no-underline ${mobile ? "text-lg" : "text-sm [&>.brand-dot]:size-3.5!"} ${PRESS_HIT}`,
          title,
        )}
        {trigger}
      </div>
      {multiple && present ? (
        <div
          className={`${collapsed ? "absolute top-full left-[calc(100%+12px)] z-30 w-[280px]" : mobile ? "col-span-2 mt-3 min-w-0" : "mt-3 min-w-0"} ${open ? "" : "pointer-events-none"}`}
          onTransitionEnd={(event) => {
            if (!open && event.propertyName === "opacity") setPresent(false);
          }}
        >
          <ClassMenu
            id={id}
            open={open}
            classes={classes}
            current={current}
            busy={busy}
            choose={choose}
            close={close}
            menuRef={menuRef}
          />
        </div>
      ) : null}
      {error ? (
        <div className={mobile ? "col-span-2 mt-3" : "mt-3"}>
          <ErrorNotice error={error} />
        </div>
      ) : null}
    </div>
  );
}
