"use client";

import dynamic from "next/dynamic";
import { useEffect, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import type { Player } from "../../lib/poker/table";
import { usePrefersReducedMotion } from "../academy/motion";
import { useSession } from "../session-provider";
import styles from "./card-table.module.css";

// The table only loads for the few who find the way in.
const CardTable = dynamic(
  () => import("./card-table").then((module) => module.CardTable),
  { ssr: false },
);

/** Typed anywhere in the workspace, outside a field. */
export const SECRET = "royalflush";
/** Seat-fillers when the group is too small for a game. */
const SCHOLARS = ["Laozi", "Plato", "Socrates", "Confucius", "Hypatia"];
const DOORS_MS = 1200;
const LEAVE_MS = 280;

type Phase = "closed" | "opening" | "open" | "leaving";

export function SecretDoor() {
  const { api, user } = useSession();
  const reduced = usePrefersReducedMotion();
  const [phase, setPhase] = useState<Phase>("closed");
  const [players, setPlayers] = useState<Player[] | null>(null);
  const top = useRef<HTMLDivElement>(null);
  const bottom = useRef<HTMLDivElement>(null);
  const room = useRef<HTMLDivElement>(null);
  const isOpen = phase !== "closed";

  useEffect(() => {
    let typed = "";
    const listen = (event: KeyboardEvent) => {
      if (
        event.metaKey ||
        event.ctrlKey ||
        event.altKey ||
        event.key.length !== 1
      )
        return;
      const target = event.target as HTMLElement | null;
      if (target?.closest?.("input, textarea, select, [contenteditable]"))
        return;
      typed = (typed + event.key.toLowerCase()).slice(-SECRET.length);
      if (typed !== SECRET) return;
      typed = "";
      setPhase((current) =>
        current === "closed" ? (reduced ? "open" : "opening") : current,
      );
    };
    window.addEventListener("keydown", listen);
    return () => window.removeEventListener("keydown", listen);
  }, [reduced]);

  // Your group takes the other seats; scholars fill in when it is small.
  useEffect(() => {
    if (!isOpen || players) return;
    let active = true;
    const me: Player = {
      id: user?.id ?? "you",
      name: user?.display_name ?? "You",
      avatar: user?.avatar ?? null,
      human: true,
    };
    const groupId = user?.groups?.[0]?.group_id;
    const members =
      groupId && typeof api?.group === "function"
        ? api
            .group(groupId)
            .then((group) => group.members ?? [])
            .catch(() => [])
        : Promise.resolve([]);
    void members.then((list) => {
      if (!active) return;
      const mates: Player[] = list
        .filter((member) => member.user_id !== me.id)
        .slice(0, 5)
        .map((member) => ({
          id: member.user_id,
          name: member.display_name,
          avatar: member.avatar ?? null,
          human: false,
        }));
      const fill = SCHOLARS.slice(0, Math.max(0, 2 - mates.length)).map(
        (name) => ({ id: `scholar-${name}`, name, avatar: null, human: false }),
      );
      setPlayers([me, ...mates, ...fill]);
    });
    return () => {
      active = false;
    };
  }, [api, isOpen, players, user]);

  // The doors are two copies of the page as it stands, each showing its half,
  // so it is the workspace itself that splits and slides apart.
  useLayoutEffect(() => {
    if (phase !== "opening") return;
    const frame = document.getElementById("workspace-content")?.parentElement;
    const rect = frame?.getBoundingClientRect();
    const halves = [
      [top.current, 0],
      [bottom.current, window.innerHeight / 2],
    ] as const;
    for (const [door, offset] of halves) {
      if (!door || !frame || !rect) continue;
      const copy = frame.cloneNode(true) as HTMLElement;
      for (const node of [copy, ...copy.querySelectorAll("[id]")])
        node.removeAttribute("id");
      copy.inert = true;
      Object.assign(copy.style, {
        left: `${rect.left}px`,
        top: `${rect.top - offset}px`,
        width: `${rect.width}px`,
      });
      door.replaceChildren(copy);
    }
    const timer = window.setTimeout(() => setPhase("open"), DOORS_MS);
    return () => window.clearTimeout(timer);
  }, [phase]);

  useEffect(() => {
    if (!isOpen) return;
    const html = document.documentElement;
    const overflow = html.style.overflow;
    const focused = document.activeElement as HTMLElement | null;
    html.style.overflow = "hidden";
    room.current?.focus();
    return () => {
      html.style.overflow = overflow;
      focused?.focus?.();
    };
  }, [isOpen]);

  useEffect(() => {
    if (phase === "leaving") {
      const timer = window.setTimeout(
        () => setPhase("closed"),
        reduced ? 0 : LEAVE_MS,
      );
      return () => window.clearTimeout(timer);
    }
    if (!isOpen) return;
    const listen = (event: KeyboardEvent) => {
      if (event.key === "Escape") setPhase("leaving");
    };
    window.addEventListener("keydown", listen);
    return () => window.removeEventListener("keydown", listen);
  }, [isOpen, phase, reduced]);

  if (!isOpen) return null;
  return createPortal(
    <>
      <div
        ref={room}
        className={styles.room}
        role="dialog"
        aria-modal="true"
        aria-label="Card table"
        tabIndex={-1}
        data-leaving={phase === "leaving" ? "" : undefined}
      >
        {players ? (
          <CardTable players={players} onLeave={() => setPhase("leaving")} />
        ) : null}
      </div>
      {phase === "opening" ? (
        <>
          <div
            ref={top}
            className={`${styles.door} ${styles.doorTop}`}
            aria-hidden="true"
          />
          <div
            ref={bottom}
            className={`${styles.door} ${styles.doorBottom}`}
            aria-hidden="true"
          />
        </>
      ) : null}
    </>,
    document.body,
  );
}
