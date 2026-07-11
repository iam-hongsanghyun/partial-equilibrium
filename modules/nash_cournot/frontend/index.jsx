// Nash-Cournot feature — strategic participant selection and solver
// tuning. Extracted verbatim from frontend/src/components/Editor.jsx
// (Nash extra fields, inside "Modelling approach").

import { numInput } from "@core/components/EditorPrimitives.jsx";

// Numerical-internals fields behind this module's own "Solver tuning" block
// (see solverSectionVisible in Editor.jsx / AppShared.jsx's
// PE_SOLVER_FIELD_DEFAULTS).
const NASH_SOLVER_FIELDS = [
  "solver_nash_price_step",
  "solver_nash_max_iters",
  "solver_nash_convergence_tol",
  "solver_nash_inner_xatol",
];

function NashApproachParams({ ctx }) {
  const { workingScenario, updateScenario, workingYear, solverSectionVisible = () => true } = ctx;
  const allNames = (workingYear.participants || []).map((x) => x.name);
  const current = workingScenario.nash_strategic_participants || [];
  const effective = current.length === 0 ? allNames : current;

  // Group by sector_group
  const bySector = {};
  (workingYear.participants || []).forEach((p) => {
    const sector = p.sector_group || "";
    if (!bySector[sector]) bySector[sector] = [];
    bySector[sector].push(p);
  });

  // Sort keys alphabetically, empty string last
  const sectorKeys = Object.keys(bySector).sort((a, b) => {
    if (a === "" && b !== "") return 1;
    if (a !== "" && b === "") return -1;
    return a.localeCompare(b);
  });

  return (
    <div className="approach-params">
      <div className="ekey" style={{ marginBottom: 6 }}>
        Strategic participants <span className="field-flag optional">optional</span>
        <span className="approach-params-hint" style={{ display: "block", marginTop: 2 }}>
          Select which participants behave strategically (internalize price impact). Leave all unchecked to make everyone strategic.
        </span>
      </div>
      {(workingYear.participants || []).length === 0 && (
        <span className="muted" style={{ fontSize: 12 }}>No participants yet — add them in Step 3.</span>
      )}
      {sectorKeys.map((sector) => {
        const sectorParticipants = bySector[sector];
        const sectorNames = sectorParticipants.map((p) => p.name);
        const allSectorStrategic = sectorNames.every((n) => effective.includes(n));

        return (
          <div key={sector || "__ungrouped__"} className="approach-nash-sector-group">
            <div className="approach-nash-sector-header">
              <span className="approach-nash-sector-label">
                {sector || "Ungrouped"}
              </span>
              <button
                type="button"
                className="approach-nash-sector-toggle"
                onClick={() => {
                  if (allSectorStrategic) {
                    const next = effective.filter((n) => !sectorNames.includes(n));
                    updateScenario({ nash_strategic_participants: next });
                  } else {
                    const next = [...new Set([...effective, ...sectorNames])];
                    updateScenario({ nash_strategic_participants: next });
                  }
                }}
              >
                {allSectorStrategic ? "Deselect all" : "Select all"}
              </button>
            </div>
            <div className="approach-nash-participants">
              {sectorParticipants.map((p) => {
                const isStrategic = effective.includes(p.name);
                return (
                  <label key={p.name} className="approach-nash-check">
                    <input
                      type="checkbox"
                      checked={isStrategic}
                      onChange={(e) => {
                        const base = current.length === 0 ? allNames : current;
                        const next = e.target.checked
                          ? [...new Set([...base, p.name])]
                          : base.filter((n) => n !== p.name);
                        updateScenario({ nash_strategic_participants: next });
                      }}
                    />
                    <span>{p.name}</span>
                  </label>
                );
              })}
            </div>
          </div>
        );
      })}
      {solverSectionVisible(NASH_SOLVER_FIELDS) && (
      <>
      <div className="approach-params-tuning-label">Solver tuning</div>
      <div className="solver-settings-grid">
        <label>
          <span className="ekey">Price step ($/t) <span className="field-flag optional">optional</span></span>
          <span className="solver-settings-desc">Finite-difference step for estimating market power (dP/dQ). Default: 0.5</span>
          {numInput(
            workingScenario.solver_nash_price_step ?? 0.5,
            (v) => updateScenario({ solver_nash_price_step: Math.max(1e-4, v) }),
            0.1, 1e-4
          )}
        </label>
        <label>
          <span className="ekey">Max best-response iterations <span className="field-flag optional">optional</span></span>
          <span className="solver-settings-desc">Nash convergence loop limit. Default: 120</span>
          {numInput(
            workingScenario.solver_nash_max_iters ?? 120,
            (v) => updateScenario({ solver_nash_max_iters: Math.max(1, Math.round(v)) }),
            1, 1
          )}
        </label>
        <label>
          <span className="ekey">Abatement convergence tolerance <span className="field-flag optional">optional</span></span>
          <span className="solver-settings-desc">Max abatement change across participants per iteration. Default: 0.001</span>
          {numInput(
            workingScenario.solver_nash_convergence_tol ?? 0.001,
            (v) => updateScenario({ solver_nash_convergence_tol: Math.max(1e-8, v) }),
            0.0001, 1e-8
          )}
        </label>
        <label>
          <span className="ekey">Inner solver tolerance (xatol) <span className="field-flag optional">optional</span></span>
          <span className="solver-settings-desc">Abatement tolerance for the per-participant best-response minimiser. Default: 0.0001</span>
          {numInput(workingScenario.solver_nash_inner_xatol ?? 1e-4, (v) => updateScenario({ solver_nash_inner_xatol: Math.max(1e-10, v) }), 1e-5, 1e-10)}
        </label>
      </div>
      </>
      )}
    </div>
  );
}

// ── Guide: pe-shell module section (only rendered when this model uses
// the Nash–Cournot approach — see frontend/src/components/GuideView.jsx).

function NashGuideSection() {
  return (
    <div className="guide-body">
      <p className="guide-lead">
        The <strong>Nash–Cournot</strong> approach lets selected participants behave
        strategically: instead of taking the market price as given, a strategic participant
        internalizes how its own abatement/trading decisions move the price, and the solver
        iterates each participant's best response until no one can improve by changing their own
        move (a Nash equilibrium).
      </p>
      <p>
        Choose which participants are strategic (leave all unchecked to make everyone
        strategic) inside "Modelling approach" when Nash–Cournot is selected.
      </p>
      <div className="guide-tip">
        <strong>Where to look:</strong> solver tuning (price step, best-response iterations,
        convergence tolerances) sits below the strategic-participant picker.
      </div>
    </div>
  );
}

export default {
  id: "nash_cournot",
  scenarioDefaults: {
    nash_strategic_participants: [],
    solver_nash_price_step: 0.5,
    solver_nash_max_iters: 120,
    solver_nash_convergence_tol: 0.001,
  },
  approachOptions: [NashApproachParams],
  guideSections: [{ id: "module-nash_cournot", tag: "NASH", title: "Nash–Cournot", content: NashGuideSection }],
};
