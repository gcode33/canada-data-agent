// One reducer for live runs and replays (A8 E1): the page is a pure function of the events seen.
import type { Answer, RunFailed, RunFinished, RunStarted, Series, Tool, UiEvent } from "./events";

export interface Step {
  id: string;
  tool: Tool;
  args: string;
  done: boolean;
  ok: boolean | null;
  latencyMs: number | null;
  errorCode: string | null;
  summary: string;
}

export interface RunState {
  run: RunStarted | null;
  steps: Step[];
  series: Series[];
  answer: Answer | null;
  failed: RunFailed | null;
  finished: RunFinished | null;
}

export const EMPTY: RunState = {
  run: null,
  steps: [],
  series: [],
  answer: null,
  failed: null,
  finished: null,
};

export function apply(state: RunState, event: UiEvent): RunState {
  switch (event.type) {
    case "run_started":
      return { ...EMPTY, run: event };
    case "step_started":
      return {
        ...state,
        steps: [
          ...state.steps,
          {
            id: event.step_id,
            tool: event.tool,
            args: event.arguments_text,
            done: false,
            ok: null,
            latencyMs: null,
            errorCode: null,
            summary: "",
          },
        ],
      };
    case "step_finished":
      return {
        ...state,
        steps: state.steps.map((s) =>
          s.id === event.step_id
            ? {
                ...s,
                done: true,
                ok: event.ok,
                latencyMs: event.latency_ms,
                errorCode: event.error_code,
                summary: event.summary,
              }
            : s,
        ),
      };
    case "series":
      return { ...state, series: [...state.series, event] };
    case "answer":
      return { ...state, answer: event };
    case "run_failed":
      return { ...state, failed: event, steps: closeDangling(state.steps) };
    case "run_finished":
      return { ...state, finished: event, steps: closeDangling(state.steps) };
  }
}

function closeDangling(steps: Step[]): Step[] {
  return steps.map((s) => (s.done ? s : { ...s, done: true, summary: "stopped" }));
}

export function replayAll(events: UiEvent[]): RunState {
  return events.reduce(apply, EMPTY);
}

export const isOver = (s: RunState): boolean => s.failed !== null || s.finished !== null;

// Only a link the server marked linkable becomes an <a> (A8 U4); the browser never decides.
export function hrefFor(link: { url: string; linkable: boolean }): string | null {
  return link.linkable ? link.url : null;
}
