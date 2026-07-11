// Shared multi-market / joint-equilibrium display machinery.
//
// A linked (multi-market / joint-equilibrium) scenario compiles to ONE config
// scenario carrying a `markets` array, and the backend keys its results by the
// composite `"<scenario> :: <market>"` (see core/backend/web/api.py's
// _build_dashboard_payload + _collect_multi_market_results). Both the Composer
// (composer/Composer.jsx) and the model editor (app.jsx, embedded by the
// pe-shell) render each market through the SAME per-scenario views, so the
// flatten helper and the two joint status surfaces live here rather than being
// duplicated in each host.
//
// Config-driven guard: every export below is inert for a scenario WITHOUT a
// `markets` array (flattenRunScenarios returns it untouched) and for a summary
// WITHOUT the backend's present-guarded `Joint *` columns (the row filters
// return empty). A single-market / acyclic run therefore renders nothing
// joint-related, byte-for-byte as before.

// The one summary column whose PRESENCE marks a cyclic-SCC (joint-equilibrium)
// row — the backend stamps the four "Joint *" columns only on those rows
// (dispatch present-guard, mirrored in pe.mcp.compact). Every joint-UI branch
// gates on this exact key being present.
export const JOINT_CONVERGED_COLUMN = "Joint Converged";

// Flatten each `markets`-carrying scenario into one pseudo-scenario per market
// whose `name` is the composite `"<scenario> :: <market>"`, so the existing
// per-scenario display (pills, AnalysisView, trajectory) renders each market
// unchanged. A scenario WITHOUT a `markets` array passes through byte-for-byte.
export function flattenRunScenarios(scenarios) {
  const flattened = [];
  for (const scenario of scenarios || []) {
    const markets = Array.isArray(scenario.markets) ? scenario.markets : null;
    if (markets && markets.length) {
      for (const market of markets) {
        const marketId = String(market.market_id ?? "");
        // Drop the linked-only keys; keep color/description/id-derived meta.
        const { markets: _markets, links: _links, joint_solver: _joint, ...meta } = scenario;
        flattened.push({
          ...meta,
          id: `${scenario.id}::${marketId}`,
          name: `${scenario.name} :: ${marketId}`,
          marketId,
          years: Array.isArray(market.years) ? market.years : [],
        });
      }
    } else {
      flattened.push(scenario);
    }
  }
  return flattened;
}

// The market id half of a composite `"<scenario> :: <market>"` result key.
export function marketLabelFromComposite(name) {
  const text = String(name ?? "");
  return text.includes(" :: ") ? text.split(" :: ").slice(1).join(" :: ") : text;
}

// The summary rows the backend stamps ONLY on cyclic-SCC markets. An acyclic /
// single-market run has no such row, so this returns [] and every joint surface
// below is inert.
export function jointRowsFromSummary(summary) {
  return (summary || []).filter((row) => JOINT_CONVERGED_COLUMN in row);
}

// One problem entry per market (dedupe the identical per-year joint rows):
// did-not-converge, or a detected oscillation (converged flag set but a cycle
// period stamped).
export function jointProblemsFromRows(rows) {
  const byMarket = new Map();
  for (const row of rows || []) {
    const converged = Number(row[JOINT_CONVERGED_COLUMN]) === 1;
    const cycle = Number(row["Joint Cycle Detected"]) || 0;
    if ((converged && cycle === 0) || byMarket.has(row.Scenario)) continue;
    byMarket.set(row.Scenario, row);
  }
  return [...byMarket.values()];
}

// The active market's joint row (or null) for a per-scenario name.
export function jointRowForScenario(rows, scenarioName) {
  if (!scenarioName) return null;
  return (rows || []).find((row) => row.Scenario === scenarioName) || null;
}

// The non-convergence / oscillation banner — reuses App's .server-warnings-*
// banner. Renders nothing when there are no problem markets.
export function JointNonConvergenceBanner({ problems }) {
  if (!problems || !problems.length) return null;
  return (
    <div className="server-warnings-banner">
      <div className="server-warnings-list">
        {problems.map((row) => {
          const market = marketLabelFromComposite(row.Scenario);
          const converged = Number(row[JOINT_CONVERGED_COLUMN]) === 1;
          const iterations = Number(row["Joint Outer Iterations"]) || 0;
          const cycle = Number(row["Joint Cycle Detected"]) || 0;
          const parts = converged
            ? [`Joint equilibrium for ${market} is oscillating after ${iterations} outer iterations — reduce the joint-solver relaxation (more damping) or raise max iterations.`]
            : [`Joint equilibrium did not converge for ${market} after ${iterations} outer iterations — reduce the joint-solver relaxation (more damping) or raise max iterations.`];
          if (cycle > 0) parts.push(`Cycle detected: period ${cycle}.`);
          return (
            <div key={row.Scenario} className="server-warning-item">{parts.join(" ")}</div>
          );
        })}
      </div>
    </div>
  );
}

// The per-market convergence card — reuses the shared .builder-card / .review-grid
// styles. Renders nothing when the active market carries no joint row (acyclic /
// single-market / not-yet-run).
export function JointConvergenceCard({ row }) {
  if (!row) return null;
  return (
    <div className="builder-card">
      <div className="builder-card-head">
        <div>
          <div className="eyebrow">Joint equilibrium</div>
          <h4>
            {Number(row[JOINT_CONVERGED_COLUMN]) === 1
              ? `Converged in ${Number(row["Joint Outer Iterations"]) || 0} iterations`
              : "Did not converge"}
          </h4>
        </div>
      </div>
      <div className="review-grid">
        <div className="review-item">
          <span className="review-label">Converged</span>
          <strong>{Number(row[JOINT_CONVERGED_COLUMN]) === 1 ? "Yes" : "No"}</strong>
        </div>
        <div className="review-item">
          <span className="review-label">Outer iterations</span>
          <strong>{Number(row["Joint Outer Iterations"]) || 0}</strong>
        </div>
        <div className="review-item">
          <span className="review-label">Max normalized change</span>
          <strong>{Number(row["Joint Max Normalized Change"] || 0).toExponential(2)}</strong>
        </div>
        <div className="review-item">
          <span className="review-label">Cycle detected</span>
          <strong>
            {Number(row["Joint Cycle Detected"]) > 0
              ? `period ${Number(row["Joint Cycle Detected"])}`
              : "none"}
          </strong>
        </div>
      </div>
    </div>
  );
}
