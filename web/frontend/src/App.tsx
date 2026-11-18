import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { IndexEntry, UiEvent } from "./events";
import { delays } from "./pace";
import { apply, EMPTY, replayAll, type RunState } from "./reducer";
import { RunView } from "./components/RunView";
import { Tested } from "./components/Tested";
import { CATEGORY_NAMES, LIBRARY_HEADER } from "./text";

const BASE = import.meta.env.BASE_URL;
const FIRST = "multi-04"; // multi-step, with two 13-point series: steps and a chart at once
type Tab = "replays" | "tested";

function param(name: string): string | null {
  return new URLSearchParams(window.location.search).get(name);
}

export function App() {
  const [tab, setTab] = useState<Tab>(param("tab") === "tested" ? "tested" : "replays");
  const [index, setIndex] = useState<IndexEntry[]>([]);
  const [selected, setSelected] = useState<string>(param("case") ?? FIRST);
  const [picked, setPicked] = useState(false); // a user choice, not the first-visit auto-play
  const [state, setState] = useState<RunState>(EMPTY);
  const [error, setError] = useState<string | null>(null);
  const timers = useRef<number[]>([]);
  const events = useRef<UiEvent[]>([]);
  const reduced = useMemo(() => window.matchMedia("(prefers-reduced-motion: reduce)").matches, []);

  const stop = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
  };

  useEffect(() => {
    fetch(`${BASE}index.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((data: IndexEntry[]) => setIndex(data))
      .catch(() => setError("The replay list couldn't be loaded."));
  }, []);

  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set("case", selected);
    if (tab === "tested") url.searchParams.set("tab", "tested");
    else url.searchParams.delete("tab");
    window.history.replaceState(null, "", url);
  }, [selected, tab]);

  useEffect(() => {
    if (tab !== "replays" || !index.some((e) => e.case === selected)) return;
    stop();
    setState(EMPTY);
    let cancelled = false;
    fetch(`${BASE}replays/${encodeURIComponent(selected)}.json`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((loaded: UiEvent[]) => {
        if (cancelled) return;
        events.current = loaded;
        const first = loaded[0];
        const wall =
          first?.type === "run_started" && first.provenance.source === "recording"
            ? first.provenance.recorded_wall_s
            : null;
        let at = 0;
        delays(loaded, wall, reduced).forEach((d, i) => {
          at += d;
          const e = loaded[i];
          if (e) timers.current.push(window.setTimeout(() => setState((s) => apply(s, e)), at));
        });
      })
      .catch(() => setError("That replay couldn't be loaded."));
    return () => {
      cancelled = true;
      stop();
    };
  }, [selected, index, reduced, tab]);

  const skip = useCallback(() => {
    stop();
    setState(replayAll(events.current));
  }, []);

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
        <nav className="tabs" aria-label="Sections">
          <button type="button" aria-current={tab === "replays" ? "page" : undefined}
                  onClick={() => setTab("replays")}>
            Replays
          </button>
          <button type="button" aria-current={tab === "tested" ? "page" : undefined}
                  onClick={() => setTab("tested")}>
            How it's tested
          </button>
        </nav>
      </header>
      {tab === "tested" ? (
        <main className="stage wide">
          <Tested />
        </main>
      ) : (
        <>
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
                          onClick={() => {
                            setPicked(true);
                            setSelected(e.case);
                          }}
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
            {error ? (
              <p role="alert">{error}</p>
            ) : (
              <RunView state={state} focusResult={picked} onSkip={reduced ? null : skip} />
            )}
          </main>
        </>
      )}
    </div>
  );
}
