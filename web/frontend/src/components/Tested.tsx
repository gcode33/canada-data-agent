// "How it's tested" (A8 §11, D2): built from tested.json, which build-demo derives from the
// committed gate receipt, baseline and README headline. Nothing here is hand-typed.
import { useEffect, useState } from "react";

interface TestedData {
  held_out: { passed: number; total: number; percent: number; wilson: [number, number]; release: string };
  gate: { model: string; k: number; passed: boolean; mean_pass_rate: number; cases: number };
  baseline: { model: string; k: number; mean_pass_rate: number; stable: number; unstable: string[] };
  links: { repo: string; staged_gate_failure: string };
}

const pct = (x: number) => `${Math.round(x * 100)}%`;

export function Tested() {
  const [data, setData] = useState<TestedData | null>(null);
  useEffect(() => {
    fetch(`${import.meta.env.BASE_URL}tested.json`)
      .then((r) => (r.ok ? r.json() : null))
      .then(setData)
      .catch(() => setData(null));
  }, []);
  if (!data) return <p className="muted">Loading…</p>;
  const h = data.held_out;
  return (
    <article className="tested">
      <h2 tabIndex={-1}>How it's tested</h2>
      <section className="card">
        <h3>Held-out result ({h.release})</h3>
        <p className="big">
          {h.passed}/{h.total} correct ({h.percent}%, 95% Wilson interval {h.wilson[0]}–{h.wilson[1]}%)
        </p>
        <p>
          On {h.total} questions whose answers were never looked at while the agent was built, run
          once at the release. The replays on this site are the other set: the dev questions it was
          tuned on.
        </p>
      </section>
      <section className="card">
        <h3>The eval gate</h3>
        <p>
          Every change to the agent must pass a gate: the {data.gate.cases} dev questions ×{" "}
          {data.gate.k} on {data.gate.model}, judged against a baseline from a separate{" "}
          {data.baseline.k}-repeat study ({pct(data.baseline.mean_pass_rate)} mean, {data.baseline.stable}{" "}
          cases stable). It fails a change if a stable case flips, the mean drops more than 10
          points, or any planted attack gets through. The current receipt:{" "}
          <strong>{data.gate.passed ? "passed" : "failed"}</strong>, mean {pct(data.gate.mean_pass_rate)}.
        </p>
        <p>
          Cases that aren't stable yet: {data.baseline.unstable.join(", ")}. A staged demonstration of
          the gate failing a one-line bug is{" "}
          <a href={data.links.staged_gate_failure} rel="noopener noreferrer" target="_blank">
            pull request #24
          </a>{" "}
          (never merged).
        </p>
      </section>
      <section className="card">
        <h3>Every answer is checked before anyone sees it</h3>
        <ul>
          <li>Every number must be one a tool returned in that run, cited to its StatCan table.</li>
          <li>Any link, host or address that isn't StatCan's is refused, after Unicode normalisation.</li>
          <li>Text from the data (table cards, member names, error messages) is treated as data, never instructions.</li>
        </ul>
        <p>
          <a href={data.links.repo} rel="noopener noreferrer" target="_blank">
            The code, the evals and every finding are on GitHub.
          </a>
        </p>
      </section>
    </article>
  );
}
