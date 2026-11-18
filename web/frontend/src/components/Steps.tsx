import type { Step } from "../reducer";
import { TOOL_NAMES } from "../text";

export function Steps({ steps, running }: { steps: Step[]; running: boolean }) {
  if (steps.length === 0) return running ? <p className="muted">Starting…</p> : null;
  return (
    <ol className="steps" aria-label="What the agent did">
      {steps.map((s) => (
        <li key={s.id} className={`step ${s.done ? (s.ok ? "ok" : "error") : "pending"}`}>
          <div className="step-head">
            <span className="step-tool">{TOOL_NAMES[s.tool]}</span>
            <span className="step-status">
              {!s.done ? "working…" : s.ok ? "done" : s.errorCode ? `failed: ${s.errorCode}` : s.summary}
              {s.latencyMs !== null ? ` · ${(s.latencyMs / 1000).toFixed(2)} s` : ""}
            </span>
          </div>
          <code className="step-args">{s.args}</code>
          {s.done && s.ok ? <p className="step-summary">{s.summary}</p> : null}
        </li>
      ))}
    </ol>
  );
}
