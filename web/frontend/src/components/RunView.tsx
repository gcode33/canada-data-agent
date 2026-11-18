import { useEffect, useRef } from "react";
import type { RunState } from "../reducer";
import { isOver } from "../reducer";
import { attackCaption, TOOL_NAMES } from "../text";
import { AnswerCard } from "./AnswerCard";
import { Steps } from "./Steps";

interface Props {
  state: RunState;
  focusResult: boolean; // move focus to the result when it arrives (only after a user's pick)
  onSkip: (() => void) | null;
}

export function RunView({ state, focusResult, onSkip }: Props) {
  const result = useRef<HTMLElement | null>(null);
  const over = isOver(state);
  useEffect(() => {
    if (over && focusResult) result.current?.querySelector<HTMLElement>("h2")?.focus();
  }, [over, focusResult]);
  const run = state.run;
  if (!run) return null;
  const prov = run.provenance;
  const running = !over;
  const done = state.steps.filter((s) => s.done);
  const latest = done[done.length - 1];
  const announce = over
    ? state.failed
      ? "Run ended without an answer."
      : "Answer ready."
    : latest
      ? `${TOOL_NAMES[latest.tool]} ${latest.ok ? "done" : "failed"}.`
      : "";
  return (
    <article className="run">
      {prov.source === "recording" ? (
        <p className="banner" role="note">
          Replay of a recorded run ({prov.model}, recorded during v1.0 development, commit{" "}
          {prov.commit}, {prov.commit_date}). Not a live model call.{" "}
          {prov.timing === "approximate" ? "Approximate pace." : ""}
        </p>
      ) : null}
      <h2 className="question">{run.question}</h2>
      {run.attack ? <p className="card attack">{attackCaption(run.attack)}</p> : null}
      {running && onSkip ? (
        <button type="button" className="skip" onClick={onSkip}>
          Skip to result
        </button>
      ) : null}
      <p className="sr-only" role="status">
        {announce}
      </p>
      <Steps steps={state.steps} running={running} />
      <div ref={(el) => { result.current = el; }}>
      {state.answer ? <AnswerCard answer={state.answer} series={state.series} /> : null}
      {state.failed ? (
        <section className="card failed" role="alert">
          <h2 tabIndex={-1}>No answer shown</h2>
          <p>{state.failed.message}</p>
          <p className="muted small">Code: {state.failed.code}</p>
        </section>
      ) : null}
      </div>
      {state.finished ? (
        <footer className="run-footer muted small">
          {state.finished.num_turns} turns · {state.steps.length} tool calls ·{" "}
          {(state.finished.duration_ms / 1000).toFixed(1)} s · {run.model} · prompt {run.prompt_version}
          {state.finished.billed === "none"
            ? " · not a model run"
            : ` · API-equivalent $${(state.finished.api_equivalent_usd ?? 0).toFixed(4)}, billed to subscription`}
        </footer>
      ) : null}
    </article>
  );
}
