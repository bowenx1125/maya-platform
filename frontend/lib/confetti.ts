/**
 * Full-page confetti for a confirmed Done or Submit (owner request,
 * 2026-11-08). Two cannons fire from the bottom corners across the page.
 *
 * It is attached to document.body outside React so it keeps playing while
 * the router moves on, never takes pointer events, and is skipped for
 * reduced motion or where the Web Animations API is missing (jsdom, very
 * old browsers). Call it only after the server confirmed success.
 */

const COLORS = ["#FF4D8D", "#A3E635", "#67E8F9", "#C4B5FD", "#FFE14D"];
const PIECES_PER_CANNON = 70;
const LONGEST_MS = 2600;

export function celebrate(): void {
  if (typeof window === "undefined" || typeof document === "undefined") return;
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
  if (typeof HTMLElement.prototype.animate !== "function") return;

  const layer = document.createElement("div");
  layer.setAttribute("aria-hidden", "true");
  layer.dataset.confetti = "";
  Object.assign(layer.style, {
    position: "fixed",
    inset: "0",
    overflow: "hidden",
    pointerEvents: "none",
    zIndex: "2147483000",
  });
  document.body.appendChild(layer);

  const width = window.innerWidth;
  const height = window.innerHeight;
  for (const side of [-1, 1]) {
    for (let index = 0; index < PIECES_PER_CANNON; index += 1) {
      const piece = document.createElement("i");
      const size = 7 + Math.random() * 7;
      const round = Math.random() < 0.3;
      Object.assign(piece.style, {
        position: "absolute",
        bottom: "-16px",
        [side < 0 ? "left" : "right"]: "-8px",
        width: `${size}px`,
        height: `${round ? size : size * 0.45}px`,
        borderRadius: round ? "50%" : "2px",
        background: COLORS[(index + (side < 0 ? 0 : 2)) % COLORS.length],
      });
      layer.appendChild(piece);
      // Aim up and towards the middle; spread so the two arcs cross.
      const across = (0.35 + Math.random() * 0.6) * width * -side;
      const rise = (0.55 + Math.random() * 0.4) * height;
      const fall = rise * (0.45 + Math.random() * 0.5);
      const spin = (Math.random() < 0.5 ? -1 : 1) * (360 + Math.random() * 720);
      const duration = 1600 + Math.random() * (LONGEST_MS - 1600);
      piece.animate(
        [
          { transform: "translate(0, 0) rotate(0deg)", opacity: 1 },
          {
            transform: `translate(${across * 0.7}px, ${-rise}px) rotate(${spin / 2}deg)`,
            opacity: 1,
            offset: 0.45,
            easing: "cubic-bezier(.3,.7,.6,1)",
          },
          {
            transform: `translate(${across * 0.95}px, ${-rise + fall * 0.8}px) rotate(${spin * 0.9}deg)`,
            opacity: 1,
            offset: 0.85,
          },
          {
            transform: `translate(${across}px, ${-rise + fall}px) rotate(${spin}deg)`,
            opacity: 0,
          },
        ],
        {
          duration,
          delay: Math.random() * 180,
          easing: "cubic-bezier(.2,.8,.2,1)",
          fill: "forwards",
        },
      );
    }
  }
  window.setTimeout(() => layer.remove(), LONGEST_MS + 400);
}
