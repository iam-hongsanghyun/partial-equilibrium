// Endogenous investment feedback feature — the outer adoption loop
// (engine/feedback.py) that masks flagged technology options until their
// Dixit-Pindyck (or break-even) trigger price is crossed on the delivered
// price path, re-solving the full scenario path each outer iteration
// (docs/invest-feedback-plan.md, docs/invest-feedback-spec.md). Two doors:
// a scenario-level master gate + safety-rail/credibility overrides
// (editorSections), and a per-technology-option trigger sub-form
// (participantEditorSections, rendered at the technology editor — a
// non-empty investment_trigger sub-dict IS the flag, backend spec D6).

import { CollapsibleGroup, numInput } from "@core/components/EditorPrimitives.jsx";
import { orderedSummaryRows } from "@core/components/ResultPrimitives.jsx";

// ── Scenario-level: master gate, safety-rail iterations, credibility
// override, and a read-only view of any pre-committed (splice-carried)
// adoptions. Extends the msr-panel / msr-params-grid pattern (MSR, CCR) —
// enable toggle + conditional params grid — rather than inventing a new
// enable/params layout.

function InvestmentFeedbackEditorSection({ ctx }) {
  const { workingScenario, updateScenario } = ctx;
  const enabled = !!workingScenario.investment_feedback_enabled;
  const initialAdoptions = workingScenario.investment_initial_adoptions || [];
  return (
    <CollapsibleGroup title="Investment feedback" defaultOpen={false}>
    <div className="msr-panel">
      <div className="msr-panel-head">
        <div className="msr-panel-title-row">
          <span className="msr-panel-label">Investment feedback</span>
          <label className="msr-enabled-toggle">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(e) => updateScenario({ investment_feedback_enabled: e.target.checked })}
            />
            <span>Enable investment feedback</span>
          </label>
        </div>
        <p className="msr-panel-hint">
          Arms the outer adoption loop: any technology option flagged with an investment trigger
          (set per technology, on the Participants step) is masked out of the choice set until the
          delivered price path crosses its trigger price, at which point the loop re-solves with
          that option adopted. Requires the competitive or banking approach.
        </p>
      </div>
      {enabled && (
        <>
        <div className="msr-params-grid">
          <label className="msr-cancel-toggle-label">
            <span className="ekey">Max iterations override <span className="field-flag optional">optional</span></span>
            <span className="solver-settings-desc">Safety-rail cap on outer feedback iterations. Default: automatic (flagged pairs + 1).</span>
            <select
              value={workingScenario.investment_max_iterations != null ? "true" : "false"}
              onChange={(e) => updateScenario({ investment_max_iterations: e.target.value === "true" ? 5 : null })}
            >
              <option value="false">automatic</option>
              <option value="true">override</option>
            </select>
            {workingScenario.investment_max_iterations != null &&
              numInput(workingScenario.investment_max_iterations, (v) => updateScenario({ investment_max_iterations: Math.max(1, Math.round(v)) }), 1, 1)}
          </label>
          <label className="msr-cancel-toggle-label">
            <span className="ekey">Credibility override q <span className="field-flag optional">optional</span></span>
            <span className="solver-settings-desc">Overrides every flagged technology's own credibility for this scenario (0-1). Default: each technology's own credibility field applies.</span>
            <select
              value={workingScenario.invest_credibility != null ? "true" : "false"}
              onChange={(e) => updateScenario({ invest_credibility: e.target.value === "true" ? 0.5 : null })}
            >
              <option value="false">not set (per-technology)</option>
              <option value="true">override</option>
            </select>
            {workingScenario.invest_credibility != null &&
              numInput(workingScenario.invest_credibility, (v) => updateScenario({ invest_credibility: Math.min(1, Math.max(0, v)) }), 0.05, 0)}
          </label>
        </div>
        <div className="eua-prices-panel">
          <div className="eua-prices-head">
            <span className="eua-prices-label">Pre-committed adoptions <span className="field-flag optional">optional, read-only</span></span>
          </div>
          <span className="approach-params-hint">
            Carried automatically from an earlier policy-event segment's converged adoption state
            (a late announcement never un-adopts an earlier investment), or set directly in the
            underlying config to pre-commit an adoption before solving. Not editable from this
            panel in v1.
          </span>
          {initialAdoptions.length > 0 ? (
            <table className="pathway-table">
              <thead><tr><th>Participant</th><th>Technology</th><th>Decision year</th></tr></thead>
              <tbody>
                {initialAdoptions.map((item, index) => (
                  <tr key={`${item.participant}-${item.technology}-${index}`}>
                    <td>{item.participant}</td>
                    <td>{item.technology}</td>
                    <td>{item.adoption_year}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <p className="msr-panel-hint">No pre-committed adoptions for this scenario.</p>
          )}
        </div>
        </>
      )}
    </div>
    </CollapsibleGroup>
  );
}

// ── Technology-level: the investment_trigger sub-form (Dixit-Pindyck /
// break-even adoption rule, docs/invest-feedback-spec.md D6). Rendered at
// the technology editor (Editor.jsx's "Selected technology" section,
// alongside "Technology parameters" / "Technology abatement") because the
// trigger is a per-(participant, technology) config, not a participant-wide
// one — see registry.js's participantEditorSections slot; ctx carries the
// selected technology and its own updater, the same shape the technology
// parameter fields next to it already use.

function TechnologyInvestmentTriggerSection({ ctx }) {
  const { workingScenario, selectedParticipantIndex, technology, selectedTechnologyIndex, updateTechnologyOption } = ctx;
  if (!technology) return null;
  const trigger = technology.investment_trigger || {};
  const enabled = Object.keys(trigger).length > 0;

  const writeTrigger = (next) =>
    updateTechnologyOption(selectedParticipantIndex, selectedTechnologyIndex, { investment_trigger: next });
  const patchTrigger = (patch) => writeTrigger({ ...trigger, ...patch });
  const setEnabled = (next) => writeTrigger(next ? { break_even_price: 0, payout_yield: 0.03 } : {});

  const perYear = trigger.break_even_prices != null && typeof trigger.break_even_prices === "object";
  const setBreakEvenMode = (mode) => {
    if (mode === "per_year") {
      const { break_even_price, ...rest } = trigger;
      writeTrigger({ ...rest, break_even_prices: rest.break_even_prices || {} });
    } else {
      const { break_even_prices, ...rest } = trigger;
      writeTrigger({ ...rest, break_even_price: rest.break_even_price ?? 0 });
    }
  };
  const addBreakEvenYearRow = () => {
    const years = (workingScenario.years || []).map((y) => String(y.year));
    const existing = new Set(Object.keys(trigger.break_even_prices || {}));
    const nextLabel = years.find((y) => !existing.has(y)) || years[years.length - 1] || "2026";
    patchTrigger({ break_even_prices: { ...(trigger.break_even_prices || {}), [nextLabel]: 0 } });
  };

  const hasDiscountOverride = trigger.discount_rate !== undefined && trigger.discount_rate !== null;
  const hasMultipleOverride = trigger.trigger_multiple_override !== undefined && trigger.trigger_multiple_override !== null;

  return (
    <CollapsibleGroup title="Investment trigger" defaultOpen={enabled}>
    <div className="msr-panel">
      <div className="msr-panel-head">
        <div className="msr-panel-title-row">
          <span className="msr-panel-label">Investment trigger</span>
          <label className="msr-enabled-toggle">
            <input type="checkbox" checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
            <span>Flag this technology for endogenous adoption</span>
          </label>
        </div>
        <p className="msr-panel-hint">
          A non-empty trigger IS the flag: this technology option is masked out of the choice set
          until the delivered price crosses its trigger price P* = M · break-even, then adopted
          (subject to the build lag below). Requires "Investment feedback" enabled on the scenario.
        </p>
      </div>
      {enabled && (
        <>
        <div className="msr-params-grid">
          <label>
            <span className="ekey">Break-even price mode <span className="field-flag required">required</span></span>
            <select value={perYear ? "per_year" : "single"} onChange={(e) => setBreakEvenMode(e.target.value)}>
              <option value="single">Single value</option>
              <option value="per_year">Per year</option>
            </select>
          </label>
          {!perYear && (
            <label>
              <span className="ekey">Break-even price (currency/tCO2) <span className="field-flag required">required</span></span>
              {numInput(trigger.break_even_price ?? 0, (v) => patchTrigger({ break_even_price: v }), 1, 0)}
            </label>
          )}
          <label>
            <span className="ekey">Payout yield y (1/yr) <span className="field-flag required">required</span></span>
            <span className="solver-settings-desc">Payout/convenience yield of the completed project; r/y sets the certainty-limit hurdle.</span>
            {numInput(trigger.payout_yield ?? 0.03, (v) => patchTrigger({ payout_yield: Math.max(0, v) }), 0.005, 0)}
          </label>
          <label>
            <span className="ekey">Volatility sigma (1/sqrt(yr)) <span className="field-flag optional">optional</span></span>
            <span className="solver-settings-desc">Annualized volatility of the price the investor faces. Default: 0.</span>
            {numInput(trigger.sigma ?? 0, (v) => patchTrigger({ sigma: Math.max(0, v) }), 0.01, 0)}
          </label>
          <label>
            <span className="ekey">Credibility q <span className="field-flag optional">optional</span></span>
            <span className="solver-settings-desc">Probability the announced price schedule holds (0-1); effective volatility = (1-q) x sigma. Default: 0.</span>
            {numInput(trigger.credibility ?? 0, (v) => patchTrigger({ credibility: Math.min(1, Math.max(0, v)) }), 0.05, 0)}
          </label>
          <label>
            <span className="ekey">Trigger mode <span className="field-flag optional">optional</span></span>
            <select value={trigger.trigger_mode || "dixit_pindyck"} onChange={(e) => patchTrigger({ trigger_mode: e.target.value })}>
              <option value="dixit_pindyck">Dixit-Pindyck (option-value trigger)</option>
              <option value="break_even">Break-even (NPV activation, M = 1)</option>
            </select>
          </label>
          <label>
            <span className="ekey">Build lag (yr) <span className="field-flag optional">optional</span></span>
            <span className="solver-settings-desc">Years between the decision (state flips) and the capacity becoming available. Default: 0.</span>
            {numInput(trigger.build_lag_years ?? 0, (v) => patchTrigger({ build_lag_years: Math.max(0, Math.round(v)) }), 1, 0)}
          </label>
          <label className="msr-cancel-toggle-label">
            <span className="ekey">Discount rate override r (1/yr) <span className="field-flag optional">optional</span></span>
            <select
              value={hasDiscountOverride ? "true" : "false"}
              onChange={(e) => {
                if (e.target.value === "false") {
                  const { discount_rate, ...rest } = trigger;
                  writeTrigger(rest);
                } else {
                  patchTrigger({ discount_rate: workingScenario.discount_rate ?? 0.055 });
                }
              }}
            >
              <option value="false">inherit scenario default</option>
              <option value="true">override</option>
            </select>
            {hasDiscountOverride && numInput(trigger.discount_rate, (v) => patchTrigger({ discount_rate: Math.max(0, v) }), 0.005, 0)}
          </label>
          <label className="msr-cancel-toggle-label">
            <span className="ekey">Trigger multiple override M <span className="field-flag optional">optional</span></span>
            <select
              value={hasMultipleOverride ? "true" : "false"}
              onChange={(e) => {
                if (e.target.value === "false") {
                  const { trigger_multiple_override, ...rest } = trigger;
                  writeTrigger(rest);
                } else {
                  patchTrigger({ trigger_multiple_override: Math.max(1, Number(trigger.trigger_multiple_override) || 1) });
                }
              }}
            >
              <option value="false">computed (Dixit-Pindyck)</option>
              <option value="true">override</option>
            </select>
            {hasMultipleOverride && numInput(trigger.trigger_multiple_override, (v) => patchTrigger({ trigger_multiple_override: Math.max(1, v) }), 0.05, 1)}
          </label>
        </div>
        {perYear && (
          <div className="eua-prices-panel">
            <div className="eua-prices-head">
              <span className="eua-prices-label">Break-even price by year <span className="field-flag required">required</span></span>
              <button type="button" className="ghost-btn on" style={{ fontSize: 12 }} onClick={addBreakEvenYearRow}>+ Add</button>
            </div>
            <span className="approach-params-hint">Year label maps to an input-price-endogenous break-even threshold (currency/tCO2).</span>
            {Object.entries(trigger.break_even_prices || {}).map(([year, value]) => (
              <div key={year} className="eua-prices-row">
                <input
                  type="text"
                  className="text"
                  value={year}
                  style={{ width: 70 }}
                  onChange={(e) => {
                    const prices = { ...(trigger.break_even_prices || {}) };
                    delete prices[year];
                    prices[e.target.value] = value;
                    patchTrigger({ break_even_prices: prices });
                  }}
                />
                {numInput(value ?? 0, (v) => {
                  patchTrigger({ break_even_prices: { ...(trigger.break_even_prices || {}), [year]: v } });
                }, 1, 0)}
                <button
                  type="button"
                  className="ghost-btn"
                  style={{ fontSize: 11, padding: "2px 6px" }}
                  onClick={() => {
                    const prices = { ...(trigger.break_even_prices || {}) };
                    delete prices[year];
                    patchTrigger({ break_even_prices: prices });
                  }}
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}
        </>
      )}
    </div>
    </CollapsibleGroup>
  );
}

// ── Result-side: adoption timeline panel ─────────────────────────────────
// Reads the four tail summary columns the backend stamps under a
// key-presence guard (core/ledger.py collect_path_results): "Investment
// Adoptions" (JSON array of {participant, technology, adoption_year}
// EFFECTIVE THROUGH that row's year — i.e. decided at or before it),
// "Investment Newly Effective" (count whose CAPACITY arrives that year),
// "Investment Feedback Iterations" and "Investment Converged" (constant
// across a scenario's years). Self-hides per scenario section (matching
// MsrReservePanel/CcrPanel) when the column is absent or every year's
// adoption list is empty.

function parseAdoptionEvents(raw) {
  if (!raw) return [];
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  if (!Array.isArray(parsed)) return [];
  return parsed.filter(
    (event) => event && typeof event === "object" && event.participant && event.technology && event.adoption_year
  );
}

// Infers each event's effective (capacity-available) year from the
// "Investment Newly Effective" per-year counts, without re-deriving the
// build-lag economics client-side: walk the scenario's years in order,
// accumulate events whose recorded decision year has been reached, and
// when the newly-effective count for a year exactly accounts for every
// still-pending event, that year IS their effective year. Left ambiguous
// (ties the count can't disambiguate) or unreached, an event's effective
// year stays null and the timeline row falls back to its decision year.
function inferAdoptionTimeline(scenario, rows) {
  const years = (scenario.years || []).map((year) => String(year.year));
  const adoptionsByYear = rows.map((row) => parseAdoptionEvents(row["Investment Adoptions"]));
  const newlyEffectiveByYear = rows.map((row) => Math.round(Number(row["Investment Newly Effective"] || 0)));

  const finalEvents = adoptionsByYear[adoptionsByYear.length - 1] || [];
  const timeline = finalEvents.map((event) => ({
    participant: event.participant,
    technology: event.technology,
    decisionYear: event.adoption_year,
    effectiveYear: null,
  }));

  let pending = [];
  years.forEach((year, index) => {
    pending.push(...timeline.filter((item) => item.decisionYear === year));
    const newlyEffective = newlyEffectiveByYear[index] || 0;
    if (newlyEffective > 0 && pending.length > 0) {
      if (newlyEffective === pending.length) {
        pending.forEach((item) => { item.effectiveYear = year; });
      }
      pending = [];
    }
  });

  return timeline.sort((a, b) =>
    a.participant === b.participant ? a.technology.localeCompare(b.technology) : a.participant.localeCompare(b.participant)
  );
}

function AdoptionTimelinePanel({ ctx }) {
  const { scenario, summary } = ctx;
  const rows = orderedSummaryRows(scenario, summary);
  const hasColumn = rows.some((row) => row["Investment Adoptions"] !== undefined);
  if (!hasColumn) return null;
  const timeline = inferAdoptionTimeline(scenario, rows);
  if (!timeline.length) return null;

  const diagnosticsRow = rows.find((row) => row["Investment Feedback Iterations"] !== undefined) || {};
  const iterations = Math.round(Number(diagnosticsRow["Investment Feedback Iterations"] || 0));
  const converged = Number(diagnosticsRow["Investment Converged"] || 0) === 1;

  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <div className="eyebrow">Endogenous investment</div>
          <h2>Adoption timeline</h2>
          <p className="muted">
            Technology adoptions triggered by the endogenous-investment feedback loop for {scenario.name}.
          </p>
        </div>
      </div>
      <div className="pathway-table-wrap">
        <table className="pathway-table">
          <thead>
            <tr><th>Participant</th><th>Technology</th><th>Decision year</th><th>Effective year</th></tr>
          </thead>
          <tbody>
            {timeline.map((item) => (
              <tr key={`${item.participant}-${item.technology}`}>
                <td>{item.participant}</td>
                <td>{item.technology}</td>
                <td>{item.decisionYear}</td>
                <td>{item.effectiveYear ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="muted">
        Feedback iterations: {iterations} · {converged ? "converged" : "did not converge (safety rail reached)"}.
      </p>
    </section>
  );
}

// ── Validators ────────────────────────────────────────────────────────────

function validateInvestmentFeedback(scenario) {
  const issues = [];
  const target = { section: "build", step: "scenario" };
  const credibility = scenario?.invest_credibility;
  if (credibility !== undefined && credibility !== null) {
    const value = Number(credibility);
    if (!Number.isFinite(value) || value < 0 || value > 1) {
      issues.push({
        level: "error",
        scope: "Investment feedback",
        message: "Scenario-wide credibility override must be between 0 and 1.",
        target,
      });
    }
  }
  const maxIterations = scenario?.investment_max_iterations;
  if (maxIterations !== undefined && maxIterations !== null) {
    const value = Number(maxIterations);
    if (!Number.isFinite(value) || !Number.isInteger(value) || value < 1) {
      issues.push({
        level: "error",
        scope: "Investment feedback",
        message: "Investment max iterations must be a positive integer when set.",
        target,
      });
    }
  }
  return issues;
}

// ── Guide: pe-shell module section (only rendered when this model uses
// endogenous investment — see frontend/src/components/GuideView.jsx).

function InvestmentFeedbackGuideSection() {
  return (
    <div className="guide-body">
      <p className="guide-lead">
        <strong>Endogenous investment feedback</strong> turns an irreversible technology adoption
        into a solved equilibrium result instead of an exogenous assumption: any technology option
        flagged with an <strong>investment trigger</strong> stays masked out of the choice set until
        the market's own delivered price path crosses that option's trigger price, at which point
        the model re-solves with the option adopted — repeating until the adoption set stops
        changing (at most one new adoption per iteration).
      </p>
      <p>
        The trigger rule is the Dixit-Pindyck option-value hurdle: adoption happens once the price
        reaches P* = M · break-even, where the multiple M grows with the price volatility the
        investor faces and shrinks toward the pure timing wedge r/y as volatility falls to zero. A
        build lag can separate the decision year (when the state flips) from the year the new
        capacity actually becomes available.
      </p>
      <p>
        The <strong>credibility</strong> lever (0-1, per technology or overridden scenario-wide)
        models how much of that volatility an announced, credible price floor or decree removes
        before the investor decides: effective volatility = (1 − q) × sigma, so a fully
        credible signal (q = 1) collapses the hurdle to its certainty limit.
      </p>
      <div className="guide-tip">
        <strong>Where to look:</strong> enable the master gate and any overrides in the "Investment
        feedback" group on the Model tab; flag individual technologies in the "Investment trigger"
        group on the Participants step; the adoption timeline and convergence status appear as
        their own panel on the Analysis tab once an adoption actually occurs.
      </div>
    </div>
  );
}

export default {
  id: "endogenous_investment",
  scenarioDefaults: {
    investment_feedback_enabled: false,
    investment_max_iterations: null,
    investment_initial_adoptions: [],
    invest_credibility: null,
  },
  editorSections: [InvestmentFeedbackEditorSection],
  participantEditorSections: [TechnologyInvestmentTriggerSection],
  summaryPanels: [AdoptionTimelinePanel],
  validators: [validateInvestmentFeedback],
  guideSections: [{
    id: "module-endogenous-investment",
    tag: "INV",
    title: "Endogenous investment feedback",
    content: InvestmentFeedbackGuideSection,
  }],
};
