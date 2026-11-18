import { useEffect, useMemo, useRef, useState } from "react";
import type { IndexEntry, UiEvent } from "./events";
import { delays } from "./pace";
import { apply, EMPTY, type RunState } from "./reducer";
import { RunView } from "./components/RunView";
import { CATEGORY_NAMES, LIBRARY_HEADER } from "./text";

const BASE = import.meta.env.BASE_URL;
const FIRST = "multi-04"; // multi-step, with two 13-point series: steps and a chart at once

function wanted(): string | null {
  return new URLSearchParams(window.location.search).get("case");
}

export function App() {
  const [index, setIndex] = useState<IndexEntry[]>([]);
  const [selected, setSelected] = useState<string | null>(wanted() ?? FIRST);
  const [state, setState] = useState<RunState>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const timers = useRef<number[]>([]);
  const reduced = useMemo(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches, []);

  useEffect(() => {
    fetch(`${BASE}index.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data: IndexEntry[]) => setIndex(data))
      .catch(() => setError("The replay list couldn't be loaded."));
  }, []);

  useEffect(() => {
    if (!selected || !index.some((e) => e.case === selected)) return;
    timers.current.forEach(clearTimeout);
    timers.current = [];
    setState(EMPTY);
    const url = new URL(window.location.href);
    url.searchParams.set("case", selected);
    window.history.replaceState(null, "", url);
    fetch(`${BASE}replays/${encodeURIComponent(selected)}.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((events: UiEvent[]) => {
        const first = events[0];
        const wall =
          first?.type === "run_started" && first.provenance.source === "recording"
            ? first.provenance.recorded_wall_s
            : null;
        let at = 0;
        delays(events, wall, reduced).forEach((d, i) => {
          at += d;
          const e = events[i];
          if (!e) return;
          timers.current.push(window.setTimeout(() => setState((s) => apply(s, e)), at));
        });
      })
      .catch(() => setError("That replay couldn't be loaded."));
    return () => timers.current.forEach(clearTimeout);
  }, [selected, index, reduced]);

  const groups = (Object.keys(CATEGORY_NAMES) as (keyof typeof CATEGORY_NAMES)[]).map((cat) => ({
    cat,
    entries: index.filter((e) => e.category === cat),
  }));

  return (
    <div className="layout">
      <header className="site-header">
        <h1>Canada Data Agent</h1>
        <p className="muted">
          An AI agent that answers questions with Statistics Canada data and cites every number,
          plus the eval suite that tests it.
        </p>
      </header>
      <nav className="library" aria-label="Recorded runs">
        <p className="small muted">{LIBRARY_HEADER}</p>
        {groups.map(({ cat, entries }) =>
          entries.length ? (
            <section key={cat}>
              <h2 className="group">
                {CATEGORY_NAMES[cat]} ({entries.length})
              </h2>
              <ul>
                {entries.map((e) => (
                  <li key={e.case}>
                    <button
                      type="button"
                      className="pick"
                      aria-current={e.case === selected ? "true" : undefined}
                      onClick={() => setSelected(e.case)}
                    >
                      {e.question}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          ) : null,
        )}
      </nav>
      <main className="stage">
        {error ? <p role="alert">{error}</p> : <RunView state={state} />}
      </main>
    </div>
  );
}
