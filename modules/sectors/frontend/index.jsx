// Sectors feature — sector-level cap/auction-share pools and the
// participant-level sector_group field that assigns a participant to one.
// Extracted from frontend/src/components/Editor.jsx (Sectors panel,
// participant "Sector group" field) verbatim; behaviour unchanged.

import { CollapsibleGroup } from "@core/components/EditorPrimitives.jsx";
import { makeBlankSector } from "@core/components/AppShared.jsx";

function SectorsEditorSection({ ctx }) {
  const { workingScenario, updateScenario } = ctx;
  return (
    <CollapsibleGroup title="Sectors" defaultOpen={true} badge={(workingScenario.sectors||[]).length ? String((workingScenario.sectors||[]).length) : null}>
    <div className="sector-panel">
      <div className="sector-panel-head">
        <button
          type="button"
          className="ghost-btn on"
          style={{ fontSize: 12 }}
          onClick={() => updateScenario({ sectors: [...(workingScenario.sectors || []), makeBlankSector()] })}
        >
          + Add sector
        </button>
      </div>
      <span className="approach-params-hint">
        When sectors are defined, total_cap and auction_offered are derived from the sum of sector caps.
        Each participant's free allocation ratio is computed from their sector pool and sector_allocation_share.
      </span>
      <div className="sector-list">
        {(workingScenario.sectors || []).map((sector, si) => {
          const capActive = !!(sector.cap_trajectory?.start_year && sector.cap_trajectory?.end_year
            && sector.cap_trajectory?.start_value !== undefined && sector.cap_trajectory?.end_value !== undefined);
          const aucActive = !!(sector.auction_share_trajectory?.start_year && sector.auction_share_trajectory?.end_year
            && sector.auction_share_trajectory?.start_value !== undefined && sector.auction_share_trajectory?.end_value !== undefined);
          return (
            <div key={si} className="sector-row">
              <div className="sector-row-fields">
                <label style={{ flex: 2 }}>
                  <span style={{ fontSize: 11 }}>Name</span>
                  <input
                    type="text"
                    className="text"
                    value={sector.name ?? ""}
                    onChange={(e) => {
                      const next = [...(workingScenario.sectors || [])];
                      next[si] = { ...next[si], name: e.target.value };
                      updateScenario({ sectors: next });
                    }}
                  />
                </label>
                <label style={{ flex: 1 }}>
                  <span style={{ fontSize: 11 }}>Carbon budget (Mt)</span>
                  <input
                    type="number"
                    className="num"
                    step="1"
                    min="0"
                    value={sector.carbon_budget ?? 0}
                    onChange={(e) => {
                      const next = [...(workingScenario.sectors || [])];
                      next[si] = { ...next[si], carbon_budget: +e.target.value };
                      updateScenario({ sectors: next });
                    }}
                  />
                </label>
                <button
                  type="button"
                  className="ghost-btn danger-btn"
                  style={{ fontSize: 11, padding: "2px 8px", alignSelf: "flex-end" }}
                  onClick={() => updateScenario({ sectors: (workingScenario.sectors || []).filter((_, i) => i !== si) })}
                >
                  Remove
                </button>
              </div>
              {/* Cap trajectory */}
              <div className="traj-section" style={{ marginTop: 6 }}>
                <div className="traj-head">
                  <span className="traj-label" style={{ fontSize: 11 }}>Cap trajectory</span>
                  {capActive
                    ? <button type="button" className="ghost-btn" style={{ fontSize: 10, padding: "1px 6px" }} onClick={() => {
                        const next = [...(workingScenario.sectors || [])];
                        next[si] = { ...next[si], cap_trajectory: {} };
                        updateScenario({ sectors: next });
                      }}>Clear</button>
                    : <button type="button" className="ghost-btn on" style={{ fontSize: 10, padding: "1px 6px" }} onClick={() => {
                        const years = workingScenario.years || [];
                        const startY = years.length ? String(years[0].year) : "2026";
                        const endY = years.length ? String(years[years.length - 1].year) : "2035";
                        const next = [...(workingScenario.sectors || [])];
                        next[si] = { ...next[si], cap_trajectory: { start_year: startY, end_year: endY, start_value: 100, end_value: 60 } };
                        updateScenario({ sectors: next });
                      }}>Enable</button>
                  }
                </div>
                {capActive && (
                  <div className="traj-row" style={{ gridTemplateColumns: "70px 70px 100px 100px", gap: 6, padding: "6px 10px" }}>
                    <div className="builder-form-field" style={{ margin: 0 }}>
                      <label style={{ fontSize: 10 }}>Start year</label>
                      <input type="text" value={sector.cap_trajectory.start_year ?? ""} onChange={(e) => {
                        const next = [...(workingScenario.sectors || [])];
                        next[si] = { ...next[si], cap_trajectory: { ...next[si].cap_trajectory, start_year: e.target.value } };
                        updateScenario({ sectors: next });
                      }} />
                    </div>
                    <div className="builder-form-field" style={{ margin: 0 }}>
                      <label style={{ fontSize: 10 }}>End year</label>
                      <input type="text" value={sector.cap_trajectory.end_year ?? ""} onChange={(e) => {
                        const next = [...(workingScenario.sectors || [])];
                        next[si] = { ...next[si], cap_trajectory: { ...next[si].cap_trajectory, end_year: e.target.value } };
                        updateScenario({ sectors: next });
                      }} />
                    </div>
                    <div className="builder-form-field" style={{ margin: 0 }}>
                      <label style={{ fontSize: 10 }}>Start value (Mt)</label>
                      <input type="number" step="1" value={sector.cap_trajectory.start_value ?? ""} onChange={(e) => {
                        const next = [...(workingScenario.sectors || [])];
                        next[si] = { ...next[si], cap_trajectory: { ...next[si].cap_trajectory, start_value: +e.target.value } };
                        updateScenario({ sectors: next });
                      }} />
                    </div>
                    <div className="builder-form-field" style={{ margin: 0 }}>
                      <label style={{ fontSize: 10 }}>End value (Mt)</label>
                      <input type="number" step="1" value={sector.cap_trajectory.end_value ?? ""} onChange={(e) => {
                        const next = [...(workingScenario.sectors || [])];
                        next[si] = { ...next[si], cap_trajectory: { ...next[si].cap_trajectory, end_value: +e.target.value } };
                        updateScenario({ sectors: next });
                      }} />
                    </div>
                  </div>
                )}
              </div>
              {/* Auction share trajectory */}
              <div className="traj-section" style={{ marginTop: 4 }}>
                <div className="traj-head">
                  <span className="traj-label" style={{ fontSize: 11 }}>Auction share trajectory (0–1)</span>
                  {aucActive
                    ? <button type="button" className="ghost-btn" style={{ fontSize: 10, padding: "1px 6px" }} onClick={() => {
                        const next = [...(workingScenario.sectors || [])];
                        next[si] = { ...next[si], auction_share_trajectory: {} };
                        updateScenario({ sectors: next });
                      }}>Clear</button>
                    : <button type="button" className="ghost-btn on" style={{ fontSize: 10, padding: "1px 6px" }} onClick={() => {
                        const years = workingScenario.years || [];
                        const startY = years.length ? String(years[0].year) : "2026";
                        const endY = years.length ? String(years[years.length - 1].year) : "2035";
                        const next = [...(workingScenario.sectors || [])];
                        next[si] = { ...next[si], auction_share_trajectory: { start_year: startY, end_year: endY, start_value: 0, end_value: 0.3 } };
                        updateScenario({ sectors: next });
                      }}>Enable</button>
                  }
                </div>
                {aucActive && (
                  <div className="traj-row" style={{ gridTemplateColumns: "70px 70px 100px 100px", gap: 6, padding: "6px 10px" }}>
                    <div className="builder-form-field" style={{ margin: 0 }}>
                      <label style={{ fontSize: 10 }}>Start year</label>
                      <input type="text" value={sector.auction_share_trajectory.start_year ?? ""} onChange={(e) => {
                        const next = [...(workingScenario.sectors || [])];
                        next[si] = { ...next[si], auction_share_trajectory: { ...next[si].auction_share_trajectory, start_year: e.target.value } };
                        updateScenario({ sectors: next });
                      }} />
                    </div>
                    <div className="builder-form-field" style={{ margin: 0 }}>
                      <label style={{ fontSize: 10 }}>End year</label>
                      <input type="text" value={sector.auction_share_trajectory.end_year ?? ""} onChange={(e) => {
                        const next = [...(workingScenario.sectors || [])];
                        next[si] = { ...next[si], auction_share_trajectory: { ...next[si].auction_share_trajectory, end_year: e.target.value } };
                        updateScenario({ sectors: next });
                      }} />
                    </div>
                    <div className="builder-form-field" style={{ margin: 0 }}>
                      <label style={{ fontSize: 10 }}>Start share</label>
                      <input type="number" step="0.05" min="0" max="1" value={sector.auction_share_trajectory.start_value ?? ""} onChange={(e) => {
                        const next = [...(workingScenario.sectors || [])];
                        next[si] = { ...next[si], auction_share_trajectory: { ...next[si].auction_share_trajectory, start_value: +e.target.value } };
                        updateScenario({ sectors: next });
                      }} />
                    </div>
                    <div className="builder-form-field" style={{ margin: 0 }}>
                      <label style={{ fontSize: 10 }}>End share</label>
                      <input type="number" step="0.05" min="0" max="1" value={sector.auction_share_trajectory.end_value ?? ""} onChange={(e) => {
                        const next = [...(workingScenario.sectors || [])];
                        next[si] = { ...next[si], auction_share_trajectory: { ...next[si].auction_share_trajectory, end_value: +e.target.value } };
                        updateScenario({ sectors: next });
                      }} />
                    </div>
                  </div>
                )}
              </div>
            </div>
          );
        })}
        {!(workingScenario.sectors || []).length && (
          <div className="builder-empty">No sectors defined. Add a sector to enable sector-level cap and allocation configuration.</div>
        )}
      </div>
    </div>
    </CollapsibleGroup>
  );
}

