// A hand-written SVG line chart (A8 U5, D4). A series with fewer than 3 values gets a value tile
// instead. Every chart has a one-sentence summary (its accessible name) and a data table.
import type { Series } from "../events";
import { SeriesTable } from "./SeriesTable";

const W = 560;
const H = 220;
const PAD = { top: 16, right: 16, bottom: 32, left: 56 };

export function summarize(s: Series): string {
  const known = s.points.filter((p) => p.value !== null);
  const name = s.label ?? `Series ${s.vector_id}`;
  const first = known[0];
  const last = known[known.length - 1];
  if (!first || !last) return `${name}: no published values in this range.`;
  const gaps = s.points.length - known.length;
  const scale = s.scalar_factor !== "units" ? ` (${s.scalar_factor})` : "";
  return (
    `${name}, ${first.ref_period} to ${last.ref_period}: ${first.value} to ${last.value}${scale}` +
    (gaps ? `; ${gaps} suppressed value${gaps > 1 ? "s" : ""}.` : ".")
  );
}

// Path segments: a suppressed (null) value breaks the line instead of dropping to zero.
export function segments(values: (number | null)[]): number[][] {
  const out: number[][] = [];
  let run: number[] = [];
  values.forEach((v, i) => {
    if (v === null) {
      if (run.length) out.push(run);
      run = [];
    } else run.push(i);
  });
  if (run.length) out.push(run);
  return out;
}

export function Chart({ series, index }: { series: Series; index: number }) {
  const values = series.points.map((p) => p.value);
  const known = values.filter((v): v is number => v !== null);
  const sentence = summarize(series);
  if (known.length < 3) {
    const last = [...series.points].reverse().find((p) => p.value !== null);
    return (
      <figure className="tile">
        <p className="tile-value">
          {last ? last.value : "—"}
          {last ? <span className="tile-period"> {last.ref_period}</span> : null}
        </p>
        <figcaption>{sentence}</figcaption>
        <SeriesTable series={series} />
      </figure>
    );
  }
  const min = Math.min(...known);
  const max = Math.max(...known);
  const span = max - min || 1;
  const x = (i: number) =>
    PAD.left + (i * (W - PAD.left - PAD.right)) / Math.max(1, series.points.length - 1);
  const y = (v: number) => PAD.top + ((max - v) * (H - PAD.top - PAD.bottom)) / span;
  const first = series.points[0]?.ref_period ?? "";
  const last = series.points[series.points.length - 1]?.ref_period ?? "";
  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={sentence} focusable="false">
        <line className="axis" x1={PAD.left} y1={H - PAD.bottom} x2={W - PAD.right} y2={H - PAD.bottom} />
        <text className="tick" x={PAD.left - 8} y={y(max) + 4} textAnchor="end">{max}</text>
        <text className="tick" x={PAD.left - 8} y={y(min) + 4} textAnchor="end">{min}</text>
        <text className="tick" x={PAD.left} y={H - 10}>{first}</text>
        <text className="tick" x={W - PAD.right} y={H - 10} textAnchor="end">{last}</text>
        {segments(values).map((seg, k) => (
          <polyline
            key={k}
            className={`line line-${(index % 2) + 1}`}
            points={seg.map((i) => `${x(i)},${y(values[i] as number)}`).join(" ")}
          />
        ))}
        {values.map((v, i) =>
          v === null ? (
            <text key={i} className="tick gap" x={x(i)} y={H - PAD.bottom - 6} textAnchor="middle">
              ×
            </text>
          ) : null,
        )}
      </svg>
      <figcaption>
        {sentence}
        {values.some((v) => v === null) ? " × marks a suppressed value." : ""}
        {min > 0 ? " The vertical axis spans the values shown; it doesn't start at zero." : ""}
      </figcaption>
      <SeriesTable series={series} />
    </figure>
  );
}
