import type { Series } from "../events";

export function SeriesTable({ series }: { series: Series }) {
  const title = series.label ?? `Series ${series.vector_id}`;
  return (
    <details className="series-table">
      <summary>
        Data: {title} ({series.points.length} points)
      </summary>
      <table>
        <caption>
          {title}. Values as published by Statistics Canada
          {series.scalar_factor !== "units" ? ` (in ${series.scalar_factor})` : ""}.{" "}
          <a href={series.table_url} rel="noopener noreferrer" target="_blank">
            Table {series.product_id}
          </a>
        </caption>
        <thead>
          <tr>
            <th scope="col">Period</th>
            <th scope="col">Value</th>
          </tr>
        </thead>
        <tbody>
          {series.points.map((p) => (
            <tr key={p.ref_period}>
              <th scope="row">{p.ref_period}</th>
              <td className="num">{p.value === null ? "suppressed" : p.value}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}
