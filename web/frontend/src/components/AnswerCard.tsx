import type { Answer, Series } from "../events";
import { hrefFor } from "../reducer";
import { CHANGE_NOTE } from "../text";
import { SeriesTable } from "./SeriesTable";

const LABELS = { level: "Level", change_abs: "Change", change_pct: "Change (%)", ratio: "Ratio" };

export function AnswerCard({ answer, series }: { answer: Answer; series: Series[] }) {
  const hasChange = answer.answer_values.some((v) => v.label !== "level");
  return (
    <section className="card answer" aria-labelledby="answer-heading">
      <h2 id="answer-heading" tabIndex={-1}>
        {answer.refused ? "The agent declined" : "Answer"}
      </h2>
      <p className="prose">{answer.answer}</p>
      {answer.answer_values.length > 0 ? (
        <table className="values">
          <caption>Values reported</caption>
          <thead>
            <tr>
              <th scope="col">What</th>
              <th scope="col">Kind</th>
              <th scope="col">Value</th>
              <th scope="col">Period</th>
            </tr>
          </thead>
          <tbody>
            {answer.answer_values.map((v, i) => (
              <tr key={i}>
                <td>{v.description}</td>
                <td>{LABELS[v.label]}</td>
                <td className="num">
                  {v.value} {v.unit}
                </td>
                <td>{v.ref_period}</td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : null}
      {hasChange ? <p className="muted small">{CHANGE_NOTE}</p> : null}
      {series.map((s) => (
        <SeriesTable key={`${s.step_id}-${s.vector_id}`} series={s} />
      ))}
      {answer.links.length > 0 ? (
        <div className="sources">
          <h3>Sources</h3>
          <ul>
            {answer.links.map((l, i) => {
              const href = hrefFor(l);
              return (
                <li key={i}>
                  {href ? (
                    <a href={href} rel="noopener noreferrer" target="_blank">
                      {l.url}
                    </a>
                  ) : (
                    <span className="muted">{l.url} (not linked: no tool returned it)</span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