function SectorGroupField({ ctx }) {
  const { participant, selectedParticipantIndex, updateParticipant } = ctx;
  return (
    <label>
      <span className="ekey">Sector group <span className="field-flag optional">optional</span></span>
      <input
        type="text"
        className="text"
        placeholder="e.g. Steel, Petrochemical"
        value={participant.sector_group ?? ""}
        onChange={(e) => updateParticipant(selectedParticipantIndex, { sector_group: e.target.value })}
      />
      <span className="approach-params-hint">Groups this participant with others for sector-level aggregated output rows.</span>
    </label>
  );
}

// ── Guide: pe-shell module section (only rendered when this model uses
// sectors — see frontend/src/components/GuideView.jsx).

function SectorsGuideSection() {
  return (
    <div className="guide-body">
      <p className="guide-lead">
        <strong>Sectors</strong> group participants into shared caps and auction pools instead
        of one economy-wide market. Each sector has its own cap trajectory and auction-share
        trajectory; a participant joins a sector by setting its <strong>sector group</strong> to
        match the sector's name.
      </p>
      <p>
        When sectors are defined, the scenario's total cap and auction offer are derived from
        the sum of sector caps, and each participant's free allocation is computed from its
        <strong> sector allocation share</strong> of that sector's free-allocation pool —
        overriding the plain free allocation ratio.
      </p>
      <div className="guide-tip">
        <strong>Where to look:</strong> define sectors in the "Sectors" group on the Model tab
        (scenario step); assign a participant to one via its "Sector group" field on the
        Participants step.
      </div>
    </div>
  );
}

export default {
  id: "sectors",
  scenarioDefaults: {
    sectors: [],
  },
  participantDefaults: {
    sector_group: "",
    sector_allocation_share: 0,
  },
  editorSections: [SectorsEditorSection],
  participantEditorSections: [SectorGroupField],
  guideSections: [{ id: "module-sectors", tag: "SECT", title: "Sector pools", content: SectorsGuideSection }],
};
