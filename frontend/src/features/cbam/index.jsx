// CBAM (Carbon Border Adjustment Mechanism) feature — EUA/external
// reference prices (scenario/year level) plus the participant-level CBAM
// exposure and Scope 2 / indirect-emissions panels. Extracted verbatim from
// frontend/src/components/Editor.jsx.

import { CollapsibleGroup, numInput } from "../../components/EditorPrimitives.jsx";
import { fmt } from "../../components/MarketChart.jsx";

function CbamEuaPricesSection({ ctx }) {
  const { workingYear, updateYear } = ctx;
  return (
    <CollapsibleGroup title="EUA & external prices" defaultOpen={false}>
    {/* ── EUA prices (per-jurisdiction) ────────────────────────────── */}
    <div className="eua-prices-panel">
      <div className="eua-prices-head">
        <span className="eua-prices-label">EUA prices by jurisdiction <span className="field-flag optional">optional</span></span>
        <button type="button" className="ghost-btn on" style={{fontSize: 12}} onClick={() => {
          const prices = { ...(workingYear.eua_prices || {}), "UK": 50 };
          updateYear({ eua_prices: prices });
        }}>+ Add</button>
      </div>
      <span className="approach-params-hint">Per-jurisdiction reference prices for multi-jurisdiction CBAM. Key must match a jurisdiction name in participant's CBAM table (e.g. "UK", "US", "JPN").</span>
      {Object.entries(workingYear.eua_prices || {}).map(([key, val]) => (
        <div key={key} className="eua-prices-row">
          <input type="text" className="text" value={key} style={{width: 70}}
            onChange={(e) => {
              const prices = { ...(workingYear.eua_prices || {}) };
              delete prices[key]; prices[e.target.value] = val;
              updateYear({ eua_prices: prices });
            }} />
          {numInput(val ?? 0, (v) => {
            const prices = { ...(workingYear.eua_prices || {}), [key]: v };
            updateYear({ eua_prices: prices });
          }, 1, 0)}
          <button type="button" className="ghost-btn" style={{fontSize: 11, padding: "2px 6px"}} onClick={() => {
            const prices = { ...(workingYear.eua_prices || {}) };
            delete prices[key];
            updateYear({ eua_prices: prices });
          }}>✕</button>
        </div>
      ))}
    </div>

    {/* ── EUA ensemble ─────────────────────────────────────────────── */}
    <div className="eua-prices-panel">
      <div className="eua-prices-head">
        <span className="eua-prices-label">EUA price ensemble <span className="field-flag optional">optional</span></span>
        <button type="button" className="ghost-btn on" style={{fontSize: 12}} onClick={() => {
          const ens = { ...(workingYear.eua_price_ensemble || {}), "EC": 65 };
          updateYear({ eua_price_ensemble: ens });
        }}>+ Add</button>
      </div>
      <span className="approach-params-hint">Named EUA trajectories (e.g. EC, Enerdata, BNEF). Each generates a separate CBAM liability column in the output — enabling price uncertainty analysis.</span>
      {Object.entries(workingYear.eua_price_ensemble || {}).map(([key, val]) => (
        <div key={key} className="eua-prices-row">
          <input type="text" className="text" value={key} style={{width: 80}}
            onChange={(e) => {
              const ens = { ...(workingYear.eua_price_ensemble || {}) };
              delete ens[key]; ens[e.target.value] = val;
              updateYear({ eua_price_ensemble: ens });
            }} />
          {numInput(val ?? 0, (v) => {
            const ens = { ...(workingYear.eua_price_ensemble || {}), [key]: v };
            updateYear({ eua_price_ensemble: ens });
          }, 1, 0)}
          <button type="button" className="ghost-btn" style={{fontSize: 11, padding: "2px 6px"}} onClick={() => {
            const ens = { ...(workingYear.eua_price_ensemble || {}) };
            delete ens[key];
            updateYear({ eua_price_ensemble: ens });
          }}>✕</button>
        </div>
      ))}
    </div>
    </CollapsibleGroup>
  );
}

