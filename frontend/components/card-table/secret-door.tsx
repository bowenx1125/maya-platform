"use client";

import dynamic from "next/dynamic";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import type { Player } from "../../lib/poker/table";
import { usePrefersReducedMotion } from "../academy/motion";
import { useSession } from "../session-provider";
import styles from "./entrance.module.css";
// Loaded with the page: the door has to be up before the first paint of the
// room behind it, or the room flashes through.
import { VaultEntrance } from "./vault-entrance";

// The room itself only loads for the few who find the way in.
const loadRoom = () => import("./card-room");
const CardRoom = dynamic(() => loadRoom().then((module) => module.CardRoom), {
  ssr: false,
});

/** The home's four scholars, left to right, clicked in turn. */
export const SEQUENCE = ["scroll", "wreath", "tablet", "wave"];
/** Seat-fillers when the group is too small for a game. */
const SCHOLARS = ["Laozi", "Plato", "Socrates", "Confucius", "Hypatia"];
const LEAVE_MS = 280;

type Phase = "closed" | "entering" | "open" | "leaving";

function hop(scholar: Element, wrong: boolean) {
  scholar.animate?.(
    wrong
      ? [
          { transform: "translateX(0)" },
          { transform: "translateX(-4px)" },
          { transform: "translateX(4px)" },
          { transform: "translateX(0)" },
        ]
      : [
          { transform: "translateY(0)" },
          { transform: "translateY(-12px)" },
          { transform: "translateY(0)" },
        ],
    { duration: wrong ? 260 : 360, easing: "cubic-bezier(0.34, 1.6, 0.64, 1)" },
  );
}

export function SecretDoor() {
  const { api, user } = useSession();
  const reduced = usePrefersReducedMotion();
  const [phase, setPhase] = useState<Phase>("closed");
  const [players, setPlayers] = useState<Player[] | null>(null);
  const room = useRef<HTMLDivElement>(null);
  const isOpen = phase !== "closed";

  // Each scholar answers a click with a hop; the right four in the right
  // order open the way, a wrong one shakes its head and starts the count over.
  useEffect(() => {
    let progress = 0;
    const listen = (event: MouseEvent) => {
      const scholar = (event.target as Element | null)?.closest?.(
        ".home-hero .academy-scholar",
      );
      if (!scholar) return;
      const id = scholar.getAttribute("data-scholar");
      const right = id === SEQUENCE[progress];
      progress = right ? progress + 1 : id === SEQUENCE[0] ? 1 : 0;
      hop(scholar, !right && progress === 0);
      // Fetch the room while the rest of the sequence is still being clicked.
      if (progress === 1) void loadRoom();
      if (progress < SEQUENCE.length) return;
      progress = 0;
      setPhase((current) =>
        current === "closed" ? (reduced ? "open" : "entering") : current,
      );
    };
    document.addEventListener("click", listen);
    return () => document.removeEventListener("click", listen);
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
        aria-label="Card room"
        tabIndex={-1}
        data-leaving={phase === "leaving" ? "" : undefined}
      >
        {players ? (
          <CardRoom players={players} onLeave={() => setPhase("leaving")} />
        ) : null}
      </div>
      {phase === "entering" ? (
        <VaultEntrance
          onDone={() =>
            setPhase((current) => (current === "entering" ? "open" : current))
          }
        />
      ) : null}
    </>,
    document.body,
  );
}
