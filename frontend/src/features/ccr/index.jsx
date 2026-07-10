// CCR (Carbon Cap Rule) feature — extracted verbatim from
// frontend/src/components/Editor.jsx (CCR panel, market step).
// Adaptive, Taylor-rule-style cap (Benmir, Roman & Taschini 2025).

import { CollapsibleGroup, numInput } from "../../components/EditorPrimitives.jsx";
import { SummaryPathwayPanel, orderedSummaryRows } from "../../components/ResultPrimitives.jsx";

function CcrEditorSection({ ctx }) {
  const { workingScenario, updateScenario } = ctx;
  return (
    <CollapsibleGroup title="Carbon Cap Rule (CCR)" defaultOpen={false}>
    <div className="msr-panel">
      <div className="msr-panel-head">
        <div className="msr-panel-title-row">
          <span className="msr-panel-label">Carbon Cap Rule (CCR)</span>
          <label className="msr-enabled-toggle">
            <input
              type="checkbox"
              checked={!!workingScenario.ccr_enabled}
              onChange={(e) => updateScenario({ ccr_enabled: e.target.checked })}
            />
            <span>Enable CCR</span>
          </label>
        </div>
        <p className="msr-panel-hint">
          Adaptive, Taylor-rule-style cap (Benmir, Roman &amp; Taschini 2025). Each year's permit
          quantity adjusts to the <em>previous</em> year's deviation of emissions and abatement cost
          from their reference levels:
          Q&nbsp;=&nbsp;Q̄&nbsp;+&nbsp;φ<sub>e</sub>·(e−ē)/ē&nbsp;+&nbsp;φ<sub>z</sub>·(z−z̄)/z̄.
          Use φ<sub>z</sub>&nbsp;&gt;&nbsp;0 to issue more permits when abatement costs run hot, and
          φ<sub>e</sub>&nbsp;&lt;&nbsp;0 to tighten when emissions overshoot.
        </p>
      </div>
      {workingScenario.ccr_enabled && (
        <div className="msr-params-grid">
          <label>
            <span className="ekey">φ emissions (Mt) <span className="field-flag required">required</span></span>
            <span className="solver-settings-desc">Cap change per unit fractional emissions gap. Paper-optimal sign: negative (tighten when emissions exceed reference). Default: 0 (off)</span>
            {numInput(workingScenario.ccr_phi_emissions ?? 0, (v) => updateScenario({ ccr_phi_emissions: v }), 1, undefined)}
          </label>
          <label>
            <span className="ekey">φ abatement cost (Mt) <span className="field-flag required">required</span></span>
            <span className="solver-settings-desc">Cap change per unit fractional abatement-cost gap. Paper-optimal sign: positive (loosen when costs exceed reference). Default: 0 (off)</span>
            {numInput(workingScenario.ccr_phi_abatement_cost ?? 0, (v) => updateScenario({ ccr_phi_abatement_cost: v }), 1, undefined)}
          </label>
          <label>
            <span className="ekey">Reference emissions ē (Mt) <span className="field-flag required">required</span></span>
            <span className="solver-settings-desc">Steady-state emissions the gap is measured against. 0 disables the emissions term.</span>
            {numInput(workingScenario.ccr_reference_emissions ?? 0, (v) => updateScenario({ ccr_reference_emissions: Math.max(0, v) }), 10, 0)}
          </label>
          <label>
            <span className="ekey">Reference abatement cost z̄ <span className="field-flag required">required</span></span>
            <span className="solver-settings-desc">Steady-state abatement cost the gap is measured against. 0 disables the cost term.</span>
            {numInput(workingScenario.ccr_reference_abatement_cost ?? 0, (v) => updateScenario({ ccr_reference_abatement_cost: Math.max(0, v) }), 100, 0)}
          </label>
        </div>
      )}
    </div>
    </CollapsibleGroup>
  );
}

// ── Result-side: CCR cap-adjustment summary panel (WO-F2) ────────────────
// No component rendered payload.summary's "CCR Cap Adjustment" / deviation
// columns before this order — new, additive panel. Self-hides when every
// year's value is zero (CCR disabled or phi coefficients both zero).

const CCR_METRICS = [
  { key: "CCR Cap Adjustment", label: "Cap Adjustment (Mt)" },
  { key: "CCR Emissions Deviation", label: "Emissions Deviation" },
  { key: "CCR Cost Deviation", label: "Abatement Cost Deviation" },
];

function CcrPanel({ ctx }) {
  const { scenario, summary } = ctx;
  const rows = orderedSummaryRows(scenario, summary);
  const hasData = rows.some((row) =>
    CCR_METRICS.some((metric) => Number(row[metric.key] || 0) !== 0)
  );
  if (!hasData) return null;
  return (
    <SummaryPathwayPanel
      eyebrow="Carbon Cap Rule"
      title="CCR cap adjustment and reference deviations by year"
      description={`Adaptive Taylor-rule cap adjustment and the emissions/abatement-cost gaps driving it, for ${scenario.name}.`}
      scenario={scenario}
      rows={rows}
      metrics={CCR_METRICS}
    />
  );
}

export default {
  id: "ccr",
  scenarioDefaults: {
    ccr_enabled: false,
    ccr_phi_emissions: 0,
    ccr_phi_abatement_cost: 0,
    ccr_reference_emissions: 0,
    ccr_reference_abatement_cost: 0,
  },
  editorSections: [CcrEditorSection],
  summaryPanels: [CcrPanel],
};
