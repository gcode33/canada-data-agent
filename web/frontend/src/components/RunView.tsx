import type { RunState } from "../reducer";
import { isOver } from "../reducer";
import { attackCaption } from "../text";
import { AnswerCard } from "./AnswerCard";
import { Steps } from "./Steps";

export function RunView({ state }: { state: RunState }) {
  const run = state.run;
  if (!run) return null;
  const prov = run.provenance;
  const running = !isOver(state);
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
      <Steps steps={state.steps} running={running} />
      {state.answer ? <AnswerCard answer={state.answer} series={state.series} /> : null}
      {state.failed ? (
        <section className="card failed" role="alert">
          <h2 tabIndex={-1}>No answer shown</h2>
          <p>{state.failed.message}</p>
          <p className="muted small">Code: {state.failed.code}</p>
        </section>
      ) : null}
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
