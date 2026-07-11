// MSR (Market Stability Reserve) feature — extracted verbatim from
// frontend/src/components/Editor.jsx (MSR panel, market step).

import { CollapsibleGroup, numInput } from "@core/components/EditorPrimitives.jsx";
import { SummaryPathwayPanel, orderedSummaryRows } from "@core/components/ResultPrimitives.jsx";

function MsrEditorSection({ ctx }) {
  const { workingScenario, updateScenario } = ctx;
  return (
    <CollapsibleGroup title="Market Stability Reserve (MSR)" defaultOpen={false}>
    <div className="msr-panel">
      <div className="msr-panel-head">
        <div className="msr-panel-title-row">
          <span className="msr-panel-label">Market Stability Reserve (MSR)</span>
          <label className="msr-enabled-toggle">
            <input
              type="checkbox"
              checked={!!workingScenario.msr_enabled}
              onChange={(e) => updateScenario({ msr_enabled: e.target.checked })}
            />
            <span>Enable MSR</span>
          </label>
        </div>
        <p className="msr-panel-hint">
          Automatically adjusts auction supply based on total banked allowances.
          Withholds volume when the bank is too large; releases from reserve when the bank is too small.
        </p>
      </div>
      {workingScenario.msr_enabled && (
        <div className="msr-params-grid">
          <label>
            <span className="ekey">Upper threshold (Mt) <span className="field-flag required">required</span></span>
            <span className="solver-settings-desc">Bank above this → withhold from auction. Default: 200 Mt</span>
            {numInput(workingScenario.msr_upper_threshold ?? 200, (v) => updateScenario({ msr_upper_threshold: Math.max(0, v) }), 10, 0)}
          </label>
          <label>
            <span className="ekey">Lower threshold (Mt) <span className="field-flag required">required</span></span>
            <span className="solver-settings-desc">Bank below this → release from reserve. Default: 50 Mt</span>
            {numInput(workingScenario.msr_lower_threshold ?? 50, (v) => updateScenario({ msr_lower_threshold: Math.max(0, v) }), 10, 0)}
          </label>
          <label>
            <span className="ekey">Withhold rate <span className="field-flag required">required</span></span>
            <span className="solver-settings-desc">Fraction of auction supply withheld per year (0–1). Default: 0.12 (12%)</span>
            {numInput(workingScenario.msr_withhold_rate ?? 0.12, (v) => updateScenario({ msr_withhold_rate: Math.min(1, Math.max(0, v)) }), 0.01, 0)}
          </label>
          <label>
            <span className="ekey">Release rate (Mt/yr) <span className="field-flag required">required</span></span>
            <span className="solver-settings-desc">Mt released from reserve per year when bank is below lower threshold. Default: 50 Mt</span>
            {numInput(workingScenario.msr_release_rate ?? 50, (v) => updateScenario({ msr_release_rate: Math.max(0, v) }), 5, 0)}
          </label>
          <label>
            <span className="ekey">Cancellation threshold (Mt) <span className="field-flag optional">optional</span></span>
            <span className="solver-settings-desc">Reserve pool above this is permanently cancelled if cancellation is enabled. Default: 400 Mt</span>
            {numInput(workingScenario.msr_cancel_threshold ?? 400, (v) => updateScenario({ msr_cancel_threshold: Math.max(0, v) }), 10, 0)}
          </label>
          <label className="msr-cancel-toggle-label">
            <span className="ekey">Cancel pool excess <span className="field-flag optional">optional</span></span>
            <span className="solver-settings-desc">Permanently retire reserve pool allowances above the cancellation threshold.</span>
            <select
              value={workingScenario.msr_cancel_excess ? "true" : "false"}
              onChange={(e) => updateScenario({ msr_cancel_excess: e.target.value === "true" })}
            >
              <option value="false">disabled</option>
              <option value="true">enabled</option>
            </select>
          </label>
        </div>
      )}
    </div>
    </CollapsibleGroup>
  );
}

// ── Result-side: MSR reserve summary panel (WO-F2) ───────────────────────
// No component rendered payload.summary's "MSR Withheld" / "MSR Released" /
// "MSR Reserve Pool" columns before this order — new, additive panel.
// Self-hides (renders null) when every year's value is zero, so scenarios
// where MSR never actually triggers (bank stays inside the thresholds) show
// nothing, matching the all-features-enabled shell's current behaviour.

const MSR_METRICS = [
  { key: "MSR Withheld", label: "MSR Withheld (Mt)" },
  { key: "MSR Released", label: "MSR Released (Mt)" },
  { key: "MSR Reserve Pool", label: "MSR Reserve Pool (Mt)" },
];

function MsrReservePanel({ ctx }) {
  const { scenario, summary } = ctx;
  const rows = orderedSummaryRows(scenario, summary);
  const hasData = rows.some((row) =>
    MSR_METRICS.some((metric) => Number(row[metric.key] || 0) !== 0)
  );
  if (!hasData) return null;
  return (
    <SummaryPathwayPanel
      eyebrow="Market Stability Reserve"
      title="MSR withhold, release, and reserve pool by year"
      description={`Auction-supply adjustment driven by the total banked-allowance threshold rule, for ${scenario.name}.`}
      scenario={scenario}
      rows={rows}
      metrics={MSR_METRICS}
    />
  );
}

// ── Guide: pe-shell module section (only rendered when this model uses
// MSR — see frontend/src/components/GuideView.jsx). Core guide intro stays
// unconditional; this is additive.

function MsrGuideSection() {
  return (
    <div className="guide-body">
      <p className="guide-lead">
        The <strong>Market Stability Reserve (MSR)</strong> automatically adjusts how many
        allowances are offered at auction each year, based on the total bank of unused
        allowances in circulation.
      </p>
      <p>
        When the bank grows above the <strong>upper threshold</strong>, a share of that year's
        auction volume is withheld and moved into the reserve instead of being sold. When the
        bank falls below the <strong>lower threshold</strong>, allowances are released back out
        of the reserve to top up supply. An optional cancellation rule can permanently retire
        reserve volume once it exceeds a cancellation threshold.
      </p>
      <div className="guide-tip">
        <strong>Where to look:</strong> configure MSR in the "Market Stability Reserve (MSR)"
        group on the Model tab; the withheld / released / reserve-pool pathway appears as its
        own panel on the Analysis tab once the reserve actually triggers for a year.
      </div>
    </div>
  );
}

export default {
  id: "msr",
  scenarioDefaults: {
    msr_enabled: false,
    msr_upper_threshold: 200,
    msr_lower_threshold: 50,
    msr_withhold_rate: 0.12,
    msr_release_rate: 50,
    msr_cancel_excess: false,
    msr_cancel_threshold: 400,
  },
  editorSections: [MsrEditorSection],
  summaryPanels: [MsrReservePanel],
  guideSections: [{ id: "module-msr", tag: "MSR", title: "Market Stability Reserve", content: MsrGuideSection }],
};
