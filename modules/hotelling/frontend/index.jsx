// Hotelling Rule feature — optimal-depletion approach params and solver
// tuning. Extracted verbatim from frontend/src/components/Editor.jsx
// (Hotelling extra fields, inside "Modelling approach"). Embeds the
// elastic_baseline reference-carbon-price field at its original position
// (between risk premium and carbon budget) — a pre-existing cross-cutting
// UI placement, not a new coupling introduced by this extraction.

import { numInput } from "@core/components/EditorPrimitives.jsx";
import { ReferenceCarbonPriceField } from "@features/elastic_baseline/frontend/index.jsx";

// Numerical-internals fields behind this module's own "Solver tuning" block
// (see solverSectionVisible in Editor.jsx / AppShared.jsx's
// PE_SOLVER_FIELD_DEFAULTS — pe mode hides this block behind "Show advanced
// settings" unless the loaded config already ships non-default values).
const HOTELLING_SOLVER_FIELDS = [
  "solver_hotelling_max_bisection_iters",
  "solver_hotelling_max_lambda_expansions",
  "solver_hotelling_convergence_tol",
  "solver_hotelling_lambda_initial_low",
  "solver_hotelling_lambda_initial_high",
  "solver_hotelling_lambda_expand_factor",
];

function HotellingApproachParams({ ctx }) {
  const {
    workingScenario, updateScenario, workingYear, updateYear, openMarketSeriesEditor, activeFeatures,
    solverSectionVisible = () => true,
  } = ctx;
  // Editor.jsx always resolves enabledFeatures to a concrete id list before
  // building ctx (activeFeatureIds(null) => every feature) — in the pe
  // shell that list is the selected model's manifest, so only embed the
  // elastic_baseline field when that feature is actually in play.
  const elasticBaselineActive = (activeFeatures || []).includes("elastic_baseline");
  return (
    <div className="approach-params">
      <label>
        <span className="ekey">Discount rate <span className="field-flag optional">optional</span></span>
        <input
          type="number"
          className="text"
          step="0.01"
          min="0"
          max="0.5"
          value={workingScenario.discount_rate ?? 0.04}
          onChange={(e) => updateScenario({ discount_rate: parseFloat(e.target.value) || 0.04 })}
        />
        <span className="approach-params-hint">Risk-free annual discount rate r. Hotelling price path grows at (1+r+ρ)^t. Default 0.04 = 4%.</span>
      </label>
      <label>
        <span className="ekey">Risk premium (ρ) <span className="field-flag optional">optional</span></span>
        <input
          type="number"
          className="text"
          step="0.005"
          min="0"
          max="0.5"
          value={workingScenario.risk_premium ?? 0.0}
          onChange={(e) => updateScenario({ risk_premium: parseFloat(e.target.value) || 0 })}
        />
        <span className="approach-params-hint">Policy/market risk premium ρ added to discount rate. Steepens the Hotelling price path to match observed prices. Default 0 = pure Hotelling.</span>
      </label>
      {elasticBaselineActive && <ReferenceCarbonPriceField ctx={ctx} />}
      <label>
        <span className="ekey">Carbon budget (this year) <span className="field-flag optional">optional</span></span>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <input
            type="number"
            className="text"
            step="1"
            min="0"
            value={workingYear.carbon_budget || 0}
            onChange={(e) => updateYear({ carbon_budget: parseFloat(e.target.value) || 0 })}
          />
          <button type="button" className="ghost-btn" style={{ flexShrink: 0 }}
            onClick={() => openMarketSeriesEditor("carbon_budget")}>
            Edit pathway ↗
          </button>
        </div>
        <span className="approach-params-hint">Mt CO₂e allowed this year. Set across all years using the pathway chart.</span>
      </label>
      {solverSectionVisible(HOTELLING_SOLVER_FIELDS) && (
      <>
      <div className="approach-params-tuning-label">Solver tuning</div>
      <div className="solver-settings-grid">
        <label>
          <span className="ekey">Max bisection iterations <span className="field-flag optional">optional</span></span>
          <span className="solver-settings-desc">Iterations to find shadow price λ. Default: 80</span>
          {numInput(
            workingScenario.solver_hotelling_max_bisection_iters ?? 80,
            (v) => updateScenario({ solver_hotelling_max_bisection_iters: Math.max(1, Math.round(v)) }),
            1, 1
          )}
        </label>
        <label>
          <span className="ekey">Max bracket expansions <span className="field-flag optional">optional</span></span>
          <span className="solver-settings-desc">Attempts to bracket λ before fallback. Default: 20</span>
          {numInput(
            workingScenario.solver_hotelling_max_lambda_expansions ?? 20,
            (v) => updateScenario({ solver_hotelling_max_lambda_expansions: Math.max(1, Math.round(v)) }),
            1, 1
          )}
        </label>
        <label>
          <span className="ekey">Emissions convergence tolerance <span className="field-flag optional">optional</span></span>
          <span className="solver-settings-desc">Relative tolerance on cumulative emissions. Default: 0.0001</span>
          {numInput(
            workingScenario.solver_hotelling_convergence_tol ?? 0.0001,
            (v) => updateScenario({ solver_hotelling_convergence_tol: Math.max(1e-9, v) }),
            0.00001, 1e-9
          )}
        </label>
        <label>
          <span className="ekey">λ initial low <span className="field-flag optional">optional</span></span>
          <span className="solver-settings-desc">Lower bound of initial shadow-price bracket. Default: 0.001</span>
          {numInput(workingScenario.solver_hotelling_lambda_initial_low ?? 0.001, (v) => updateScenario({ solver_hotelling_lambda_initial_low: Math.max(1e-6, v) }), 0.001, 1e-6)}
        </label>
        <label>
          <span className="ekey">λ initial high <span className="field-flag optional">optional</span></span>
          <span className="solver-settings-desc">Upper bound of initial shadow-price bracket. Default: 20.0</span>
          {numInput(workingScenario.solver_hotelling_lambda_initial_high ?? 20.0, (v) => updateScenario({ solver_hotelling_lambda_initial_high: Math.max(0.01, v) }), 1, 0.01)}
        </label>
        <label>
          <span className="ekey">λ expand factor <span className="field-flag optional">optional</span></span>
          <span className="solver-settings-desc">Multiplier applied to upper λ bound when bracket is too small. Default: 3.0</span>
          {numInput(workingScenario.solver_hotelling_lambda_expand_factor ?? 3.0, (v) => updateScenario({ solver_hotelling_lambda_expand_factor: Math.max(1.1, v) }), 0.1, 1.1)}
        </label>
      </div>
      </>
      )}
    </div>
  );
}

