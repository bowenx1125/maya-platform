"use client";

import { useEffect, useLayoutEffect, useRef } from "react";

import styles from "./entrance.module.css";

const SVG_NS = "http://www.w3.org/2000/svg";
const ease = (t: number) => (t < 0.5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2);

type Actor = {
  node: HTMLDivElement;
  waddle: HTMLDivElement;
  /** Centre of the copy where it starts, in viewport pixels. */
  x: number;
  y: number;
};

/** A copy of one scholar in its own SVG, laid exactly over where it stands. */
function lift(group: SVGGElement): Actor | null {
  const ctm = group.getScreenCTM();
  if (!ctm || typeof group.getBBox !== "function") return null;
  const box = group.getBBox();
  const pad = 16;
  const x0 = box.x - pad;
  const y0 = box.y - pad;
  const width = (box.width + pad * 2) * ctm.a;
  const height = (box.height + pad * 2) * ctm.d;
  const left = ctm.a * x0 + ctm.e;
  const top = ctm.d * y0 + ctm.f;

  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute(
    "viewBox",
    `${x0} ${y0} ${box.width + pad * 2} ${box.height + pad * 2}`,
  );
  const copy = group.cloneNode(true) as SVGGElement;
  copy.style.transform = "";
  // Fresh clip ids, so the copy does not lean on the original's.
  for (const clip of copy.querySelectorAll("clipPath[id]")) {
    const fresh = `${clip.id}-actor`;
    for (const user of copy.querySelectorAll(`[clip-path="url(#${clip.id})"]`))
      user.setAttribute("clip-path", `url(#${fresh})`);
    clip.id = fresh;
  }
  svg.append(copy);

  const waddle = document.createElement("div");
  waddle.style.cssText = "width:100%;height:100%;transform-origin:50% 100%";
  waddle.append(svg);
  const node = document.createElement("div");
  node.className = styles.vaultActor;
  Object.assign(node.style, {
    left: `${left}px`,
    top: `${top}px`,
    width: `${width}px`,
    height: `${height}px`,
  });
  node.append(waddle);
  return { node, waddle, x: left + width / 2, y: top + height / 2 };
}

/** The vault wheel the four turn: a gold ring, spokes, a hub and four bolts. */
function wheel(): SVGSVGElement {
  const svg = document.createElementNS(SVG_NS, "svg");
  svg.setAttribute("viewBox", "-120 -120 240 240");
  svg.setAttribute("class", styles.vaultWheel);
  svg.innerHTML = `
    <g data-bolts fill="#b8902e" stroke="#7a5d1c" stroke-width="2">
      <rect x="-9" y="-118" width="18" height="34" rx="3"/>
      <rect x="-9" y="84" width="18" height="34" rx="3"/>
      <rect x="-118" y="-9" width="34" height="18" rx="3"/>
      <rect x="84" y="-9" width="34" height="18" rx="3"/>
    </g>
    <circle r="92" fill="#efe3c6" stroke="#c9a227" stroke-width="10"/>
    <circle r="78" fill="none" stroke="#c9a227" stroke-width="2" stroke-dasharray="4 7"/>
    <g data-spin stroke="#8a6a1f" stroke-width="9" stroke-linecap="round">
      <line x1="0" y1="-62" x2="0" y2="62"/>
      <line x1="-62" y1="0" x2="62" y2="0"/>
      <line x1="-44" y1="-44" x2="44" y2="44"/>
      <line x1="-44" y1="44" x2="44" y2="-44"/>
      <circle r="62" fill="none" stroke-width="6"/>
      <circle r="18" fill="#d8a94b" stroke-width="5"/>
    </g>`;
  return svg;
}

/**
 * The way in from the home. The four scholars step out of the hero towards
 * the viewer, circle the middle of the page, and fold into a vault wheel that
 * turns, draws its bolts and swings the whole page open on its hinge.
 * Clicking anywhere skips to the room.
 */