function CbamExposureSection({ ctx }) {
  const { participant, selectedParticipantIndex, updateParticipant } = ctx;
  return (
    <CollapsibleGroup title="CBAM exposure" defaultOpen={false}>
    <div className="cbam-participant-panel">
      <div className="cbam-participant-head">
        <span className="cbam-participant-label">CBAM exposure</span>
        <span className="cbam-participant-hint">
          Carbon Border Adjustment Mechanism — set export share &gt; 0 to compute
          CBAM liability on this participant's residual emissions.
          Use <em>single jurisdiction</em> (EU only) or <em>multi-jurisdiction</em> for UK / US / Japan.
        </span>
      </div>
      <div className="builder-form-grid">
        <label>
          <span className="ekey">EU export share <span className="field-flag optional">optional</span></span>
          {numInput(
            participant.cbam_export_share ?? 0,
            (v) => updateParticipant(selectedParticipantIndex, { cbam_export_share: Math.min(1, Math.max(0, v)) }),
            0.05, 0
          )}
          <span className="approach-params-hint">Used when cbam_jurisdictions is empty (EU-only shorthand).</span>
        </label>
        <label>
          <span className="ekey">CBAM coverage ratio <span className="field-flag optional">optional</span></span>
          {numInput(
            participant.cbam_coverage_ratio ?? 1,
            (v) => updateParticipant(selectedParticipantIndex, { cbam_coverage_ratio: Math.min(1, Math.max(0, v)) }),
            0.05, 0
          )}
        </label>
      </div>
      {/* Multi-jurisdiction table */}
      <div className="cbam-jur-section">
        <div className="cbam-jur-head">
          <span className="cbam-jur-label">Multi-jurisdiction CBAM <span className="field-flag optional">optional</span></span>
          <button type="button" className="ghost-btn on" style={{fontSize: 12}} onClick={() => {
            const jurs = [...(participant.cbam_jurisdictions || []), { name: "UK", export_share: 0.1, coverage_ratio: 1.0 }];
            updateParticipant(selectedParticipantIndex, { cbam_jurisdictions: jurs });
          }}>+ Add jurisdiction</button>
        </div>
        <span className="approach-params-hint">When non-empty, replaces the EU-only fields above. Reference prices come from the year's EUA Prices table.</span>
        {(participant.cbam_jurisdictions || []).map((jur, ji) => (
          <div key={ji} className="cbam-jur-row">
            <input type="text" className="text" placeholder="Name (EU/UK/US/JPN)" value={jur.name ?? ""} style={{width: 90}}
              onChange={(e) => {
                const jurs = [...(participant.cbam_jurisdictions || [])];
                jurs[ji] = { ...jurs[ji], name: e.target.value };
                updateParticipant(selectedParticipantIndex, { cbam_jurisdictions: jurs });
              }} />
            {numInput(jur.export_share ?? 0, (v) => {
              const jurs = [...(participant.cbam_jurisdictions || [])];
              jurs[ji] = { ...jurs[ji], export_share: Math.min(1, Math.max(0, v)) };
              updateParticipant(selectedParticipantIndex, { cbam_jurisdictions: jurs });
            }, 0.05, 0)}
            <span style={{fontSize: 11, color: "#666"}}>share</span>
            {numInput(jur.coverage_ratio ?? 1, (v) => {
              const jurs = [...(participant.cbam_jurisdictions || [])];
              jurs[ji] = { ...jurs[ji], coverage_ratio: Math.min(1, Math.max(0, v)) };
              updateParticipant(selectedParticipantIndex, { cbam_jurisdictions: jurs });
            }, 0.05, 0)}
            <span style={{fontSize: 11, color: "#666"}}>cov</span>
            <button type="button" className="ghost-btn" style={{fontSize: 11, padding: "2px 6px"}} onClick={() => {
              const jurs = (participant.cbam_jurisdictions || []).filter((_, i) => i !== ji);
              updateParticipant(selectedParticipantIndex, { cbam_jurisdictions: jurs });
            }}>✕</button>
          </div>
        ))}
      </div>
    </div>
    </CollapsibleGroup>
  );
}