// ── Guide: pe-shell module section (only rendered when this model uses
// the Hotelling approach — see frontend/src/components/GuideView.jsx).

function HotellingGuideSection() {
  return (
    <div className="guide-body">
      <p className="guide-lead">
        The <strong>Hotelling Rule</strong> approach models optimal depletion of a fixed carbon
        budget: instead of clearing a market year-by-year, the solver finds the shadow price λ
        such that cumulative residual emissions across all years equal the cumulative carbon
        budget, and the price path grows at the <strong>discount rate</strong> plus an optional
        <strong> risk premium</strong> — (1 + r + ρ)^t.
      </p>
      <div className="guide-tip">
        <strong>Where to look:</strong> discount rate, risk premium, and the per-year carbon
        budget are set inside "Modelling approach" when Hotelling is selected; solver tuning
        (bisection iterations, λ bracket, convergence tolerance) sits below them.
      </div>
    </div>
  );
}

export default {
  id: "hotelling",
  scenarioDefaults: {
    discount_rate: 0.04,
    risk_premium: 0.0,
    solver_hotelling_max_bisection_iters: 80,
    solver_hotelling_max_lambda_expansions: 20,
    solver_hotelling_convergence_tol: 0.0001,
  },
  approachOptions: [HotellingApproachParams],
  guideSections: [{ id: "module-hotelling", tag: "HOT", title: "Hotelling Rule", content: HotellingGuideSection }],
};
