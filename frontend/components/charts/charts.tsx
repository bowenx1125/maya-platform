"use client";

import styles from "./charts.module.css";

/**
 * The two charts this classroom needs, drawn by hand.
 *
 * No chart library is added for two shapes: a pie of a handful of vote totals
 * and a bar per Agent. Sharing one module keeps them reading as one system
 * rather than two accidents, and keeps the dependency surface at zero.
 *
 * Colours come from the palette every other surface uses, and each slice or
 * bar carries its own label, so neither chart depends on colour alone to be
 * readable.
 */

export type ChartDatum = {
  id: string;
  label: string;
  value: number;
};

const SERIES = [
  "var(--indigo)",
  "var(--gold)",
  "var(--green)",
  "var(--indigo-dark)",
  "var(--red)",
];

function seriesColour(index: number): string {
  return SERIES[index % SERIES.length];
}

/** A point on a circle of `radius`, with 0 at twelve o'clock. */
function point(fraction: number, radius: number): [number, number] {
  const angle = fraction * 2 * Math.PI - Math.PI / 2;
  return [50 + radius * Math.cos(angle), 50 + radius * Math.sin(angle)];
}

export function PieChart({
  data,
  emptyLabel,
}: {
  data: ChartDatum[];
  emptyLabel: string;
}) {
  const total = data.reduce((sum, item) => sum + item.value, 0);
  if (total <= 0) {
    return <p className={styles.empty}>{emptyLabel}</p>;
  }
  // Slice boundaries are computed before rendering rather than accumulated
  // inside the map: a running total mutated during render is exactly what the
  // compiler cannot reason about.
  const slices: { datum: ChartDatum; start: number; end: number }[] = [];
  let running = 0;
  for (const datum of data) {
    const start = running;
    running += datum.value / total;
    slices.push({ datum, start, end: running });
  }
  return (
    <div className={styles.pieLayout}>
      <svg
        className={styles.pie}
        role="img"
        aria-label={data
          .map((item) => `${item.label} ${item.value}`)
          .join("; ")}
        viewBox="0 0 100 100"
      >
        {slices.map(({ datum, start, end }, index) => {
          if (datum.value <= 0) return null;
          // One slice covering the whole circle cannot be drawn as an arc: its
          // start and end points coincide and the path collapses.
          if (datum.value === total) {
            return (
              <circle
                cx="50"
                cy="50"
                fill={seriesColour(index)}
                key={datum.id}
                r="42"
              />
            );
          }
          const [x1, y1] = point(start, 42);
          const [x2, y2] = point(end, 42);
          const large = datum.value / total > 0.5 ? 1 : 0;
          return (
            <path
              d={`M 50 50 L ${x1} ${y1} A 42 42 0 ${large} 1 ${x2} ${y2} Z`}
              fill={seriesColour(index)}
              key={datum.id}
            />
          );
        })}
      </svg>
      <ul className={styles.legend}>
        {data.map((item, index) => (
          <li key={item.id}>
            <span
              aria-hidden="true"
              className={styles.swatch}
              style={{ background: seriesColour(index) }}
            />
            <span className={styles.legendLabel}>{item.label}</span>
            <span className={styles.legendValue}>
              {item.value} · {Math.round((item.value / total) * 100)}%
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export function BarChart({
  data,
  emptyLabel,
}: {
  data: ChartDatum[];
  emptyLabel: string;
}) {
  if (data.length === 0) {
    return <p className={styles.empty}>{emptyLabel}</p>;
  }
  // A zero-width bar for every Agent is honest but unreadable, so the scale
  // falls back to one and every bar renders empty.
  const peak = Math.max(1, ...data.map((item) => item.value));
  return (
    <ul className={styles.bars}>
      {data.map((item, index) => (
        <li key={item.id}>
          <span className={styles.barLabel}>{item.label}</span>
          <span className={styles.barTrack}>
            <span
              className={styles.barFill}
              style={{
                background: seriesColour(index),
                width: `${(item.value / peak) * 100}%`,
              }}
            />
          </span>
          <span className={styles.barValue}>{item.value}</span>
        </li>
      ))}
    </ul>
  );
}
