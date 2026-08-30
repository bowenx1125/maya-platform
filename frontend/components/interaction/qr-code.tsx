"use client";

import { create } from "qrcode";

import styles from "./interaction.module.css";

type QrCodeProps = {
  value: string;
  label?: string;
};

const QUIET_ZONE = 4;

/** Render a standards-compliant, offline QR symbol without a remote image. */
export function QrCode({ value, label = "Scan to join" }: QrCodeProps) {
  const code = create(value, { errorCorrectionLevel: "M" });
  const viewBoxSize = code.modules.size + QUIET_ZONE * 2;
  const cells = [];
  for (let row = 0; row < code.modules.size; row += 1) {
    for (let column = 0; column < code.modules.size; column += 1) {
      if (code.modules.get(row, column)) {
        cells.push(
          <rect
            key={`${row}-${column}`}
            x={column + QUIET_ZONE}
            y={row + QUIET_ZONE}
            width="1"
            height="1"
          />,
        );
      }
    }
  }
  return (
    <div className={styles.qrWrap}>
      <svg
        className={styles.qr}
        viewBox={`0 0 ${viewBoxSize} ${viewBoxSize}`}
        role="img"
        aria-label={`${label}: ${value}`}
        shapeRendering="crispEdges"
      >
        <rect width={viewBoxSize} height={viewBoxSize} fill="white" />
        <g fill="black">{cells}</g>
      </svg>
      <div className={styles.qrCaption}>
        <strong>{label}</strong>
        <code>{value}</code>
      </div>
    </div>
  );
}
