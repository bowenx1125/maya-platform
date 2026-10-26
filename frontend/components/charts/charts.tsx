"use client";

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
  color?: string;
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
    return <p className="m-0 text-[0.86rem] text-(--muted)">{emptyLabel}</p>;
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
    <div className="flex flex-wrap items-center gap-5">
      <svg
        className="size-[132px] shrink-0"
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
      <ul className="m-0 grid min-w-[180px] flex-1 list-none gap-2 p-0">
        {data.map((item, index) => (
          <li className="flex items-center gap-2 text-[0.86rem]" key={item.id}>
            <span
              aria-hidden="true"
              className="size-3 shrink-0 rounded"
              style={{ background: seriesColour(index) }}
            />
            <span className="min-w-0 flex-1 truncate">{item.label}</span>
            <span className="font-[640] text-(--muted) tabular-nums">
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
  valueColor,
}: {
  data: ChartDatum[];
  emptyLabel: string;
  valueColor?: string;
}) {
  if (data.length === 0) {
    return <p className="m-0 text-[0.86rem] text-(--muted)">{emptyLabel}</p>;
  }
  // A zero-width bar for every Agent is honest but unreadable, so the scale
  // falls back to one and every bar renders empty.
  const peak = Math.max(1, ...data.map((item) => item.value));
  return (
    <ul className="m-0 grid min-w-[180px] flex-1 list-none gap-2 p-0">
      {data.map((item, index) => (
        <li
          className="grid grid-cols-[minmax(72px,0.35fr)_1fr_auto] items-center gap-2.5 text-[0.86rem]"
          key={item.id}
        >
          <span className="truncate font-[640]">{item.label}</span>
          <span className="h-3 overflow-hidden rounded-full bg-(--line)">
            <span
              className="block h-full min-w-0.5 rounded-full"
              style={{
                background: item.color ?? seriesColour(index),
                width: `${(item.value / peak) * 100}%`,
              }}
            />
          </span>
          <span
            className="font-[640] text-(--muted) tabular-nums"
            style={{ color: valueColor }}
          >
            {item.value}
          </span>
        </li>
      ))}
    </ul>
  );
}
