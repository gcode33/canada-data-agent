// Replay pacing (A8 U9). Today's recordings carry no per-step timings, so the recorded wall time
// is spread evenly over the events, and every replay says "Approximate pace". (Per-step timings
// arrive with U2's P3; using them is a follow-up.) Reduced motion plays instantly.
import type { UiEvent } from "./events";

export const MIN_MS = 120;
export const MAX_MS = 1500;

export function delays(events: UiEvent[], wallSeconds: number | null, reduced: boolean): number[] {
  if (reduced || events.length === 0) return events.map(() => 0);
  const total = (wallSeconds ?? 6) * 1000;
  const each = Math.min(MAX_MS, Math.max(MIN_MS, total / events.length));
  return events.map((_, i) => (i === 0 ? 0 : each));
}
