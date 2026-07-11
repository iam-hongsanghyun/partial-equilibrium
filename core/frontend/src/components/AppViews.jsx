import { useEffect, useMemo, useState } from "react";
import { fmt, SECTOR_COLORS, MarketChart } from "./MarketChart.jsx";
import { TrajectoryChart } from "./TrajectoryChart.jsx";
import { ParticipantPanel } from "./ParticipantPanel.jsx";
import { ParticipantMacChart } from "./ParticipantMacChart.jsx";
import { AnnualMarketChart } from "./AnnualMarketChart.jsx";
import { AnnualEmissionsChart } from "./AnnualEmissionsChart.jsx";
import { MarketYearGallery } from "./MarketYearGallery.jsx";
import { Editor } from "./Editor.jsx";
import {
  KPI,
  ValidationPanel,
  AuctionDiagnosticsPanel,
  AuctionPathwayPanel,
  ScenarioHero,
  clampSeriesValue,
  generateSeriesPath,
  SeriesTrajectoryEditor,
  MiniMarket,
  buildTechnologyPathway,
  describeUnsoldTreatment,
  getSeriesFieldMeta,
  visibleYearAttributeFields,
  TooltipButton,
} from "./AppShared.jsx";
import { activeFeatureIds, collectSlot, FEATURES } from "../registry.js";

// The full year-attribute candidate list for the "Market timeline" metric
// picker. Unscoped (default) shell: shown in full, unchanged, in this exact
// order. Pe mode: filtered through visibleYearAttributeFields (feature tag
// + config-driven "did this model's config actually set it" — see
// AppShared.jsx) unless "Show advanced settings" is on.
const YEAR_SERIES_FIELDS = [
  "total_cap",
  "auction_offered",
  "carbon_budget",
  "reserved_allowances",
  "cancelled_allowances",
  "auction_reserve_price",
  "minimum_bid_coverage",
  "price_lower_bound",
  "price_upper_bound",
  "borrowing_limit",
  "manual_expected_price",
  "eua_price",
];

