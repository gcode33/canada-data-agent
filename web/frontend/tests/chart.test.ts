import { describe, expect, it } from "vitest";
import { segments, summarize } from "../src/components/Chart";
import type { Series } from "../src/events";

const series = (values: (number | null)[], label: string | null = "Rent index"): Series => ({
  type: "series",
  step_id: "s1",
  product_id: 18100004,
  table_url: "x",
  vector_id: 41691116,
  scalar_factor: "units",
  truncated: false,
  label,
  points: values.map((value, i) => ({
    ref_period: `2026-0${i + 1}`,
    value,
    status_symbol: value === null ? ".." : null,
  })),
});

describe("chart", () => {
  it("breaks the line at a suppressed value instead of drawing zero", () => {
    expect(segments([1, 2, null, 4, 5])).toEqual([[0, 1], [3, 4]]);
    expect(segments([null, null])).toEqual([]);
  });
  it("summarizes first to last known value, and says what's suppressed", () => {
    expect(summarize(series([161.2, null, 164.4]))).toBe(
      "Rent index, 2026-01 to 2026-03: 161.2 to 164.4; 1 suppressed value.",
    );
    expect(summarize(series([null], null))).toBe("Series 41691116: no published values in this range.");
  });
});
