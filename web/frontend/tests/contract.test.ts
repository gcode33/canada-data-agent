import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { EVENT_TYPES, type UiEvent } from "../src/events";
import { hrefFor, isOver, replayAll } from "../src/reducer";
import { delays, MAX_MS, MIN_MS } from "../src/pace";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const REPLAYS = join(ROOT, "public", "replays");
const SCHEMA = JSON.parse(readFileSync(join(ROOT, "..", "schema", "events.v1.json"), "utf8"));

describe("the event types match the schema", () => {
  it("has exactly the schema's event type names", () => {
    const consts = Object.values(SCHEMA.$defs as Record<string, any>)
      .map((d) => d.properties?.type?.const)
      .filter(Boolean)
      .sort();
    expect([...EVENT_TYPES].sort()).toEqual(consts);
  });
});

describe("every bundled replay drives the reducer to a finished run", () => {
  if (!existsSync(REPLAYS)) throw new Error("no replays: run `uv run canada-web build-demo` first");
  const files = readdirSync(REPLAYS).filter((f: string) => f.endsWith(".json"));
  it("has all 24 replays", () => expect(files).toHaveLength(24));
  for (const file of files) {
    it(file, () => {
      const events = JSON.parse(readFileSync(join(REPLAYS, file), "utf8")) as UiEvent[];
      const state = replayAll(events);
      expect(state.run).not.toBeNull();
      expect(isOver(state)).toBe(true);
      expect(state.steps.every((s) => s.done)).toBe(true);
      if (state.failed) {
        expect(state.answer).toBeNull();
        expect(state.series).toHaveLength(0);
      } else {
        expect(state.answer).not.toBeNull();
      }
    });
  }
});

describe("links", () => {
  it("only a server-marked link becomes an href", () => {
    expect(hrefFor({ url: "https://example.test/x", linkable: false })).toBeNull();
    expect(hrefFor({ url: "https://a.test/x", linkable: true })).toBe("https://a.test/x");
  });
});

describe("pacing", () => {
  const events = new Array(10).fill({ type: "step_started" }) as UiEvent[];
  it("plays instantly under reduced motion", () => {
    expect(delays(events, 9, true).every((d) => d === 0)).toBe(true);
  });
  it("spreads the recorded wall time within bounds", () => {
    const d = delays(events, 9, false);
    expect(d[0]).toBe(0);
    expect(d.slice(1).every((x) => x >= MIN_MS && x <= MAX_MS)).toBe(true);
  });
});

describe("the reducer", () => {
  it("closes a step that never finished when the run ends", () => {
    const state = replayAll([
      { type: "run_started", mode: "replay", category: "rejected", question: "q", model: "m",
        prompt_version: "p", provenance: { source: "live" }, attack: null },
      { type: "step_started", step_id: "s1", tool: "get_series", arguments_text: "{}" },
      { type: "run_failed", code: "BUDGET_EXCEEDED", message: "over budget" },
    ] as UiEvent[]);
    expect(state.steps[0]?.done).toBe(true);
    expect(state.steps[0]?.summary).toBe("stopped");
  });
});