function Scope2Section({ ctx }) {
  const { workingScenario, participant, selectedParticipantIndex, updateParticipant } = ctx;
  return (
    <CollapsibleGroup title="Scope 2 / Indirect emissions" defaultOpen={false}>
    <div className="scope2-panel">
      <div className="scope2-head">
        <span className="scope2-label">Scope 2 / Indirect Emissions</span>
        <span className="approach-params-hint">Electricity-based indirect emissions and CBAM exposure. Indirect emissions = consumption × emission factor.</span>
      </div>
      <div className="builder-form-grid">
        <div className="builder-form-field">
          <label>Electricity consumption (MWh)</label>
          <input type="number" min="0" step="100"
            value={participant.electricity_consumption ?? 0}
            onChange={(e) => updateParticipant(selectedParticipantIndex, { electricity_consumption: +e.target.value })} />
        </div>
        <div className="builder-form-field">
          <label>Grid emission factor (tCO₂/MWh)</label>
          <input type="number" min="0" step="0.001"
            value={participant.grid_emission_factor ?? 0}
            onChange={(e) => updateParticipant(selectedParticipantIndex, { grid_emission_factor: +e.target.value })} />
          <span className="approach-params-hint">Indirect emissions = consumption × factor. Korean grid ≈ 0.45 tCO₂/MWh.</span>
          {/* Grid emission factor trajectory */}
          {(() => {
            const traj = participant.grid_emission_factor_trajectory || {};
            const active = !!(traj.start_year && traj.end_year && traj.start_value !== undefined && traj.end_value !== undefined);
            const years = workingScenario.years || [];
            const startY = years.length ? String(years[0].year) : "2026";
            const endY = years.length ? String(years[years.length - 1].year) : "2035";
            const curGef = Number(participant.grid_emission_factor || 0.45);
            return (
              <div className="traj-section" style={{ marginTop: 4 }}>
                <div className="traj-head">
                  <span className="traj-label" style={{ fontSize: 10 }}>Grid EF trajectory</span>
                  {active
                    ? <button type="button" className="ghost-btn" style={{ fontSize: 10, padding: "1px 6px" }} onClick={() => updateParticipant(selectedParticipantIndex, { grid_emission_factor_trajectory: {} })}>Clear</button>
                    : <button type="button" className="ghost-btn on" style={{ fontSize: 10, padding: "1px 6px" }} onClick={() => updateParticipant(selectedParticipantIndex, { grid_emission_factor_trajectory: { start_year: startY, end_year: endY, start_value: curGef, end_value: curGef * 0.5 } })}>Enable trajectory</button>
                  }
                </div>
                {active && (
                  <div className="traj-row" style={{ gridTemplateColumns: "60px 60px 90px 90px", gap: 5, padding: "5px 8px" }}>
                    <div className="builder-form-field" style={{ margin: 0 }}>
                      <label style={{ fontSize: 10 }}>Start yr</label>
                      <input type="text" value={traj.start_year ?? ""} onChange={(e) => updateParticipant(selectedParticipantIndex, { grid_emission_factor_trajectory: { ...traj, start_year: e.target.value } })} />
                    </div>
                    <div className="builder-form-field" style={{ margin: 0 }}>
                      <label style={{ fontSize: 10 }}>End yr</label>
                      <input type="text" value={traj.end_year ?? ""} onChange={(e) => updateParticipant(selectedParticipantIndex, { grid_emission_factor_trajectory: { ...traj, end_year: e.target.value } })} />
                    </div>
                    <div className="builder-form-field" style={{ margin: 0 }}>
                      <label style={{ fontSize: 10 }}>Start (tCO₂/MWh)</label>
                      <input type="number" step="0.001" value={traj.start_value ?? ""} onChange={(e) => updateParticipant(selectedParticipantIndex, { grid_emission_factor_trajectory: { ...traj, start_value: +e.target.value } })} />
                    </div>
                    <div className="builder-form-field" style={{ margin: 0 }}>
                      <label style={{ fontSize: 10 }}>End (tCO₂/MWh)</label>
                      <input type="number" step="0.001" value={traj.end_value ?? ""} onChange={(e) => updateParticipant(selectedParticipantIndex, { grid_emission_factor_trajectory: { ...traj, end_value: +e.target.value } })} />
                    </div>
                  </div>
                )}
              </div>
            );
          })()}
        </div>
        <div className="builder-form-field">
          <label>Scope 2 CBAM coverage (0–1)</label>
          <input type="number" min="0" max="1" step="0.1"
            value={participant.scope2_cbam_coverage ?? 0}
            onChange={(e) => updateParticipant(selectedParticipantIndex, { scope2_cbam_coverage: +e.target.value })} />
          <span className="approach-params-hint">0 = Scope 2 not covered by CBAM (current default). 1 = fully covered (6-month extension scenario).</span>
        </div>
      </div>
    </div>
    </CollapsibleGroup>
  );
}

// ── Result-side: participant drilldown stat rows (WO-F2) ────────────────
// Extracted verbatim from frontend/src/components/ParticipantPanel.jsx
// (indirect_emissions, scope2_cbam_liability) plus a new CBAM-liability row
// (cbam_liability — the /api/run payload already carries this key on every
// perParticipant record; no component rendered it before this extraction).
// Each stat self-hides (renders null) when its value is absent/zero, so the
// all-features shell is pixel-identical to today on non-CBAM models.

function IndirectEmissionsStat({ ctx }) {
  const { r } = ctx;
  if (!(r.indirect_emissions > 0)) return null;
  return <div className="stat"><span className="label">Indirect Emissions</span><span className="val">{fmt.num(r.indirect_emissions, 1)}</span></div>;
}

function Scope2CbamStat({ ctx }) {
  const { r } = ctx;
  if (!(r.scope2_cbam_liability > 0)) return null;
  return <div className="stat"><span className="label">Scope 2 CBAM</span><span className="val">{fmt.money(r.scope2_cbam_liability)}</span></div>;
}

function CbamLiabilityStat({ ctx }) {
  const { r } = ctx;
  if (!(r.cbam_liability > 0)) return null;
  return <div className="stat"><span className="label">CBAM Liability</span><span className="val">{fmt.money(r.cbam_liability)}</span></div>;
}

export default {
  id: "cbam",
  participantDefaults: {
    cbam_export_share: 0,
    cbam_coverage_ratio: 1,
    cbam_jurisdictions: [],
    // Scope 2 / indirect emissions
    electricity_consumption: 0,
    grid_emission_factor: 0,
    scope2_cbam_coverage: 0,
    grid_emission_factor_trajectory: {},
  },
  editorSections: [CbamEuaPricesSection],
  participantEditorSections: [CbamExposureSection, Scope2Section],
  resultStats: [IndirectEmissionsStat, Scope2CbamStat, CbamLiabilityStat],
};
