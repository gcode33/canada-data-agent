// Replay pacing (A8 U9). Recorded timings are used when present; otherwise the recorded wall
// time is spread evenly over the events ("approximate pace"). Reduced motion plays instantly.
import type { UiEvent } from "./events";

export const MIN_MS = 120;
export const MAX_MS = 1500;

export function delays(events: UiEvent[], wallSeconds: number | null, reduced: boolean): number[] {
  if (reduced || events.length === 0) return events.map(() => 0);
  const total = (wallSeconds ?? 6) * 1000;
  const each = Math.min(MAX_MS, Math.max(MIN_MS, total / events.length));
  return events.map((_, i) => (i === 0 ? 0 : each));
}
