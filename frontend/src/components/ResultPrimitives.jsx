// Shared result-side primitives — reused by feature modules
// (frontend/src/features/*) that contribute summaryPanels to AnalysisView.
// One generic "metric rows x year columns" table, driven by a metrics
// config array, rather than a bespoke table per feature (msr/ccr/banking
// all read the same shape of data: payload.summary rows keyed by
// Scenario + Year). Reuses the existing .panel / .pathway-table CSS
// (see AuctionPathwayPanel / the Technology pathway table in
// AppShared.jsx / AppViews.jsx) — no new styling.

import { fmt } from "./MarketChart.jsx";

// Returns one summary row per scenario year, in scenario.years order,
// matched on Scenario + Year (falls back to {} so callers can read absent
// columns as undefined without guarding on the row itself).
export function orderedSummaryRows(scenario, summary) {
  return (scenario.years || []).map((year) => {
    const match = (summary || []).find(
      (row) => row.Scenario === scenario.name && String(row.Year) === String(year.year)
    );
    return match || {};
  });
}

const defaultFormat = (value) => fmt.num(Number(value || 0), 1);

export function SummaryPathwayPanel({ eyebrow, title, description, scenario, rows, metrics }) {
  const years = (scenario.years || []).map((year) => String(year.year));
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <div className="eyebrow">{eyebrow}</div>
          <h2>{title}</h2>
          <p className="muted">{description}</p>
        </div>
      </div>
      <div className="pathway-table-wrap">
        <table className="pathway-table">
          <thead>
            <tr>
              <th>Metric</th>
              {years.map((year) => <th key={year}>{year}</th>)}
            </tr>
          </thead>
          <tbody>
            {metrics.map((metric) => (
              <tr key={metric.key}>
                <td>{metric.label}</td>
                {rows.map((row, index) => (
                  <td key={years[index]}>{(metric.format || defaultFormat)(row[metric.key])}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
