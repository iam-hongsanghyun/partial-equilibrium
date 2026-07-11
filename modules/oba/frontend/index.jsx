// OBA (Output-Based Allocation / benchmark) feature — participant-level
// production output, benchmark emission intensity, output price elasticity
// (Option A price-elastic baseline input), and the free-allocation-ratio /
// sector-allocation-share field that OBA (and, when a matching sector is
// defined, the sectors feature) can override. Extracted verbatim from
// frontend/src/components/Editor.jsx (Allocation panel, participants step).

import { numInput, fieldWithPathButton } from "@core/components/EditorPrimitives.jsx";

function ObaAllocationFields({ ctx }) {
  const { workingScenario, workingYear, participant, selectedParticipantIndex, updateParticipant, openParticipantSeriesEditor } = ctx;
  const po = Number(participant.production_output ?? 0);
  const bei = Number(participant.benchmark_emission_intensity ?? 0);
  const obaActive = po > 0 && bei > 0;
  const definedSectors = workingScenario.sectors || [];
  const participantSectorGroup = participant.sector_group ?? "";
  const sectorMatch = definedSectors.find((s) => s.name === participantSectorGroup);

  let allocationField;
  if (sectorMatch) {
    // Sector mode: show sector_allocation_share with live preview
    const sas = Number(participant.sector_allocation_share ?? 0);
    const ie = Number(participant.initial_emissions ?? 0);
    const cap = sectorMatch.cap_trajectory;
    const capActive = !!(cap?.start_year && cap?.end_year && cap?.start_value !== undefined && cap?.end_value !== undefined);
    let previewMt = null;
    if (capActive && ie > 0) {
      const yearNum = Number(workingYear.year);
      const t0 = Number(cap.start_year), t1 = Number(cap.end_year);
      const v0 = Number(cap.start_value), v1 = Number(cap.end_value);
      let sectorCap;
      if (yearNum <= t0) sectorCap = v0;
      else if (yearNum >= t1) sectorCap = v1;
      else sectorCap = v0 + (v1 - v0) * (yearNum - t0) / (t1 - t0);
      const aucTraj = sectorMatch.auction_share_trajectory;
      const aucActive2 = !!(aucTraj?.start_year && aucTraj?.end_year && aucTraj?.start_value !== undefined && aucTraj?.end_value !== undefined);
      let aucShare = 0;
      if (aucActive2) {
        const at0 = Number(aucTraj.start_year), at1 = Number(aucTraj.end_year);
        const av0 = Number(aucTraj.start_value), av1 = Number(aucTraj.end_value);
        if (yearNum <= at0) aucShare = av0;
        else if (yearNum >= at1) aucShare = av1;
        else aucShare = av0 + (av1 - av0) * (yearNum - at0) / (at1 - at0);
      }
      const pool = sectorCap * (1 - aucShare);
      previewMt = Math.min(ie, pool * sas);
    }
    allocationField = (
      <label>
        <span className="ekey">Sector allocation share <span className="field-flag optional">optional</span></span>
        {numInput(sas, (value) => updateParticipant(selectedParticipantIndex, { sector_allocation_share: Math.min(1, Math.max(0, value)) }), 0.01, 0)}
        {previewMt !== null && (
          <span className="approach-params-hint">
            ≈ {previewMt.toFixed(1)} Mt free allocation in year {workingYear.year}
          </span>
        )}
        <span className="approach-params-hint">
          Share of the {sectorMatch.name} sector's free allocation pool (0–1). Replaces free_allocation_ratio.
        </span>
      </label>
    );
  } else if (obaActive) {
    allocationField = (
      <label style={{ opacity: 0.4 }}>
        <span className="ekey">Free allocation ratio <span className="field-flag optional">optional</span></span>
        {numInput(participant.free_allocation_ratio, (value) => updateParticipant(selectedParticipantIndex, { free_allocation_ratio: value }), 0.05, 0)}
        <span className="approach-params-hint">Overridden by OBA (production_output × benchmark_intensity).</span>
      </label>
    );
  } else {
    allocationField = (
      <label>
        <span className="ekey">{fieldWithPathButton("Free allocation ratio", () => openParticipantSeriesEditor("free_allocation_ratio"), true)}</span>
        {numInput(participant.free_allocation_ratio, (value) => updateParticipant(selectedParticipantIndex, { free_allocation_ratio: value }), 0.05, 0)}
      </label>
    );
  }

  return (
    <>
      <label>
        <span className="ekey">Production output (units/yr) <span className="field-flag optional">optional</span></span>
        {numInput(po, (v) => updateParticipant(selectedParticipantIndex, { production_output: Math.max(0, v) }), 0.1, 0)}
      </label>
      <label>
        <span className="ekey">Benchmark intensity (tCO₂/unit) <span className="field-flag optional">optional</span></span>
        {numInput(bei, (v) => updateParticipant(selectedParticipantIndex, { benchmark_emission_intensity: Math.max(0, v) }), 0.01, 0)}
        {obaActive && (
          <span className="approach-params-hint" style={{ fontWeight: 600, color: "#1f6f55" }}>
            OBA free allocation: {(bei * po).toFixed(1)} Mt
          </span>
        )}
        <span className="approach-params-hint">When both are &gt; 0, free allocation = intensity × output (overrides free_allocation_ratio).</span>
      </label>
      <label>
        <span className="ekey">Output price elasticity (Option A) <span className="field-flag optional">optional</span></span>
        {numInput(Number(participant.output_price_elasticity ?? 0), (v) => updateParticipant(selectedParticipantIndex, { output_price_elasticity: Math.max(0, v) }), 0.05, 0)}
        <span className="approach-params-hint">ε ≥ 0. Activity (and baseline emissions) contract as the carbon price rises above the scenario's reference carbon price. 0 = inelastic (default).</span>
      </label>
      {allocationField}
    </>
  );
}

// ── Guide: pe-shell module section (only rendered when this model uses
// OBA — see frontend/src/components/GuideView.jsx).

function ObaGuideSection() {
  return (
    <div className="guide-body">
      <p className="guide-lead">
        <strong>Output-Based Allocation (OBA)</strong> ties a participant's free allowances to
        how much it actually produces, rather than to a fixed ratio of its baseline emissions.
        Set both <strong>production output</strong> (units/yr) and a
        <strong> benchmark emission intensity</strong> (tCO₂/unit) and free allocation becomes
        their product — overriding the plain free allocation ratio.
      </p>
      <p>
        The same panel also carries the participant's <strong>output price elasticity</strong>
        (Option A price-elastic baseline): with a scenario reference carbon price set, activity
        and baseline emissions contract as the carbon price rises above that reference.
      </p>
      <div className="guide-tip">
        <strong>Where to look:</strong> production output and benchmark intensity are set per
        participant on the Participants step, alongside the free allocation ratio field they
        override.
      </div>
    </div>
  );
}

export default {
  id: "oba",
  participantDefaults: {
    production_output: 0,
    benchmark_emission_intensity: 0,
    output_price_elasticity: 0,
  },
  participantEditorSections: [ObaAllocationFields],
  guideSections: [{ id: "module-oba", tag: "OBA", title: "Output-based allocation", content: ObaGuideSection }],
};