function BuildView({
  scenario, yearObj, activeYear, onYearChange, addYear, removeYear,
  onRunBase, onRunEdited, onRunAll, hasEditedChanges, onSave, onUpdateYearSeries, navigationTarget,
  enabledFeatures = null, manifest = null,
}) {
  const peMode = enabledFeatures != null;
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [selectedSeriesField, setSelectedSeriesField] = useState("total_cap");
  const [generatorRule, setGeneratorRule] = useState("linear");
  const [generatorStart, setGeneratorStart] = useState(0);
  const [generatorEnd, setGeneratorEnd] = useState(0);
  const [holdUntilYear, setHoldUntilYear] = useState("");
  const [percentRate, setPercentRate] = useState(5);
  const [applyStartYear, setApplyStartYear] = useState("");
  const [applyEndYear, setApplyEndYear] = useState("");
  const seriesFields = useMemo(
    () =>
      peMode
        ? visibleYearAttributeFields(YEAR_SERIES_FIELDS, { enabledFeatures, years: scenario.years, showAdvanced })
        : YEAR_SERIES_FIELDS,
    [peMode, enabledFeatures, scenario.years, showAdvanced]
  );
  const selectedMeta = getSeriesFieldMeta(selectedSeriesField);
  const orderedYears = useMemo(() => (scenario.years || []).map((year) => String(year.year)), [scenario.years]);
  const seriesDraft = useMemo(
    () => {
      const scale = selectedMeta.displayScale || 1;
      return Object.fromEntries(
        (scenario.years || []).map((year) => [String(year.year), Number(year[selectedSeriesField] ?? 0) * scale])
      );
    },
    [scenario.years, selectedSeriesField]
  );
  useEffect(() => {
    if (seriesFields.length && !seriesFields.includes(selectedSeriesField)) {
      setSelectedSeriesField(seriesFields[0]);
    }
  }, [seriesFields, selectedSeriesField]);
  useEffect(() => {
    const scale = getSeriesFieldMeta(selectedSeriesField).displayScale || 1;
    const firstYear = scenario.years?.[0];
    const lastYear = scenario.years?.[Math.max(0, (scenario.years?.length || 1) - 1)];
    const midYear = scenario.years?.[Math.max(0, Math.floor(((scenario.years?.length || 1) - 1) / 2))];
    setGeneratorStart(Number(firstYear?.[selectedSeriesField] ?? 0) * scale);
    setGeneratorEnd(Number(lastYear?.[selectedSeriesField] ?? 0) * scale);
    setHoldUntilYear(String(midYear?.year ?? ""));
    setApplyStartYear(String(firstYear?.year ?? ""));
    setApplyEndYear(String(lastYear?.year ?? ""));
  }, [scenario.years, selectedSeriesField]);
  const updateSelectedSeries = (updater) => {
    const scale = selectedMeta.displayScale || 1;
    const current = Object.fromEntries(
      (scenario.years || []).map((year) => [String(year.year), Number(year[selectedSeriesField] ?? 0) * scale])
    );
    const next = typeof updater === "function" ? updater(current) : updater;
    const rawNext = scale !== 1
      ? Object.fromEntries(Object.entries(next).map(([y, v]) => [y, v / scale]))
      : next;
    onUpdateYearSeries(selectedSeriesField, rawNext);
  };
  return (
    <div className="wb">
      <ScenarioHero
        scenario={scenario}
        activeYear={activeYear}
        onYearChange={onYearChange}
        results={{}}
        showYearStrip={false}
        primaryMetric={(
          <div className="panel hero-panel">
            <div className="panel-head">
              <div>
                <div className="eyebrow">Model</div>
                <h2>Scenario builder</h2>
              </div>
            </div>
            <div className="hero-actions">
              <button className="ghost-btn ghost-btn-muted" onClick={onRunBase}>Run loaded scenario</button>
              <button className={"ghost-btn ghost-btn-muted " + (hasEditedChanges ? "edited-btn" : "")} onClick={onRunEdited}>Run edited</button>
              <button className="ghost-btn ghost-btn-muted" onClick={onRunAll}>Run all scenarios</button>
            </div>
          </div>
        )}
      />
      <section className="panel">
        <div className="panel-head">
          <div>
            <div className="eyebrow">Market timeline</div>
            <h2>Review values across years</h2>
            <p className="muted">Select a market attribute on the left, then edit it directly on the chart. The pathway setup controls are embedded on the right so you can generate and refine without opening a popup.</p>
          </div>
          {peMode && (
            <div className="toggles">
              <button
                type="button"
                className={"toggle " + (showAdvanced ? "on" : "")}
                onClick={() => setShowAdvanced((value) => !value)}
              >
                {showAdvanced ? "Hide advanced settings" : "Show advanced settings"}
              </button>
            </div>
          )}
        </div>
        {!seriesFields.length ? (
          <div className="builder-empty">
            This model has not configured any market attributes beyond their defaults yet.
            Turn on "Show advanced settings" to reveal the full attribute list and start editing.
          </div>
        ) : (
        <div className="timeline-workbench">
          <div className="timeline-field-list">
            {seriesFields.map((field) => {
              const meta = getSeriesFieldMeta(field);
              return (
                <TooltipButton
                  key={field}
                  className={"timeline-field-item " + (selectedSeriesField === field ? "on" : "")}
                  onClick={() => setSelectedSeriesField(field)}
                  tooltip={meta.description}
                >
                  <span>{meta.label}</span>
                </TooltipButton>
              );
            })}
          </div>
          <div className="timeline-chart-panel">
            <div className="timeline-editor-head">
              <div>
                <div className="eyebrow">Selected metric</div>
                <h3>{selectedMeta.label}</h3>
              </div>
            </div>
            <SeriesTrajectoryEditor
              years={scenario.years}
              draft={seriesDraft}
              setDraft={updateSelectedSeries}
              meta={selectedMeta}
            />
          </div>
          <div className="timeline-side-panel">
            <div className="series-generator timeline-generator-inline">
              <div className="timeline-gen-header">
                <h3>Pathway Setting</h3>
                <div className="series-generator-actions">
                  <button
                    className="ghost-btn ghost-btn-muted"
                    onClick={() =>
                      updateSelectedSeries((current) =>
                        generateSeriesPath({
                          years: scenario.years,
                          draft: current,
                          meta: selectedMeta,
                          rule: generatorRule,
                          startValue: generatorStart,
                          endValue: generatorEnd,
                          holdUntilYear,
                          percentRate,
                          applyStartYear,
                          applyEndYear,
                        })
                      )
                    }
                  >
                    Apply pathway
                  </button>
                  <button
                    className="ghost-btn ghost-btn-muted"
                    onClick={() =>
                      updateSelectedSeries((current) => {
                        const next = { ...current };
                        const startIndex = orderedYears.indexOf(String(applyStartYear));
                        const endIndex = orderedYears.indexOf(String(applyEndYear));
                        const rangeStart = Math.min(startIndex >= 0 ? startIndex : 0, endIndex >= 0 ? endIndex : orderedYears.length - 1);
                        const rangeEnd = Math.max(startIndex >= 0 ? startIndex : 0, endIndex >= 0 ? endIndex : orderedYears.length - 1);
                        const flatValue = clampSeriesValue(generatorStart, selectedMeta);
                        orderedYears.forEach((year, index) => {
                          if (index >= rangeStart && index <= rangeEnd) next[year] = flatValue;
                        });
                        return next;
                      })
                    }
                  >
                    Fill selected range
                  </button>
                </div>
              </div>
              <div className="series-generator-grid series-generator-grid-stack">
                <label className="series-generator-select">
                  <span className="review-label">Method</span>
                  <select value={generatorRule} onChange={(event) => setGeneratorRule(event.target.value)}>
                    <option value="linear">Linear</option>
                    <option value="step">Step</option>
                    <option value="percent_decline">% decline</option>
                    <option value="hold_then_drop">Hold then drop</option>
                    <option value="s_curve">S-curve</option>
                  </select>
                </label>
                <label>
                  <span>From</span>
                  <select value={applyStartYear} onChange={(event) => setApplyStartYear(event.target.value)}>
                    {orderedYears.map((year) => <option key={`build-start-${year}`} value={year}>{year}</option>)}
                  </select>
                </label>
                <label>
                  <span>To</span>
                  <select value={applyEndYear} onChange={(event) => setApplyEndYear(event.target.value)}>
                    {orderedYears.map((year) => <option key={`build-end-${year}`} value={year}>{year}</option>)}
                  </select>
                </label>
                <label>
                  <span>Start</span>
                  <input type="number" step={selectedMeta.step} min={selectedMeta.min} max={selectedMeta.max} value={generatorStart} onChange={(event) => setGeneratorStart(Number(event.target.value))} />
                </label>
                <label>
                  <span>End</span>
                  <input type="number" step={selectedMeta.step} min={selectedMeta.min} max={selectedMeta.max} value={generatorEnd} onChange={(event) => setGeneratorEnd(Number(event.target.value))} />
                </label>
                {generatorRule === "hold_then_drop" && (
                  <label>
                    <span>Hold until</span>
                    <select value={holdUntilYear} onChange={(event) => setHoldUntilYear(event.target.value)}>
                      {orderedYears.map((year) => <option key={`build-hold-${year}`} value={year}>{year}</option>)}
                    </select>
                  </label>
                )}
                {generatorRule === "percent_decline" && (
                  <label>
                    <span>% per step</span>
                    <input type="number" step="0.1" min="0" max="100" value={percentRate} onChange={(event) => setPercentRate(Number(event.target.value))} />
                  </label>
                )}
              </div>
            </div>
          </div>
        </div>
        )}
      </section>
      <section className="panel">
        <div className="panel-head">
          <div>
            <div className="eyebrow">Build</div>
            <h2>Edit scenario inputs</h2>
            <p className="muted">Build from scratch, use templates, and edit year, participant, MAC, and technology assumptions.</p>
          </div>
        </div>
        <Editor
          scenario={scenario}
          year={yearObj}
          onSave={onSave}
          onAddYear={addYear}
          onRemoveYear={removeYear}
          onSelectYear={onYearChange}
          navigationTarget={navigationTarget}
          enabledFeatures={enabledFeatures}
          showAdvanced={showAdvanced}
          manifest={manifest}
        />
      </section>
    </div>
  );
}