export function VaultEntrance({ onDone }: { onDone: () => void }) {
  const stage = useRef<HTMLDivElement>(null);
  const finish = useRef(onDone);
  useEffect(() => {
    finish.current = onDone;
  }, [onDone]);

  useLayoutEffect(() => {
    const root = stage.current;
    const frame = document.getElementById("workspace-content")?.parentElement;
    const groups = [
      ...document.querySelectorAll<SVGGElement>(".home-hero .academy-scholar"),
    ];
    let ended = false;
    const end = () => {
      if (ended) return;
      ended = true;
      finish.current();
    };
    if (
      !root ||
      !frame ||
      groups.length !== 4 ||
      typeof root.animate !== "function"
    ) {
      end();
      return;
    }

    // The door: a picture of the page, scholars taken off it.
    const rect = frame.getBoundingClientRect();
    const door = document.createElement("div");
    door.className = styles.vaultDoor;
    const page = frame.cloneNode(true) as HTMLElement;
    for (const node of [page, ...page.querySelectorAll("[id]")])
      node.removeAttribute("id");
    for (const scholar of page.querySelectorAll<SVGGElement>(
      ".academy-scholar",
    ))
      scholar.style.visibility = "hidden";
    Object.assign(page.style, {
      left: `${rect.left}px`,
      top: `${rect.top}px`,
      width: `${rect.width}px`,
    });
    const vaultWheel = wheel();
    door.append(page, vaultWheel);

    const layer = document.createElement("div");
    layer.className = styles.vaultActors;
    const actors = groups
      .map(lift)
      .filter((actor): actor is Actor => actor !== null);
    actors.forEach((actor) => layer.append(actor.node));
    root.append(door, layer);
    if (actors.length !== 4) {
      end();
      return;
    }

    const cx = window.innerWidth / 2;
    const cy = window.innerHeight / 2 + 30;
    const radius = Math.min(window.innerWidth, window.innerHeight) * 0.26;
    const grown = 2.2;
    // Left, front, right, back: the four take their places round the middle.
    const start = [Math.PI, Math.PI / 2, 0, -Math.PI / 2];
    const at = (actor: Actor, angle: number, lift = 0, scale = grown) =>
      `translate3d(${cx + radius * Math.cos(angle) - actor.x}px, ${
        cy - actor.y - lift
      }px, ${radius * Math.sin(angle)}px) scale(${scale})`;

    const run = async () => {
      // 1. Out of the picture: forward, up and larger, waddling as they go.
      await Promise.all(
        actors.map((actor, index) => {
          actor.waddle.animate([{ rotate: "-7deg" }, { rotate: "7deg" }], {
            duration: 170,
            iterations: 6,
            direction: "alternate",
            delay: index * 90,
          });
          return actor.node.animate(
            [
              { transform: "translate3d(0, 0, 0) scale(1)", filter: "none" },
              {
                transform: at(actor, start[index], 60, 1.6),
                filter: "drop-shadow(0 24px 18px rgba(0,0,0,0.25))",
                offset: 0.6,
              },
              {
                transform: at(actor, start[index]),
                filter: "drop-shadow(0 30px 22px rgba(0,0,0,0.3))",
              },
            ],
            {
              duration: 1050,
              delay: index * 90,
              easing: "cubic-bezier(0.3, 0.7, 0.3, 1)",
              fill: "forwards",
            },
          ).finished;
        }),
      );

      // 2. Round the middle twice, with a hop, while the wheel rises behind.
      vaultWheel.animate(
        [
          { opacity: 0, transform: "scale(0.5) rotate(-40deg)" },
          { opacity: 1, transform: "scale(1) rotate(0deg)" },
        ],
        {
          duration: 700,
          easing: "cubic-bezier(0.34, 1.5, 0.64, 1)",
          fill: "forwards",
        },
      );
      await Promise.all(
        actors.map((actor, index) => {
          const frames = Array.from({ length: 49 }, (_, step) => {
            const t = ease(step / 48);
            const hop = Math.abs(Math.sin(step / 4)) * 10;
            return {
              transform: at(actor, start[index] + t * Math.PI * 4, hop),
            };
          });
          return actor.node.animate(frames, {
            duration: 1400,
            fill: "forwards",
          }).finished;
        }),
      );

      // 3. Into the hub.
      await Promise.all(
        actors.map(
          (actor, index) =>
            actor.node.animate(
              [
                {
                  transform: at(actor, start[index] + Math.PI * 4),
                  opacity: 1,
                },
                {
                  transform: `translate3d(${cx - actor.x}px, ${cy - actor.y - 30}px, 0) scale(0.2)`,
                  opacity: 0,
                },
              ],
              {
                duration: 420,
                delay: index * 40,
                easing: "cubic-bezier(0.6, 0, 0.8, 0.4)",
                fill: "forwards",
              },
            ).finished,
        ),
      );

      // 4. The wheel turns and the bolts draw back.
      const spokes = vaultWheel.querySelector("[data-spin]");
      const bolts = vaultWheel.querySelector("[data-bolts]");
      await Promise.all([
        spokes?.animate(
          [{ transform: "rotate(0deg)" }, { transform: "rotate(-540deg)" }],
          {
            duration: 800,
            easing: "cubic-bezier(0.5, 0, 0.3, 1)",
            fill: "forwards",
          },
        ).finished,
        bolts?.animate(
          [{ transform: "scale(1)" }, { transform: "scale(0.78)" }],
          {
            duration: 260,
            delay: 560,
            easing: "ease-in",
            fill: "forwards",
          },
        ).finished,
      ]);

      // 5. The page swings open on its hinge, pulled towards the viewer like
      // a vault door; it fades on the way past so its near edge never fills
      // the screen.
      await door.animate(
        [
          { transform: "rotateY(0deg)", opacity: 1 },
          { transform: "rotateY(-62deg)", opacity: 1, offset: 0.65 },
          { transform: "rotateY(-92deg)", opacity: 0 },
        ],
        {
          duration: 1000,
          easing: "cubic-bezier(0.6, 0, 0.25, 1)",
          fill: "forwards",
        },
      ).finished;
    };

    const skip = () => end();
    root.addEventListener("click", skip);
    run().then(end, end);
    return () => {
      // A cancelled run must not count as finished: in development React
      // mounts this twice, and the first teardown would open the room.
      ended = true;
      root.removeEventListener("click", skip);
      for (const animation of root.getAnimations({ subtree: true }))
        animation.cancel();
      root.replaceChildren();
    };
  }, []);

  return <div ref={stage} className={styles.vault} aria-hidden="true" />;
}
