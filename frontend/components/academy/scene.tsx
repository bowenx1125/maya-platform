"use client";

/**
 * Flat scenery for the sign-in illustration.
 *
 * Everything here is decorative: the shapes carry no information a reader
 * needs, so they are hidden from assistive technology and the panel is
 * described by the mascots' own label instead.
 */
export function AcademyBackdrop() {
  return (
    <svg
      className="academy-backdrop"
      viewBox="0 0 440 420"
      preserveAspectRatio="xMidYMax slice"
      aria-hidden="true"
      focusable="false"
    >
      <defs>
        <linearGradient id="academy-sky" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#d9e6ee" />
          <stop offset="100%" stopColor="#f2f2e8" />
        </linearGradient>
        <clipPath id="academy-arch">
          <path d="M150 300 V150 a70 70 0 0 1 140 0 V300 Z" />
        </clipPath>
      </defs>

      <rect width="440" height="420" fill="#f4ecdd" />

      {/* Receding barrel vault */}
      <path
        d="M60 300 V132 a160 160 0 0 1 320 0 V300 Z"
        fill="#eadfca"
        stroke="#dccdb0"
        strokeWidth="2"
      />
      <path
        d="M100 300 V146 a120 120 0 0 1 240 0 V300 Z"
        fill="#f1e7d5"
        stroke="#dccdb0"
        strokeWidth="2"
      />
      <path
        d="M150 300 V150 a70 70 0 0 1 140 0 V300 Z"
        fill="url(#academy-sky)"
      />
      {/* Depth inside the opening, so the arch reads as a view through the
          building rather than as a flat panel of sky. */}
      <g clipPath="url(#academy-arch)">
        <g opacity="0.45" fill="#ffffff">
          <circle cx="192" cy="188" r="13" />
          <circle cx="208" cy="183" r="17" />
          <circle cx="229" cy="190" r="11" />
        </g>
        <rect x="150" y="244" width="140" height="56" fill="#e3dcc4" />
        <path d="M150 244 H290" stroke="#d3c9ab" strokeWidth="1.6" />
        <g fill="#dcd4b8">
          <rect x="163" y="214" width="9" height="30" />
          <rect x="184" y="220" width="8" height="24" />
          <rect x="248" y="220" width="8" height="24" />
          <rect x="268" y="214" width="9" height="30" />
        </g>
        <path
          d="M158 214 H282"
          stroke="#dcd4b8"
          strokeWidth="5"
          strokeLinecap="round"
        />
        <g fill="#cfc6a6" opacity="0.9">
          <rect x="200" y="228" width="6" height="16" rx="3" />
          <rect x="212" y="231" width="6" height="13" rx="3" />
          <rect x="232" y="230" width="6" height="14" rx="3" />
        </g>
        <g stroke="#d7cdaf" strokeWidth="1.4">
          <path d="M150 262 H290" />
          <path d="M150 280 H290" />
        </g>
      </g>

      {/* Coffers along the vault */}
      <g fill="none" stroke="#dccdb0" strokeWidth="2" opacity="0.8">
        <path d="M112 150 a112 112 0 0 1 216 0" />
        <path d="M128 140 a100 100 0 0 1 184 0" />
      </g>

      {/* Flanking columns */}
      {[26, 74, 366, 414].map((x) => (
        <g key={x}>
          <rect
            x={x - 13}
            y="112"
            width="26"
            height="188"
            fill="#f6efe1"
            stroke="#ddd0b6"
            strokeWidth="2"
          />
          <rect
            x={x - 18}
            y="100"
            width="36"
            height="14"
            rx="3"
            fill="#efe4cd"
            stroke="#ddd0b6"
            strokeWidth="2"
          />
          <rect
            x={x - 18}
            y="298"
            width="36"
            height="12"
            rx="3"
            fill="#e6dac0"
            stroke="#ddd0b6"
            strokeWidth="2"
          />
          <g stroke="#e0d2b6" strokeWidth="1.6">
            <path d={`M${x - 5} 118 V294`} />
            <path d={`M${x + 5} 118 V294`} />
          </g>
        </g>
      ))}

      {/* Statues in the side bays */}
      {[112, 328].map((x) => (
        <g key={x} opacity="0.62">
          <rect
            x={x - 14}
            y="238"
            width="28"
            height="62"
            rx="6"
            fill="#e7dcc6"
          />
          <circle cx={x} cy="228" r="11" fill="#e7dcc6" />
        </g>
      ))}

      {/* Floor */}
      <rect x="0" y="300" width="440" height="120" fill="#e9dfc9" />
      <g stroke="#dbcdb0" strokeWidth="1.6" opacity="0.85">
        <path d="M0 316 H440" />
        <path d="M0 340 H440" />
        <path d="M0 372 H440" />
        <path d="M150 300 L60 420" />
        <path d="M290 300 L380 420" />
        <path d="M220 300 V420" />
      </g>
    </svg>
  );
}

/** The gold rule and corner flourishes that frame the whole card. */
export function AcademyFrame() {
  const corner = (
    <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
      <g fill="none" stroke="#c9a227" strokeWidth="2">
        <path d="M4 22 V10 a6 6 0 0 1 6 -6 H22" />
        <path d="M12 30 V18 a6 6 0 0 1 6 -6 H30" />
        <circle cx="15" cy="15" r="2.6" fill="#c9a227" stroke="none" />
      </g>
    </svg>
  );
  return (
    <div className="academy-frame" aria-hidden="true">
      <span className="academy-corner academy-corner-tl">{corner}</span>
      <span className="academy-corner academy-corner-tr">{corner}</span>
      <span className="academy-corner academy-corner-bl">{corner}</span>
      <span className="academy-corner academy-corner-br">{corner}</span>
    </div>
  );
}

/**
 * The Mayaform mark: a gold ring with an indigo disc set above and right of it.
 *
 * This is the same shape `.brand-dot` draws in the signed-in header, at the
 * proportions that rule sets — a 3-in-18 ring, a 16-wide disc offset by 5 and
 * -4 — so the logo the opening animation collapses is the one the app then
 * wears in its nav.  The viewBox is cropped to the mark itself rather than
 * padded to a square, which lets it scale without a margin of empty space.
 */
export function AcademyEmblem() {
  return (
    <svg
      className="academy-emblem"
      viewBox="0 0 66 63"
      aria-hidden="true"
      focusable="false"
    >
      {/* Drawn first, so the ring crosses in front of it as the shadow does. */}
      <circle cx="42" cy="24" r="24" fill="var(--indigo)" />
      <circle
        cx="27"
        cy="36"
        r="22.5"
        fill="none"
        stroke="var(--gold)"
        strokeWidth="9"
      />
    </svg>
  );
}
