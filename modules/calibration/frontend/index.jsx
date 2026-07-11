// Calibration feature — Nelder-Mead solver tuning for scenario calibration.
// Extracted verbatim from frontend/src/components/Editor.jsx (Calibration
// solver group, market step). No defaults exist in makeBlankScenario today
// (the fields fall back to their in-editor defaults via `??`), so
// scenarioDefaults is intentionally omitted here.

import { CollapsibleGroup, numInput } from "@core/components/EditorPrimitives.jsx";

// Numerical-internals fields behind this whole group (see
// solverSectionVisible in Editor.jsx / AppShared.jsx's
// PE_SOLVER_FIELD_DEFAULTS). The whole group counts as one "Solver
// tuning"-style subsection, per the owner's rule — no per-field split.
const CALIBRATION_SOLVER_FIELDS = ["solver_calibration_xatol", "solver_calibration_fatol"];

function CalibrationEditorSection({ ctx }) {
  const { workingScenario, updateScenario, solverSectionVisible = () => true } = ctx;
  if (!solverSectionVisible(CALIBRATION_SOLVER_FIELDS)) return null;
  return (
    <CollapsibleGroup title="Calibration solver" defaultOpen={false}>
      <div className="solver-settings-grid">
        <label>
          <span className="ekey">Calibration xatol <span className="field-flag optional">optional</span></span>
          <span className="solver-settings-desc">Nelder-Mead slope change tolerance. Smaller = tighter fit but slower. Default: 0.1</span>
          {numInput(workingScenario.solver_calibration_xatol ?? 0.1, (v) => updateScenario({ solver_calibration_xatol: Math.max(1e-6, v) }), 0.01, 1e-6)}
        </label>
        <label>
          <span className="ekey">Calibration fatol <span className="field-flag optional">optional</span></span>
          <span className="solver-settings-desc">Nelder-Mead MSE change tolerance. Smaller = tighter fit but slower. Default: 0.01</span>
          {numInput(workingScenario.solver_calibration_fatol ?? 0.01, (v) => updateScenario({ solver_calibration_fatol: Math.max(1e-8, v) }), 0.001, 1e-8)}
        </label>
      </div>
    </CollapsibleGroup>
  );
}

// ── Guide: pe-shell module section (only rendered when this model uses
// calibration — see frontend/src/components/GuideView.jsx).

function CalibrationGuideSection() {
  return (
    <div className="guide-body">
      <p className="guide-lead">
        <strong>Calibration</strong> fits scenario parameters to a target using a Nelder-Mead
        search, rather than requiring every coefficient to be hand-tuned. Its two tolerances
        trade fit quality for solve time.
      </p>
      <div className="guide-tip">
        <strong>Where to look:</strong> the "Calibration solver" group on the Model tab sets the
        slope-change (xatol) and error-change (fatol) convergence tolerances the calibration run
        uses.
      </div>
    </div>
  );
}

export default {
  id: "calibration",
  editorSections: [CalibrationEditorSection],
  guideSections: [{ id: "module-calibration", tag: "CALIB", title: "Calibration", content: CalibrationGuideSection }],
};