function ModelView({
  scenario, yearObj, activeYear, onYearChange, selPart, setSelPart, onRunBase, onRunEdited, onRunAll, hasEditedChanges,
}) {
  const selectedIndex = selPart == null ? 0 : selPart;
  const selectedParticipant = yearObj.participants?.[selectedIndex] || null;
  const freeAllocation = (yearObj.participants || []).reduce(
    (sum, participant) => sum + Number(participant.initial_emissions || 0) * Number(participant.free_allocation_ratio || 0),
    0
  );
  const unallocatedAllowances = Math.max(
    0,
    Number(yearObj.total_cap || 0)
      - freeAllocation
      - Number(yearObj.auction_offered || 0)
      - Number(yearObj.reserved_allowances || 0)
      - Number(yearObj.cancelled_allowances || 0)
  );
  return (
    <div className="wb">
      <ScenarioHero
        scenario={scenario}
        activeYear={activeYear}
        onYearChange={onYearChange}
        results={{}}
        primaryMetric={(
          <div className="panel hero-panel">
            <div className="panel-head">
              <div>
                <div className="eyebrow">Model</div>
                <h2>Review built model</h2>
                <p className="muted">Inspect the scenario structure before running: market rules, participants, MACs, and technology pathways.</p>
              </div>
            </div>
            <div className="hero-actions">
              <button className="ghost-btn ghost-btn-muted" onClick={onRunBase}>Run loaded scenario</button>
              <button className={"ghost-btn ghost-btn-muted " + (hasEditedChanges ? "edited-btn" : "")} onClick={onRunEdited}>Run edited</button>
              <button className="ghost-btn ghost-btn-muted" onClick={onRunAll}>Run all scenarios</button>
            </div>
          </div>
        )}
      />
      <section className="wb-grid">
        <div className="panel">
          <div className="panel-head">
            <div><div className="eyebrow">Market</div><h2>Year {yearObj.year} market definition</h2></div>
          </div>
          <div className="review-grid">
            <div className="review-item"><span className="review-label">Auction mode</span><strong>{yearObj.auction_mode}</strong></div>
            <div className="review-item"><span className="review-label">Total cap</span><strong>{fmt.num(yearObj.total_cap || 0, 0)}</strong></div>
            <div className="review-item"><span className="review-label">Auction offered</span><strong>{fmt.num(yearObj.auction_offered || 0, 0)}</strong></div>
            <div className="review-item"><span className="review-label">Reserved allowances</span><strong>{fmt.num(yearObj.reserved_allowances || 0, 0)}</strong></div>
            <div className="review-item"><span className="review-label">Cancelled allowances</span><strong>{fmt.num(yearObj.cancelled_allowances || 0, 0)}</strong></div>
            <div className="review-item"><span className="review-label">Unallocated allowances</span><strong>{fmt.num(unallocatedAllowances, 0)}</strong></div>
            <div className="review-item"><span className="review-label">Auction reserve price</span><strong>{fmt.num(yearObj.auction_reserve_price || 0, 0)}</strong></div>
            <div className="review-item"><span className="review-label">Minimum bid coverage</span><strong>{fmt.num(yearObj.minimum_bid_coverage || 0, 2)}</strong></div>
            <div className="review-item"><span className="review-label">Unsold treatment</span><strong>{yearObj.unsold_treatment || "reserve"}</strong></div>
            <div className="review-item"><span className="review-label">Price bounds</span><strong>{fmt.num(yearObj.price_lower_bound || 0, 0)} to {fmt.num(yearObj.price_upper_bound || 0, 0)}</strong></div>
            <div className="review-item"><span className="review-label">Banking</span><strong>{yearObj.banking_allowed ? "enabled" : "disabled"}</strong></div>
            <div className="review-item"><span className="review-label">Borrowing</span><strong>{yearObj.borrowing_allowed ? `enabled (${fmt.num(yearObj.borrowing_limit || 0, 0)})` : "disabled"}</strong></div>
            <div className="review-item"><span className="review-label">Expectation rule</span><strong>{yearObj.expectation_rule || "next_year_baseline"}</strong></div>
            <div className="review-item"><span className="review-label">Manual expected price</span><strong>{fmt.price(yearObj.manual_expected_price || 0)}</strong></div>
          </div>
        </div>
        <div className="panel">
          <div className="panel-head"><div><div className="eyebrow">Participants</div><h2>Configured participants</h2></div></div>
          <div className="pathway-table-wrap">
            <table className="pathway-table">
              <thead><tr><th>Participant</th><th>Sector</th><th>Emissions</th><th>Abatement</th><th>Technology options</th></tr></thead>
              <tbody>
                {(yearObj.participants || []).map((participant, index) => (
                  <tr key={`${participant.name}-${index}`} onClick={() => setSelPart(index)}>
                    <td>{participant.name}</td><td>{participant.sector || "Other"}</td><td>{fmt.num(participant.initial_emissions || 0, 0)}</td><td>{participant.abatement_type}</td><td>{(participant.technology_options || []).length || 0}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>
      <section className="wb-grid">
        <div className="panel">
          <div className="panel-head">
            <div>
              <div className="eyebrow">Auction design</div>
              <h2>How this year’s auction is configured</h2>
              <p className="muted">These settings control whether offered allowances are fully sold and what happens to unsold volume.</p>
            </div>
          </div>
          <div className="review-grid auction-review-grid">
            <div className="review-item"><span className="review-label">Auction offered</span><strong>{fmt.num(yearObj.auction_offered || 0, 0)}</strong></div>
            <div className="review-item"><span className="review-label">Reserve price</span><strong>{fmt.price(yearObj.auction_reserve_price || 0)}</strong></div>
            <div className="review-item"><span className="review-label">Minimum bid coverage</span><strong>{fmt.num((yearObj.minimum_bid_coverage || 0) * 100, 0)}%</strong></div>
            <div className="review-item"><span className="review-label">Reserved allowances</span><strong>{fmt.num(yearObj.reserved_allowances || 0, 0)}</strong></div>
            <div className="review-item"><span className="review-label">Cancelled allowances</span><strong>{fmt.num(yearObj.cancelled_allowances || 0, 0)}</strong></div>
            <div className="review-item review-item-wide"><span className="review-label">Unsold treatment</span><strong>{describeUnsoldTreatment(yearObj.unsold_treatment || "reserve")}</strong></div>
            <div className="review-item review-item-wide"><span className="review-label">Mechanism</span><strong>Offered auction volume only becomes market supply if it clears the reserve-price and bid-coverage rules for the year.</strong></div>
            <div className="review-item"><span className="review-label">Expectation rule</span><strong>{yearObj.expectation_rule || "next_year_baseline"}</strong></div>
            <div className="review-item"><span className="review-label">Manual expected price</span><strong>{fmt.price(yearObj.manual_expected_price || 0)}</strong></div>
          </div>
        </div>
        <AuctionPathwayPanel scenario={scenario} results={{}} />
      </section>
      <section className="wb-grid">
        <div className="panel">
          <div className="panel-head">
            <div><div className="eyebrow">MAC</div><h2>Selected participant MAC</h2></div>
            <div className="panel-controls">
              <select value={selectedIndex} onChange={(event) => setSelPart(Number(event.target.value))}>
                {(yearObj.participants || []).map((participant, index) => (
                  <option key={`${participant.name}-${index}`} value={index}>{participant.name}</option>
                ))}
              </select>
            </div>
          </div>
          <ParticipantMacChart participant={selectedParticipant} outcome={null} carbonPrice={null} />
        </div>
        <div className="panel">
          <div className="panel-head"><div><div className="eyebrow">Technology</div><h2>Technology pathway setup</h2></div></div>
          <div className="pathway-table-wrap">
            <table className="pathway-table">
              <thead><tr><th>Technology</th><th>Emissions</th><th>Free ratio</th><th>Fixed cost</th></tr></thead>
              <tbody>
                {((selectedParticipant?.technology_options || []).length ? selectedParticipant.technology_options : [{
                  name: "Base Technology",
                  initial_emissions: selectedParticipant?.initial_emissions || 0,
                  free_allocation_ratio: selectedParticipant?.free_allocation_ratio || 0,
                  fixed_cost: 0,
                }]).map((option, index) => (
                  <tr key={`${option.name}-${index}`}>
                    <td>{option.name}</td><td>{fmt.num(option.initial_emissions || 0, 1)}</td><td>{fmt.num(option.free_allocation_ratio || 0, 2)}</td><td>{fmt.num(option.fixed_cost || 0, 0)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </section>
    </div>
  );
}

function ValidationView({ scenario, activeYear, onYearChange, validationIssues, onNavigateIssue }) {
  const issueCounts = validationIssues.reduce(
    (acc, issue) => {
      acc[issue.level] = (acc[issue.level] || 0) + 1;
      return acc;
    },
    { error: 0, warning: 0, note: 0 }
  );
  return (
    <div className="wb">
      <ScenarioHero
        scenario={scenario}
        activeYear={activeYear}
        onYearChange={onYearChange}
        results={{}}
        primaryMetric={(
          <div className="panel hero-panel">
            <div className="panel-head">
              <div>
                <div className="eyebrow">Validation</div>
                <h2>Review scenario checks</h2>
                <p className="muted">Use this section to inspect structural issues before running or interpreting the model.</p>
              </div>
            </div>
            <div className="review-grid">
              <div className="review-item"><span className="review-label">Errors</span><strong>{issueCounts.error || 0}</strong></div>
              <div className="review-item"><span className="review-label">Warnings</span><strong>{issueCounts.warning || 0}</strong></div>
              <div className="review-item"><span className="review-label">Notes</span><strong>{issueCounts.note || 0}</strong></div>
              <div className="review-item"><span className="review-label">Scenario years</span><strong>{(scenario?.years || []).length}</strong></div>
            </div>
          </div>
        )}
      />
      <ValidationPanel issues={validationIssues} title="Scenario validation" onNavigateIssue={onNavigateIssue} />
    </div>
  );
}

function AnalysisView({
  scenario, yearObj, activeYear, onYearChange, result, results, scenarios, stacked,
  onToggleStacked, dragSupply, selPart, setSelPart, analysis,
  summary = [], enabledFeatures = null,
}) {
  const activeFeatures = activeFeatureIds(enabledFeatures);
  const isFeatureActive = (id) => activeFeatures.includes(id);
  const yearKeys = scenario.years.map((year) => String(year.year));
  const resByYear = results[scenario.name] || {};
  const idx = yearKeys.indexOf(String(activeYear));
  const prevYear = idx > 0 ? yearKeys[idx - 1] : null;
  const prevResult = prevYear ? resByYear[prevYear] : null;
  const delta = (current, previous) => previous == null ? null : current - previous;
  const selectedIndex = selPart == null ? 0 : selPart;
  const selectedParticipant = yearObj.participants?.[selectedIndex] || null;
  const selectedOutcome = result.perParticipant?.[selectedIndex] || null;
  const technologyPathway = buildTechnologyPathway(scenario, results);
  return (
    <div className="wb">
      <ScenarioHero
        scenario={scenario}
        activeYear={activeYear}
        onYearChange={onYearChange}
        results={results}
        primaryMetric={(
          <div className="kpis">
            <KPI label="Equilibrium price" value={fmt.price(result.price)} sub={prevResult ? `${delta(result.price, prevResult.price) >= 0 ? "▲" : "▼"} ${fmt.num(Math.abs(delta(result.price, prevResult.price)), 2)} vs ${prevYear}` : "base year"} tone="primary" />
            <KPI label="Auction revenue" value={fmt.money(result.revenue)} sub={`${fmt.int(result.Q)} allowances × ${fmt.price(result.price)}`}/>
            <KPI label="Abatement" value={`${fmt.num(result.totalAbate, 0)} Mt`} sub={prevResult ? `${delta(result.totalAbate, prevResult.totalAbate) >= 0 ? "▲" : "▼"} ${fmt.num(Math.abs(delta(result.totalAbate, prevResult.totalAbate)), 1)} Mt` : "—"}/>
            <KPI label="Allowances traded" value={fmt.num(result.totalTraded, 0)} sub="between buyers & sellers"/>
          </div>
        )}
      />
      <section className="wb-grid">
        <div className="panel panel-chart">
          <div className="panel-head">
            <div>
              <div className="eyebrow">Figure 1</div>
              <h2>Market clearing · {yearObj.year}</h2>
              <p className="muted">Where aggregate net participant demand meets auction supply entering the market. Drag the supply line to edit offered volume, then rerun the model.</p>
            </div>
            <div className="toggles">
              <button className={"toggle " + (stacked ? "on" : "")} onClick={onToggleStacked}>Stack by participant</button>
            </div>
          </div>
          <MarketChart year={yearObj} result={result} stacked={stacked} onDragSupply={dragSupply} sectorColors={SECTOR_COLORS} />
        </div>
        <div className="panel panel-trajectory">
          <div className="panel-head">
            <div><div className="eyebrow">Figure 2</div><h2>Price trajectory across scenarios</h2><p className="muted">How this scenario compares against the others over time.</p></div>
          </div>
          <TrajectoryChart scenarios={scenarios} results={results} highlightScenario={scenario.name} />
        </div>
      </section>
      <section className="wb-grid">
        <AuctionDiagnosticsPanel yearObj={yearObj} result={result} />
        <div className="panel">
          <div className="panel-head">
            <div><div className="eyebrow">Auction rules</div><h2>What determined the auction outcome</h2><p className="muted">The current year’s auction mechanics and any policy frictions affecting supply available to the allowance market.</p></div>
          </div>
          <ul className="analysis-list">
            {/* price_controls.analysisBullets[0..2] = reserve price, minimum
                bid coverage, unsold treatment (rendered at their original
                position, before the core "Reserved allowances" bullet). */}
            {isFeatureActive("price_controls") &&
              [0, 1, 2].map((index) => {
                const Bullet = FEATURES.price_controls.analysisBullets?.[index];
                return Bullet ? <Bullet key={`price-controls-bullet-${index}`} ctx={{ yearObj }} /> : null;
              })}
            <li>Reserved allowances: {fmt.num(yearObj.reserved_allowances || 0, 0)} are held out of circulation before market clearing.</li>
            {/* price_controls.analysisBullets[3] = cancelled allowances. */}
            {isFeatureActive("price_controls") && (() => {
              const CancelledBullet = FEATURES.price_controls.analysisBullets?.[3];
              return CancelledBullet ? <CancelledBullet ctx={{ yearObj }} /> : null;
            })()}
            <li>Expectation rule: {result.expectationRule === "manual" ? `manual future price of ${fmt.price(result.manualExpectedPrice)}.` : `${result.expectationRule || "next_year_baseline"} with expected future price ${fmt.price(result.expectedFuturePrice)}.`}</li>
          </ul>
        </div>
      </section>
      <section className="panel panel-parts">
        <div className="panel-head"><div><div className="eyebrow">Figure 3</div><h2>Participant drilldown · {yearObj.year}</h2></div></div>
        <ParticipantPanel year={yearObj} result={result} selectedIdx={selPart} onSelectParticipant={(index) => setSelPart(index === selPart ? null : index)} sectorColors={SECTOR_COLORS} enabledFeatures={enabledFeatures} />
      </section>
      <section className="wb-grid">
        <div className="panel">
          <div className="panel-head">
            <div><div className="eyebrow">Figure 4</div><h2>Selected participant MAC</h2><p className="muted">Marginal abatement cost schedule for {selectedParticipant?.name || "the selected participant"} at {yearObj.year}.</p></div>
            <div className="panel-controls">
              <select value={selectedIndex} onChange={(event) => setSelPart(Number(event.target.value))}>
                {(yearObj.participants || []).map((participant, index) => (
                  <option key={`${participant.name}-${index}`} value={index}>{participant.name}</option>
                ))}
              </select>
            </div>
          </div>
          <ParticipantMacChart participant={selectedParticipant} outcome={selectedOutcome} carbonPrice={result.price} />
        </div>
        <div className="panel">
          <div className="panel-head"><div><div className="eyebrow">Analysis</div><h2>Model interpretation</h2></div></div>
          <ul className="analysis-list">
            {analysis.filter((item) => item.includes(scenario.name)).map((item, index) => <li key={index}>{item}</li>)}
          </ul>
        </div>
      </section>
      <section className="wb-grid">
        <div className="panel">
          <div className="panel-head">
            <div><div className="eyebrow">Figure 5</div><h2>Annual market pathway</h2><p className="muted">Interactive annual trajectory of equilibrium price, abatement, and auction revenue for this scenario.</p></div>
          </div>
          <AnnualMarketChart scenario={scenario} results={results} onSelectYear={onYearChange} />
        </div>
        <div className="panel">
          <div className="panel-head">
            <div><div className="eyebrow">Figure 6</div><h2>Annual emissions pathway</h2><p className="muted">Gross and residual emissions across years, plus the participant-level residual-emissions breakdown behind the transition.</p></div>
          </div>
          <AnnualEmissionsChart scenario={scenario} results={results} onSelectYear={onYearChange} />
        </div>
      </section>
      <section className="panel panel-note">
        <div className="panel-head"><div><div className="eyebrow">Calibration</div><h2>About the sample MACs</h2></div></div>
        <p className="muted">The participant MACs bundled in the example scenarios are demonstration inputs. They are economically coherent, but they are not calibrated sector estimates.</p>
        <p className="muted">For policy analysis, treat them as placeholders until you replace them with engineering, benchmarking, or observed-firm data for the selected participant.</p>
      </section>
      <AuctionPathwayPanel scenario={scenario} results={results} />
      <section className="panel">
        <div className="panel-head"><div><div className="eyebrow">Technology pathway</div><h2>Chosen technologies across years</h2><p className="muted">The annual technology selected by the optimization for each participant in this scenario.</p></div></div>
        <div className="pathway-table-wrap">
          <table className="pathway-table">
            <thead><tr><th>Participant</th>{technologyPathway.years.map((year) => <th key={year}>{year}</th>)}</tr></thead>
            <tbody>
              {technologyPathway.rows.map((row) => (
                <tr key={row.participant}>
                  <td>{row.participant}</td>
                  {row.pathway.map((technology, index) => (
                    <td key={`${row.participant}-${technologyPathway.years[index]}`}>{technology}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="panel">
        <div className="panel-head"><div><div className="eyebrow">Figure 7</div><h2>Year-by-year market views</h2><p className="muted">Interactive small-multiple market views for each year. Click a card to jump to that year.</p></div></div>
        <MarketYearGallery scenario={scenario} results={results} activeYear={activeYear} onSelectYear={onYearChange} />
      </section>
      {collectSlot(enabledFeatures, "summaryPanels").map((Panel, index) => (
        <Panel key={`summary-panel-${index}`} ctx={{ scenario, summary }} />
      ))}
      <footer className="foot">
        <span>Numerical method · Brent root finding in Python</span><span>·</span>
        <span>Source of truth · backend model in <code>ets/participant.py</code> and <code>ets/market.py</code></span><span>·</span>
        <span>Inputs are editable in the UI; rerun the scenario to refresh results</span>
      </footer>
    </div>
  );
}

function scenarioYearRows(scenarios, results, activeYear) {
  return scenarios
    .map((scenario) => {
      const year = scenario.years.find((item) => String(item.year) === String(activeYear));
      if (!year) return null;
      const result = results[scenario.name]?.[String(year.year)];
      if (!result) return null;
      const residual = (result.perParticipant || []).reduce((sum, participant) => sum + Number(participant.residual || 0), 0);
      const gross = (result.perParticipant || []).reduce((sum, participant) => sum + Number(participant.initial || 0), 0);
      const totalComplianceCost = (result.perParticipant || []).reduce((sum, participant) => sum + Number(participant.total_compliance_cost || 0), 0);
      const mixedParticipants = (result.perParticipant || []).filter((participant) => {
        const mix = String(participant.technology_mix || "");
        return mix.includes(";") || mix.includes("Mixed Portfolio");
      }).length;
      return {
        scenario,
        year,
        result,
        residual,
        gross,
        totalComplianceCost,
        mixedParticipants,
      };
    })
    .filter(Boolean);
}

function ComparisonMetricChart({ title, kicker, rows, scenarios, metricKey, valueFormatter, activeYear }) {
  const W = 860;
  const H = 260;
  const PAD = { t: 22, r: 28, b: 42, l: 74 };
  const years = [...new Set(scenarios.flatMap((scenario) => scenario.years.map((year) => String(year.year))))].sort();
  const series = scenarios.map((scenario) => ({
    name: scenario.name,
    color: scenario.color,
    values: years.map((year) => {
      const result = rows?.[scenario.name]?.[year];
      return Number(result?.[metricKey] ?? 0);
    }),
  }));
  const maxValue = Math.max(1, ...series.flatMap((item) => item.values));
  const xAt = (index) => {
    const iw = W - PAD.l - PAD.r;
    const n = Math.max(1, years.length - 1);
    return PAD.l + (index / n) * iw;
  };
  const yAt = (value) => {
    const ih = H - PAD.t - PAD.b;
    return PAD.t + ih - (Number(value || 0) / maxValue) * ih;
  };
  const tickValues = [0, maxValue / 2, maxValue];

  return (
    <div className="panel">
      <div className="panel-head">
        <div>
          <div className="eyebrow">{kicker}</div>
          <h2>{title}</h2>
          <p className="muted">Benchmark all scenarios across the full pathway while staying anchored on the selected year {activeYear}.</p>
        </div>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="chart">
        {tickValues.map((tick, index) => (
          <g key={`${title}-tick-${index}`}>
            <line x1={PAD.l} x2={W - PAD.r} y1={yAt(tick)} y2={yAt(tick)} className="gridline subtle" />
            <text x={PAD.l - 10} y={yAt(tick)} className="axis-label" textAnchor="end" dy="0.32em">
              {valueFormatter(tick)}
            </text>
          </g>
        ))}
        <line x1={PAD.l} x2={W - PAD.r} y1={H - PAD.b} y2={H - PAD.b} className="axis" />
        <line x1={PAD.l} x2={PAD.l} y1={PAD.t} y2={H - PAD.b} className="axis" />
        {years.map((year, index) => (
          <g key={`${title}-year-${year}`}>
            <line x1={xAt(index)} x2={xAt(index)} y1={PAD.t} y2={H - PAD.b} className="gridline subtle" />
            <text x={xAt(index)} y={H - 12} className="axis-label" textAnchor="middle">{year}</text>
          </g>
        ))}
        {series.map((item) => {
          const path = item.values.map((value, index) => `${index === 0 ? "M" : "L"}${xAt(index)},${yAt(value)}`).join(" ");
          return (
            <g key={`${title}-${item.name}`}>
              <path d={path} fill="none" stroke={item.color} strokeWidth="3" />
              {item.values.map((value, index) => (
                <circle key={`${item.name}-${years[index]}`} cx={xAt(index)} cy={yAt(value)} r={String(years[index]) === String(activeYear) ? "5.5" : "4"} fill={item.color} />
              ))}
              <text x={W - PAD.r + 6} y={yAt(item.values[item.values.length - 1])} className="line-label" fill={item.color}>
                {item.name}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

function Compare({ scenarios, results, activeYear, onYear }) {
  const allYears = [...new Set(scenarios.flatMap((scenario) => scenario.years.map((year) => String(year.year))))].sort();
  const compareRows = scenarioYearRows(scenarios, results, activeYear);
  const benchmarkPrice = [...compareRows].sort((left, right) => left.result.price - right.result.price)[0];
  const benchmarkResidual = [...compareRows].sort((left, right) => left.residual - right.residual)[0];
  const benchmarkRevenue = [...compareRows].sort((left, right) => right.result.revenue - left.result.revenue)[0];
  const comparisonSeries = scenarios.reduce((acc, scenario) => {
    const scenarioRuns = results?.[scenario.name] || {};
    acc[scenario.name] = Object.fromEntries(
      allYears.map((year) => {
        const run = scenarioRuns[year];
        const residual = (run?.perParticipant || []).reduce((sum, participant) => sum + Number(participant.residual || 0), 0);
        return [year, { price: Number(run?.price || 0), residual }];
      })
    );
    return acc;
  }, {});
  return (
    <div className="cmp">
      <div className="cmp-head">
        <div>
          <div className="eyebrow">Scenario studio</div>
          <h1>Scenario comparison dashboard</h1>
          <p className="lede">Commercial-style comparison of price, emissions, auction performance, and transition outcomes for {activeYear}.</p>
        </div>
        <div className="year-picker">
          {allYears.map((year) => (
            <button key={year} className={"pill-btn " + (year === activeYear ? "on" : "")} onClick={() => onYear(year)}>{year}</button>
          ))}
        </div>
      </div>
      <div className="cmp-benchmark-grid">
        <div className="cmp-benchmark-card">
          <div className="eyebrow">Best price</div>
          <strong>{benchmarkPrice?.scenario.name || "—"}</strong>
          <div className="cmp-benchmark-value">{benchmarkPrice ? fmt.price(benchmarkPrice.result.price) : "—"}</div>
        </div>
        <div className="cmp-benchmark-card">
          <div className="eyebrow">Lowest residual emissions</div>
          <strong>{benchmarkResidual?.scenario.name || "—"}</strong>
          <div className="cmp-benchmark-value">{benchmarkResidual ? `${fmt.num(benchmarkResidual.residual, 1)} Mt` : "—"}</div>
        </div>
        <div className="cmp-benchmark-card">
          <div className="eyebrow">Highest auction revenue</div>
          <strong>{benchmarkRevenue?.scenario.name || "—"}</strong>
          <div className="cmp-benchmark-value">{benchmarkRevenue ? fmt.money(benchmarkRevenue.result.revenue) : "—"}</div>
        </div>
      </div>
      <section className="panel cmp-matrix">
        <div className="panel-head">
          <div>
            <div className="eyebrow">Current-year matrix</div>
            <h2>Scenario performance in {activeYear}</h2>
            <p className="muted">Use this as the commercial comparison sheet for price, emissions, revenue, auction friction, and transition activity.</p>
          </div>
        </div>
        <div className="pathway-table-wrap">
          <table className="pathway-table cmp-matrix-table">
            <thead>
              <tr>
                <th>Scenario</th>
                <th>Price</th>
                <th>Residual emissions</th>
                <th>Abatement</th>
                <th>Auction sold</th>
                <th>Unsold</th>
                <th>Auction revenue</th>
                <th>Compliance cost</th>
                <th>Mixed adopters</th>
              </tr>
            </thead>
            <tbody>
              {compareRows.map((row) => (
                <tr key={row.scenario.id}>
                  <td>
                    <div className="cmp-scenario-cell">
                      <i className="sw" style={{ background: row.scenario.color }}></i>
                      <span>{row.scenario.name}</span>
                    </div>
                  </td>
                  <td>{fmt.price(row.result.price)}</td>
                  <td>{fmt.num(row.residual, 1)} Mt</td>
                  <td>{fmt.num(row.result.totalAbate, 1)} Mt</td>
                  <td>{fmt.num(row.result.auctionSold || row.result.Q || 0, 0)}</td>
                  <td>{fmt.num(row.result.unsoldAllowances || 0, 0)}</td>
                  <td>{fmt.money(row.result.revenue)}</td>
                  <td>{fmt.money(row.totalComplianceCost)}</td>
                  <td>{row.mixedParticipants}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      <section className="wb-grid">
        <ComparisonMetricChart
          title="Carbon price pathway"
          kicker="Cross-scenario trajectory"
          rows={comparisonSeries}
          scenarios={scenarios}
          metricKey="price"
          valueFormatter={(value) => fmt.price(value)}
          activeYear={activeYear}
        />
        <ComparisonMetricChart
          title="Residual emissions pathway"
          kicker="Cross-scenario trajectory"
          rows={comparisonSeries}
          scenarios={scenarios}
          metricKey="residual"
          valueFormatter={(value) => `${fmt.num(value, 1)} Mt`}
          activeYear={activeYear}
        />
      </section>
      <section className="cmp-grid">
        {compareRows.map((row) => (
          <div key={row.scenario.id} className="cmp-card cmp-card-pro" style={{ "--c": row.scenario.color }}>
            <div className="cmp-card-head">
              <div className="cmp-card-title">
                <i className="sw" style={{ background: row.scenario.color }}></i>
                <h3>{row.scenario.name}</h3>
              </div>
              <span className="cmp-chip">{activeYear}</span>
            </div>
            <div className="cmp-big">
              <div className="cmp-price">{fmt.price(row.result.price)}</div>
              <div className="cmp-sub">equilibrium price</div>
            </div>
            <div className="cmp-kpis">
              <div><div className="lbl">Residual</div><div className="val">{fmt.num(row.residual, 1)} Mt</div></div>
              <div><div className="lbl">Revenue</div><div className="val">{fmt.money(row.result.revenue)}</div></div>
              <div><div className="lbl">Unsold</div><div className="val">{fmt.num(row.result.unsoldAllowances || 0, 0)}</div></div>
            </div>
            <MiniMarket year={row.year} result={row.result} />
            <div className="cmp-notes">
              <div className="cmp-note"><span className="cmp-note-label">Technology mix</span><strong>{row.mixedParticipants} mixed participants</strong></div>
              <div className="cmp-note"><span className="cmp-note-label">Compliance burden</span><strong>{fmt.money(row.totalComplianceCost)}</strong></div>
            </div>
          </div>
        ))}
      </section>
    </div>
  );
}

export { BuildView, ValidationView, AnalysisView, Compare };
