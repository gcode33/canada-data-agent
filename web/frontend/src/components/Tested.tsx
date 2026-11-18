// "How it's tested" (A8 §11, D2). Every number comes from tested.json, which build-demo derives
// from committed evidence (README headline, history.jsonl, the gate receipt, baseline, flakiness
// study, and the gate's own constants). The sentences are fixed text, written to say exactly
// what the code checks (the U1 honesty review found the first version overclaimed).
import { useEffect, useState } from "react";

interface TestedData {
  held_out: {
    passed: number;
    total: number;
    percent: number;
    wilson: [number, number];
    release: string;
    model: string;
  };
  gate: { model: string; k: number; passed: boolean; mean_pass_rate: number; cases: number };
  rules: { k: number; study_k: number; flip_max_passes: number; max_mean_drop: number; max_usd: number };
  baseline: { model: string; k: number; mean_pass_rate: number; stable: number; unstable: string[] };
  study: { model: string; k: number; mean_pass_rate: number };
  links: { repo: string; staged_gate_failure: string; headline: string };
}

const pct = (x: number) => `${Math.round(x * 100)}%`;
const BASE = import.meta.env.BASE_URL;

export function Tested() {
  const [data, setData] = useState<TestedData | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    fetch(`${BASE}tested.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then(setData)
      .catch(() => setFailed(true));
  }, []);
  if (failed) return <p role="alert">The test results couldn't be loaded.</p>;
  if (!data) return <p className="muted">Loading…</p>;
  const h = data.held_out;
  const r = data.rules;
  return (
    <article className="tested">
      <h2 tabIndex={-1}>How it's tested</h2>
      <section className="card">
        <h3>Held-out result ({h.release})</h3>
        <p className="big">
          {h.passed}/{h.total} correct ({h.percent}%, 95% Wilson interval {h.wilson[0]}–{h.wilson[1]}%)
        </p>
        <p>
          {h.total} questions whose answers weren't looked at while the agent was built, run once
          at the release on {h.model}. With so few questions the interval is wide: the honest
          reading is the range.{" "}
          <a href={data.links.headline} rel="noopener noreferrer" target="_blank">
            How held-out it really is
          </a>
          . The replays on this site are the other set: the dev questions it was tuned on.
        </p>
        <img
          className="history-chart"
          src={`${BASE}chart.svg`}
          alt={`Pass rates with 95% Wilson intervals: held-out ${h.percent}% (${h.wilson[0]}–${h.wilson[1]}%) and the dev set it was tuned on.`}
        />
      </section>
      <section className="card">
        <h3>The eval gate</h3>
        <p>
          Every change to the agent must pass a gate before it merges: the {data.gate.cases} dev
          questions × {r.k} on {data.gate.model}, judged against a baseline from a separate{" "}
          {r.study_k}-repeat study (mean {pct(data.baseline.mean_pass_rate)}, {data.baseline.stable}{" "}
          cases passing every time). A change fails the gate if:
        </p>
        <ul>
          <li>
            a case that passed {r.study_k}/{r.study_k} in the study passes {r.flip_max_passes} of {r.k} or
            fewer;
          </li>
          <li>the mean pass rate drops more than {Math.round(r.max_mean_drop * 100)} points;</li>
          <li>any planted attack gets through, or an attack never fired;</li>
          <li>the run costs more than ${r.max_usd.toFixed(2)} (API-equivalent).</li>
        </ul>
        <p>
          The current receipt <strong>{data.gate.passed ? "passed" : "failed"}</strong>, mean{" "}
          {pct(data.gate.mean_pass_rate)}. The gate runs {data.gate.model}; the replays and the
          held-out result are {h.model}. Cases not yet stable on {data.baseline.model}:{" "}
          {data.baseline.unstable.join(", ")}. A staged demonstration of the gate failing a one-line
          bug is{" "}
          <a href={data.links.staged_gate_failure} rel="noopener noreferrer" target="_blank">
            pull request #24
          </a>{" "}
          (never merged).
        </p>
      </section>
      <section className="card">
        <h3>What's checked before an answer is shown</h3>
        <ul>
          <li>
            Each level the answer reports must equal a value the tools returned for that series in
            this run. The check doesn't look at the period, and changes, ratios and numbers in the
            prose are the model's own.
          </li>
          <li>
            Every cited link must be a Statistics Canada table URL a tool returned in this run. An
            answer carrying any other link, host or email address is refused.
          </li>
          <li>
            Text from the data (table cards, member names, error messages) is marked as untrusted,
            and the agent's instructions forbid following it. The link and level checks are the
            code's backstop: models still sometimes quote planted text.
          </li>
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
