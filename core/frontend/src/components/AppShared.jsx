import { useState as useS, useEffect as useE, useMemo as useM, useRef as useR } from "react";
import { fmt } from "./MarketChart.jsx";
import { activeFeatureIds, collectSlot, FEATURES } from "../registry.js";

// `feature` tags the metric-list / per-year attribute vocabulary with the
// feature module that owns it (see core/frontend/src/registry.js and
// ets/blocks/manifest.py, whose `derive_manifest` is the backend twin of
// this table — every field below is tagged with exactly the feature its
// backing block declares in ets/blocks/catalogue.py). `feature: null` means
// core — always eligible regardless of which features a pe-scoped model's
// manifest reports. Every surface that lists these metrics (BuildView's
// "Market timeline" attribute picker, and nothing else today — see
// visibleYearAttributeFields below) must filter through this table rather
// than hardcoding a metric's availability.
const SERIES_FIELD_META = {
  total_cap: { label: "Total cap", unit: "Mt CO₂e", step: 1, min: 0, feature: null, format: (value) => `${fmt.num(value, 0)} Mt`, description: "Hard annual ceiling on covered emissions. All allowance buckets (free allocation, auction, reserved, cancelled) must sum to this." },
  auction_offered: { label: "Auction offered", unit: "Mt CO₂e", step: 1, min: 0, feature: null, format: (value) => `${fmt.num(value, 0)} Mt`, description: "Volume offered at auction each year. Must not exceed total cap minus free allocation, reserved, and cancelled allowances." },
  reserved_allowances: { label: "Reserved allowances", unit: "Mt CO₂e", step: 1, min: 0, feature: null, format: (value) => `${fmt.num(value, 0)} Mt`, description: "Allowances withheld from the market this year. They are not auctioned and do not contribute to supply." },
  cancelled_allowances: { label: "Cancelled allowances", unit: "Mt CO₂e", step: 1, min: 0, feature: "price_controls", format: (value) => `${fmt.num(value, 0)} Mt`, description: "Allowances permanently retired from the cap. Reduces the effective supply permanently." },
  auction_reserve_price: { label: "Auction reserve price", unit: "$/t", step: 1, min: 0, feature: "price_controls", format: (value) => fmt.price(value), description: "Minimum price at which auction volume will clear. Offered allowances that cannot meet this price are treated as unsold." },
  minimum_bid_coverage: { label: "Minimum bid coverage", unit: "%", displayScale: 100, step: 5, min: 0, max: 100, feature: "price_controls", format: (value) => `${fmt.num(value, 0)}%`, description: "Minimum fraction of offered volume that must be covered by bids for the auction to clear. E.g. 80 means 80% of offered volume must be bid for." },
  price_lower_bound: { label: "Price floor", unit: "$/t", step: 1, min: 0, feature: "price_controls", format: (value) => fmt.price(value), description: "Equilibrium price cannot fall below this value. Models a minimum price guarantee or cost-containment mechanism." },
  price_upper_bound: { label: "Price ceiling", unit: "$/t", step: 1, min: 0, feature: "price_controls", format: (value) => fmt.price(value), description: "Equilibrium price is capped at this value. Models a safety valve or maximum price commitment." },
  borrowing_limit: { label: "Borrowing limit", unit: "Mt CO₂e", step: 1, min: 0, feature: "banking", format: (value) => `${fmt.num(value, 0)} Mt`, description: "Maximum volume a participant may borrow from a future period's allocation to cover current compliance. Requires borrowing to be enabled." },
  manual_expected_price: { label: "Manual expected price", unit: "$/t", step: 1, min: 0, feature: null, format: (value) => fmt.price(value), description: "Overrides the expectation rule and sets the future carbon price assumption manually. Only active when expectation rule is set to Manual." },
  carbon_budget: { label: "Carbon budget", unit: "Mt CO₂e", step: 1, min: 0, feature: "hotelling", format: (value) => `${fmt.num(value, 0)} Mt`, description: "Annual carbon budget for the Hotelling rule approach. The solver finds the shadow price λ such that cumulative residual emissions equal the cumulative budget across all years." },
  eua_price: { label: "EUA price (external)", unit: "$/t", step: 1, min: 0, feature: "cbam", format: (value) => fmt.price(value), description: "EU ETS allowance price for this year (external input). Used to compute CBAM liability = max(0, EUA − KAU) × CBAM-exposed residual emissions." },
  initial_emissions: { label: "Initial emissions", unit: "Mt CO₂e", step: 1, min: 0, feature: null, format: (value) => fmt.num(value, 1), description: "Gross emissions before any abatement. This is the participant's baseline coverage obligation each year." },
  free_allocation_ratio: { label: "Free allocation ratio", unit: "ratio 0–1", step: 0.05, min: 0, max: 1, feature: null, format: (value) => fmt.num(value, 2), description: "Share of a participant's initial emissions covered by free allowances. 1.0 means fully covered for free; 0 means no free allocation." },
  penalty_price: { label: "Penalty price", unit: "$/t", step: 1, min: 0, feature: null, format: (value) => fmt.price(value), description: "Price paid per tonne of uncovered emissions when a participant exceeds their allowance holdings. Acts as a compliance ceiling." },
  fixed_cost: { label: "Fixed cost", unit: "$", step: 1, min: 0, feature: null, format: (value) => fmt.num(value, 0), description: "One-time adoption cost for a technology option. Paid in the year a participant switches to that technology." },
  max_activity_share: { label: "Adoption share cap", unit: "ratio 0–1", step: 0.05, min: 0, max: 1, feature: null, format: (value) => fmt.num(value, 2), description: "Maximum fraction of a participant's activity that can switch to this technology option in any given year." },
};

function getSeriesFieldMeta(field) {
  return SERIES_FIELD_META[field] || {
    label: field.replaceAll("_", " "),
    step: 1,
    min: 0,
    feature: null,
    format: (value) => fmt.num(value, 2),
  };
}

// Core participant skeleton. Feature-owned defaults (cbam_*, Scope 2,
// sector_group, sector_allocation_share, OBA/output-price-elasticity
// fields) are composed in via the feature registry below, in
// registry-literal order — see core/frontend/src/registry.js.
function coreBlankParticipant(index = 1) {
  return {
    name: `Participant ${index}`,
    sector: "Other",
    initial_emissions: 0,
    free_allocation_ratio: 0,
    penalty_price: 100,
    abatement_type: "linear",
    max_abatement: 0,
    cost_slope: 1,
    threshold_cost: 0,
    mac_blocks: [],
    // BAU emissions trajectory
    initial_emissions_trajectory: {},
  };
}

function makeBlankParticipant(index = 1, enabledFeatures = null) {
  const featureDefaults = activeFeatureIds(enabledFeatures)
    .map((id) => FEATURES[id].participantDefaults)
    .filter(Boolean);
  return Object.assign(coreBlankParticipant(index), ...featureDefaults);
}

function makeBlankSector() {
  return { name: "New Sector", cap_trajectory: {}, auction_share_trajectory: {}, carbon_budget: 0 };
}

function makeBlankYear(label = "2030") {
  return {
    year: String(label),
    total_cap: 0,
    auction_mode: "explicit",
    auction_offered: 0,
    reserved_allowances: 0,
    cancelled_allowances: 0,
    auction_reserve_price: 0,
    minimum_bid_coverage: 0,
    unsold_treatment: "reserve",
    price_lower_bound: 0,
    price_upper_bound: 100,
    banking_allowed: false,
    borrowing_allowed: false,
    borrowing_limit: 0,
    expectation_rule: "next_year_baseline",
    manual_expected_price: 0,
    carbon_budget: 0,
    eua_price: 0,
    eua_prices: {},
    eua_price_ensemble: {},
    participants: [],
  };
}

// ── PE-mode config-driven field visibility ──────────────────────────────
// Owner rule (see repo history on branch feat/pe-scoping-sweep): in pe mode
// a field renders only if the loaded model's config sets it away from its
// backend default, or the user opted into the full field surface via the
// "Show advanced settings" toggle. This mirrors how the backend's own
// manifest derivation works — ets/blocks/decompile.py only synthesises a
// block node (and therefore counts a feature as "in play") when a field's
// value deviates from its ets/blocks/catalogue.py ParamSpec default across
// ANY year — so `isYearAttributeConfigured` below applies the same
// any-year-deviates rule the backend already uses. The unscoped (default)
// shell never calls any of this — every call site is gated on
// `enabledFeatures != null` (pe mode) at the caller.
function valueDiffersFromDefault(value, defaultValue) {
  if (Array.isArray(defaultValue)) {
    return JSON.stringify(value ?? []) !== JSON.stringify(defaultValue);
  }
  if (defaultValue && typeof defaultValue === "object") {
    return JSON.stringify(value ?? {}) !== JSON.stringify(defaultValue);
  }
  return (value ?? defaultValue) !== defaultValue;
}

// Backend mirror: ets/config_io/templates.py blank_year_config() (every key
// below matches its Python default 1:1 — see normalize.py's normalize_year
// for the same defaults applied when a key is absent from a loaded config).
const YEAR_FIELD_DEFAULTS = makeBlankYear();

function isYearAttributeConfigured(years, field) {
  const fallback = YEAR_FIELD_DEFAULTS[field];
  return (years || []).some((year) => valueDiffersFromDefault(year?.[field], fallback));
}

// Backend mirror: ets/config_io/builder.py normalize_scenario()'s `_fval`
// defaults for the solver-tuning knobs — the only scenario-level fields any
// pe-mode "Show advanced settings" gate currently needs (see Editor.jsx's
// "Solver tuning" / "Market clearing" blocks and the hotelling/nash_cournot/
// calibration feature modules' own tuning blocks).
const PE_SOLVER_FIELD_DEFAULTS = {
  solver_competitive_max_iters: 25,
  solver_competitive_tolerance: 0.001,
  solver_price_bracket_expand_factor: 2.0,
  solver_price_bracket_max_expansions: 10,
  solver_slsqp_max_iters: 400,
  solver_slsqp_ftol: 1e-9,
  solver_penalty_price_multiplier: 1.25,
  solver_hotelling_max_bisection_iters: 80,
  solver_hotelling_max_lambda_expansions: 20,
  solver_hotelling_convergence_tol: 0.0001,
  solver_hotelling_lambda_initial_low: 0.001,
  solver_hotelling_lambda_initial_high: 20.0,
  solver_hotelling_lambda_expand_factor: 3.0,
  solver_nash_price_step: 0.5,
  solver_nash_max_iters: 120,
  solver_nash_convergence_tol: 0.001,
  solver_nash_inner_xatol: 1e-4,
  solver_calibration_xatol: 0.1,
  solver_calibration_fatol: 0.01,
};

function isScenarioFieldConfigured(scenario, field) {
  return valueDiffersFromDefault(scenario?.[field], PE_SOLVER_FIELD_DEFAULTS[field]);
}

// A "Solver tuning"-style subsection (several scenario-level fields grouped
// under one heading) counts as configured if ANY field in it deviates —
// see the owner's exception: "a model that ships custom solver settings
// must not hide them silently."
function isScenarioSectionConfigured(scenario, fields) {
  return fields.some((field) => isScenarioFieldConfigured(scenario, field));
}

// The metric-list candidate fields (BuildView's "Market timeline" attribute
// picker — the one and only surface that lists these as a pickable set; see
// frontend/src/components/AppViews.jsx). Filters each candidate through
// SERIES_FIELD_META's feature tag, then — in pe mode, unless the user has
// revealed the full surface — through isYearAttributeConfigured.
function visibleYearAttributeFields(fields, { enabledFeatures, years, showAdvanced }) {
  if (enabledFeatures == null) return fields;
  const active = activeFeatureIds(enabledFeatures);
  return fields.filter((field) => {
    const meta = getSeriesFieldMeta(field);
    if (meta.feature && !active.includes(meta.feature)) return false;
    return showAdvanced || isYearAttributeConfigured(years, field);
  });
}

// Core scenario skeleton. Feature-owned defaults (msr_*, ccr_*, sectors,
// price_floor_trajectory/price_ceiling_trajectory, hotelling/nash_cournot
// approach + solver settings, reference_carbon_price) are composed in via
// the feature registry below, in registry-literal order — see
// core/frontend/src/registry.js. makeBlankYear stays entirely core
// (year-level defaults are out of scope for this composition — WO-F1 only
// decomposes makeBlankScenario/makeBlankParticipant).
function coreBlankScenario(index = 1) {
  return {
    id: `custom_scenario_${Date.now()}_${index}`,
    name: `New Scenario ${index}`,
    color: "#1f6f55",
    description: "Describe the policy design, participants, and transition logic for this scenario.",
    model_approach: "competitive",
    free_allocation_trajectories: [],
    cap_trajectory: {},
    // ── Solver settings (user-overridable, defaults match backend) ──────────
    solver_competitive_max_iters: 25,
    solver_competitive_tolerance: 0.001,
    solver_penalty_price_multiplier: 1.25,
    years: [makeBlankYear("2030")],
  };
}

function makeBlankScenario(index = 1, enabledFeatures = null) {
  const featureDefaults = activeFeatureIds(enabledFeatures)
    .map((id) => FEATURES[id].scenarioDefaults)
    .filter(Boolean);
  return Object.assign(coreBlankScenario(index), ...featureDefaults);
}

function buildDraftResult(year) {
  const priceFloor = Number(year?.price_lower_bound ?? 0);
  const priceCeiling = Math.max(priceFloor + 1, Number(year?.price_upper_bound ?? 100));
  const participants = year?.participants || [];
  const q = year?.auction_mode === "explicit"
    ? Number(year?.auction_offered ?? year?.auctioned_allowances ?? 0)
    : Math.max(
        0,
        Number(year?.total_cap ?? 0) - participants.reduce(
          (sum, participant) =>
            sum + Number(participant.initial_emissions || 0) * Number(participant.free_allocation_ratio || 0),
          0
        ) - Number(year?.reserved_allowances ?? 0) - Number(year?.cancelled_allowances ?? 0)
      );
  const perParticipant = participants.map((participant) => {
    const initial = Number(participant.initial_emissions || 0);
    const free = initial * Number(participant.free_allocation_ratio || 0);
    const net = Math.max(0, initial - free);
    return {
      name: participant.name,
      initial,
      free,
      abatement: 0,
      residual: initial,
      net_trade: net,
      ratio: participant.free_allocation_ratio || 0,
      allowance_buys: net,
      allowance_sells: Math.max(0, free - initial),
      penalty_emissions: 0,
      abatement_cost: 0,
      allowance_cost: 0,
      penalty_cost: 0,
      sales_revenue: 0,
      total_compliance_cost: 0,
      sector: participant.sector || "Other",
      technology_mix: "",
    };
  });
  const baselineTotal = perParticipant.reduce((sum, participant) => sum + participant.net_trade, 0);
  return {
    price: null,
    Q: q,
    totalAbate: 0,
    totalTraded: baselineTotal,
    revenue: 0,
    perParticipant,
    demandCurve: [
      { p: priceFloor, total: baselineTotal, perPart: perParticipant.map((participant) => participant.net_trade) },
      { p: priceCeiling, total: baselineTotal, perPart: perParticipant.map((participant) => participant.net_trade) },
    ],
  };
}

function configsEqual(left, right) {
  return JSON.stringify(left) === JSON.stringify(right);
}

function buildTechnologyPathway(scenario, results) {
  const years = (scenario?.years || []).map((year) => String(year.year));
  const rows = (scenario?.years?.[0]?.participants || []).map((participant) => {
    const pathway = years.map((year) => {
      const yearResult = results?.[scenario.name]?.[year];
      const match = yearResult?.perParticipant?.find((item) => item.name === participant.name);
      return match?.technology || "Base Technology";
    });
    return { participant: participant.name, pathway };
  });
  return { years, rows };
}

function describeUnsoldTreatment(value) {
  if (value === "carry_forward") return "Carry forward to next year";
  if (value === "cancel") return "Cancel unsold volume";
  return "Move unsold volume to reserve";
}

function buildAuctionPathway(scenario, results) {
  const years = (scenario?.years || []).map((year) => String(year.year));
  const rows = years.map((year) => {
    const run = results?.[scenario.name]?.[year] || null;
    const yearConfig = (scenario?.years || []).find((item) => String(item.year) === year) || {};
    return {
      year,
      offered: Number(run?.auctionOffered ?? yearConfig.auction_offered ?? 0),
      sold: Number(run?.auctionSold ?? 0),
      unsold: Number(run?.unsoldAllowances ?? 0),
      coverageRatio: Number(run?.auctionCoverageRatio ?? 1),
      reservePrice: Number(yearConfig.auction_reserve_price ?? 0),
      minimumBidCoverage: Number(yearConfig.minimum_bid_coverage ?? 0),
      unsoldTreatment: String(yearConfig.unsold_treatment ?? "reserve"),
      reserved: Number(yearConfig.reserved_allowances ?? 0),
      cancelled: Number(yearConfig.cancelled_allowances ?? 0),
    };
  });
  return { years, rows };
}

function makeIssue(level, scope, message, target = null) {
  return { level, scope, message, target };
}

function validateMacBlocks(blocks, label, target = null) {
  const issues = [];
  if (!Array.isArray(blocks)) {
    issues.push(makeIssue("error", label, "MAC blocks must be provided as a list.", target));
    return issues;
  }
  let previousCost = -Infinity;
  blocks.forEach((block, index) => {
    const amount = Number(block?.amount ?? 0);
    const cost = Number(block?.marginal_cost ?? 0);
    if (!Number.isFinite(amount) || !Number.isFinite(cost)) {
      issues.push(makeIssue("error", label, `MAC block ${index + 1} must contain numeric amount and marginal cost.`, target));
      return;
    }
    if (amount < 0 || cost < 0) {
      issues.push(makeIssue("error", label, `MAC block ${index + 1} must be non-negative.`, target));
    }
    if (cost < previousCost) {
      issues.push(makeIssue("error", label, "MAC blocks must be ordered by non-decreasing marginal cost.", target));
    }
    previousCost = cost;
  });
  return issues;
}

function validateTechnology(option, scope, target = null) {
  const issues = [];
  if (!option?.name) issues.push(makeIssue("error", scope, "Technology option must have a name.", target));
  if (Number(option?.initial_emissions ?? 0) < 0) issues.push(makeIssue("error", scope, "Technology emissions must be non-negative.", target));
  if (Number(option?.free_allocation_ratio ?? 0) < 0 || Number(option?.free_allocation_ratio ?? 0) > 1) {
    issues.push(makeIssue("error", scope, "Technology free allocation ratio must be between 0 and 1.", target));
  }
  if (Number(option?.penalty_price ?? 0) <= 0) issues.push(makeIssue("error", scope, "Technology penalty price must be positive.", target));
  if (Number(option?.fixed_cost ?? 0) < 0) issues.push(makeIssue("error", scope, "Technology fixed cost must be non-negative.", target));
  if (Number(option?.max_activity_share ?? 1) < 0 || Number(option?.max_activity_share ?? 1) > 1) {
    issues.push(makeIssue("error", scope, "Technology adoption share cap must be between 0 and 1.", target));
  }
  if (option?.abatement_type === "piecewise" && !(option?.mac_blocks || []).length) {
    issues.push(makeIssue("error", scope, "Piecewise technology option requires MAC blocks.", target));
  }
  issues.push(...validateMacBlocks(option?.mac_blocks || [], scope, target));
  return issues;
}

function validateParticipant(participant, yearLabel, yearValue) {
  const scope = `${yearLabel} · ${participant?.name || "Unnamed participant"}`;
  const participantTarget = {
    section: "build",
    step: "participants",
    year: String(yearValue),
    participantName: participant?.name || null,
  };
  const issues = [];
  if (!participant?.name) issues.push(makeIssue("error", scope, "Participant must have a name.", participantTarget));
  const emissions = Number(participant?.initial_emissions ?? 0);
  const freeRatio = Number(participant?.free_allocation_ratio ?? 0);
  const penalty = Number(participant?.penalty_price ?? 0);
  if (emissions < 0) issues.push(makeIssue("error", scope, "Initial emissions must be non-negative.", participantTarget));
  if (freeRatio < 0 || freeRatio > 1) issues.push(makeIssue("error", scope, "Free allocation ratio must be between 0 and 1.", participantTarget));
  if (penalty <= 0) issues.push(makeIssue("error", scope, "Penalty price must be positive.", participantTarget));
  if (participant?.abatement_type === "piecewise" && !(participant?.mac_blocks || []).length) {
    issues.push(makeIssue("error", scope, "Piecewise abatement requires MAC blocks.", participantTarget));
  }
  if ((participant?.technology_options || []).length > 0) {
    const techNames = new Set();
    participant.technology_options.forEach((option) => {
      const technologyTarget = {
        ...participantTarget,
        technologyName: option?.name || null,
      };
      if (techNames.has(option.name)) {
        issues.push(makeIssue("warning", scope, `Duplicate technology option name '${option.name}'.`, technologyTarget));
      }
      techNames.add(option.name);
      issues.push(...validateTechnology(option, `${scope} · ${option.name || "Unnamed technology"}`, technologyTarget));
    });
  }
  issues.push(...validateMacBlocks(participant?.mac_blocks || [], scope, participantTarget));
  return issues;
}

function validateScenario(scenario, enabledFeatures = null) {
  const issues = [];
  if (!scenario) return issues;
  if (!scenario.name) issues.push(makeIssue("error", "Scenario", "Scenario must have a name.", { section: "build", step: "scenario" }));
  if (!(scenario.years || []).length) issues.push(makeIssue("error", "Scenario", "Scenario must contain at least one year.", { section: "build", step: "scenario" }));
  const seenYears = new Set();
  (scenario.years || []).forEach((year) => {
    const yearLabel = String(year?.year || "Unnamed year");
    const yearTarget = { section: "build", step: "market", year: yearLabel };
    if (seenYears.has(yearLabel)) issues.push(makeIssue("error", `Year ${yearLabel}`, "Duplicate year label.", yearTarget));
    seenYears.add(yearLabel);
    const participants = year?.participants || [];
    if (!participants.length) issues.push(makeIssue("warning", `Year ${yearLabel}`, "This year has no participants.", yearTarget));
    const lower = Number(year?.price_lower_bound ?? 0);
    const upper = Number(year?.price_upper_bound ?? 0);
    if (upper <= lower) issues.push(makeIssue("error", `Year ${yearLabel}`, "Price ceiling must be greater than price floor.", yearTarget));
    if (year?.borrowing_allowed && Number(year?.borrowing_limit ?? 0) <= 0) {
      issues.push(makeIssue("warning", `Year ${yearLabel}`, "Borrowing is enabled but borrowing limit is zero.", yearTarget));
    }
    const expectationRule = String(year?.expectation_rule ?? "next_year_baseline");
    if (!["myopic", "next_year_baseline", "perfect_foresight", "manual"].includes(expectationRule)) {
      issues.push(makeIssue("error", `Year ${yearLabel}`, "Expectation rule must be myopic, next_year_baseline, perfect_foresight, or manual.", yearTarget));
    }
    if (Number(year?.manual_expected_price ?? 0) < 0) {
      issues.push(makeIssue("error", `Year ${yearLabel}`, "Manual expected price must be non-negative.", yearTarget));
    }
    if (expectationRule === "manual" && Number(year?.manual_expected_price ?? 0) <= 0) {
      issues.push(makeIssue("warning", `Year ${yearLabel}`, "Manual expectation is selected but manual expected price is zero.", yearTarget));
    }
    if (Number(year?.auction_reserve_price ?? 0) < 0) {
      issues.push(makeIssue("error", `Year ${yearLabel}`, "Auction reserve price must be non-negative.", yearTarget));
    }
    if (Number(year?.minimum_bid_coverage ?? 0) < 0 || Number(year?.minimum_bid_coverage ?? 0) > 1) {
      issues.push(makeIssue("error", `Year ${yearLabel}`, "Minimum bid coverage must be between 0 and 1.", yearTarget));
    }
    if (!["reserve", "cancel", "carry_forward"].includes(String(year?.unsold_treatment ?? "reserve"))) {
      issues.push(makeIssue("error", `Year ${yearLabel}`, "Unsold treatment must be reserve, cancel, or carry_forward.", yearTarget));
    }
    const freeAllocation = participants.reduce(
      (sum, participant) => sum + Number(participant?.initial_emissions ?? 0) * Number(participant?.free_allocation_ratio ?? 0),
      0
    );
    const auctioned = Number(year?.auction_offered ?? year?.auctioned_allowances ?? 0);
    const reserved = Number(year?.reserved_allowances ?? 0);
    const cancelled = Number(year?.cancelled_allowances ?? 0);
    const totalCap = Number(year?.total_cap ?? 0);
    if (year?.auction_mode === "explicit") {
      const allowanceSupply = freeAllocation + auctioned + reserved + cancelled;
      if (allowanceSupply - totalCap > 1e-6) {
        issues.push(makeIssue("error", `Year ${yearLabel}`, `Free allocation + auction offered + reserved + cancelled allowances (${allowanceSupply.toFixed(2)}) exceeds total cap (${totalCap.toFixed(2)}).`, yearTarget));
      } else if (totalCap - allowanceSupply > 1e-6) {
        issues.push(makeIssue("warning", `Year ${yearLabel}`, `Configured supply buckets leave ${(totalCap - allowanceSupply).toFixed(2)} allowances unallocated within the cap.`, yearTarget));
      }
    }
    if (reserved > 0) issues.push(makeIssue("note", `Year ${yearLabel}`, `Reserved allowances remove ${reserved.toFixed(2)} allowances from current-year circulation.`, yearTarget));
    if (cancelled > 0) issues.push(makeIssue("note", `Year ${yearLabel}`, `Cancelled allowances permanently retire ${cancelled.toFixed(2)} allowances from the cap.`, yearTarget));
    if ((year?.auction_reserve_price ?? 0) > 0) issues.push(makeIssue("note", `Year ${yearLabel}`, `Auction reserve price is set at ${Number(year.auction_reserve_price).toFixed(2)}.`, yearTarget));
    if ((year?.minimum_bid_coverage ?? 0) > 0) issues.push(makeIssue("note", `Year ${yearLabel}`, `Minimum bid coverage is set at ${(Number(year.minimum_bid_coverage) * 100).toFixed(0)}% of auction volume.`, yearTarget));
    if (expectationRule === "manual") issues.push(makeIssue("note", `Year ${yearLabel}`, `Manual expected future price is set at ${Number(year.manual_expected_price ?? 0).toFixed(2)}.`, yearTarget));
    if (expectationRule === "perfect_foresight") issues.push(makeIssue("note", `Year ${yearLabel}`, "Perfect foresight expectations are active for this year.", yearTarget));
    const names = new Set();
    participants.forEach((participant) => {
      if (names.has(participant.name)) {
        issues.push(makeIssue("error", `Year ${yearLabel}`, `Duplicate participant name '${participant.name}'.`, {
          section: "build",
          step: "participants",
          year: yearLabel,
          participantName: participant?.name || null,
        }));
      }
      names.add(participant.name);
      issues.push(...validateParticipant(participant, `Year ${yearLabel}`, yearLabel));
    });
  });
  // Feature-specific rules (composed in registry order; none defined for
  // msr/ccr today — see core/frontend/src/registry.js).
  collectSlot(enabledFeatures, "validators").forEach((validate) => {
    issues.push(...(validate(scenario) || []));
  });
  if (!issues.length) issues.push(makeIssue("note", "Scenario", "No validation issues detected for the active scenario.", { section: "validation" }));
  return issues;
}

function KPI({ label, value, sub, tone }) {
  return (
    <div className={"kpi" + (tone ? " tone-" + tone : "")}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value">{value}</div>
      {sub && <div className="kpi-sub">{sub}</div>}
    </div>
  );
}

function ValidationPanel({ issues, title = "Validation", onNavigateIssue = null }) {
  const counts = {
    error: issues.filter((issue) => issue.level === "error").length,
    warning: issues.filter((issue) => issue.level === "warning").length,
    note: issues.filter((issue) => issue.level === "note").length,
  };
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <div className="eyebrow">Validation</div>
          <h2>{title}</h2>
          <p className="muted">Pre-run checks on the active scenario configuration.</p>
        </div>
        <div className="validation-summary">
          <span className="validation-pill error">{counts.error} errors</span>
          <span className="validation-pill warning">{counts.warning} warnings</span>
          <span className="validation-pill note">{counts.note} notes</span>
        </div>
      </div>
      <div className="validation-list">
        {issues.map((issue, index) => (
          <button
            key={`${issue.scope}-${issue.message}-${index}`}
            className={`validation-item ${issue.level} ${issue.target ? "clickable" : ""}`}
            onClick={() => issue.target && onNavigateIssue?.(issue)}
            disabled={!issue.target}
            type="button"
          >
            <div className="validation-item-head">
              <span className={`validation-dot ${issue.level}`}></span>
              <strong>{issue.scope}</strong>
              {issue.target ? <span className="validation-jump">Open</span> : null}
            </div>
            <div className="validation-message">{issue.message}</div>
          </button>
        ))}
      </div>
    </section>
  );
}

function AuctionDiagnosticsPanel({ yearObj, result }) {
  const offered = Number(result?.auctionOffered ?? yearObj?.auction_offered ?? 0);
  const sold = Number(result?.auctionSold ?? 0);
  const unsold = Number(result?.unsoldAllowances ?? 0);
  const coverage = Number(result?.auctionCoverageRatio ?? 1);
  const reservePrice = Number(yearObj?.auction_reserve_price ?? 0);
  const minCoverage = Number(yearObj?.minimum_bid_coverage ?? 0);
  const treatment = String(yearObj?.unsold_treatment ?? "reserve");
  const bindingRule =
    unsold > 0 && reservePrice > 0
      ? "Reserve price constrained auction sales in this year."
      : unsold > 0 && minCoverage > 0
        ? "Minimum bid coverage constrained auction sales in this year."
        : unsold > 0
          ? "Auction supply was not fully absorbed in this year."
          : "Auction volume was fully sold in this year.";
  return (
    <div className="panel">
      <div className="panel-head">
        <div>
          <div className="eyebrow">Auction</div>
          <h2>Current-year auction outcome</h2>
          <p className="muted">How offered allowances translated into sold volume, unsold volume, and policy treatment in {yearObj?.year}.</p>
        </div>
      </div>
      <div className="review-grid auction-review-grid">
        <div className="review-item"><span className="review-label">Auction offered</span><strong>{fmt.num(offered, 0)}</strong></div>
        <div className="review-item"><span className="review-label">Auction sold</span><strong>{fmt.num(sold, 0)}</strong></div>
        <div className="review-item"><span className="review-label">Unsold allowances</span><strong>{fmt.num(unsold, 0)}</strong></div>
        <div className="review-item"><span className="review-label">Coverage ratio</span><strong>{fmt.num(coverage * 100, 0)}%</strong></div>
        <div className="review-item"><span className="review-label">Reserve price</span><strong>{fmt.price(reservePrice)}</strong></div>
        <div className="review-item"><span className="review-label">Minimum bid coverage</span><strong>{fmt.num(minCoverage * 100, 0)}%</strong></div>
        <div className="review-item review-item-wide"><span className="review-label">Unsold treatment</span><strong>{describeUnsoldTreatment(treatment)}</strong></div>
        <div className="review-item review-item-wide"><span className="review-label">Interpretation</span><strong>{bindingRule}</strong></div>
      </div>
    </div>
  );
}

function AuctionPathwayPanel({ scenario, results }) {
  const auctionPathway = buildAuctionPathway(scenario, results);
  return (
    <div className="panel">
      <div className="panel-head">
        <div>
          <div className="eyebrow">Auction pathway</div>
          <h2>Offered, sold, and unsold allowances across years</h2>
          <p className="muted">Tracks the auction flow and the rule set that governs unsold volumes in each year of this scenario.</p>
        </div>
      </div>
      <div className="pathway-table-wrap">
        <table className="pathway-table">
          <thead>
            <tr>
              <th>Year</th>
              <th>Offered</th>
              <th>Sold</th>
              <th>Unsold</th>
              <th>Coverage</th>
              <th>Reserve price</th>
              <th>Min coverage</th>
              <th>Unsold treatment</th>
            </tr>
          </thead>
          <tbody>
            {auctionPathway.rows.map((row) => (
              <tr key={row.year}>
                <td>{row.year}</td>
                <td>{fmt.num(row.offered, 0)}</td>
                <td>{fmt.num(row.sold, 0)}</td>
                <td>{fmt.num(row.unsold, 0)}</td>
                <td>{fmt.num(row.coverageRatio * 100, 0)}%</td>
                <td>{fmt.price(row.reservePrice)}</td>
                <td>{fmt.num(row.minimumBidCoverage * 100, 0)}%</td>
                <td>{describeUnsoldTreatment(row.unsoldTreatment)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Header({
  scenarios,
  templates,
  activeId,
  onSelectScenario,
  activeSection,
  onSelectSection,
  onLoadTemplate,
  onSaveScenario,
  onAddScenario,
  onDuplicateScenario,
  onRemoveScenario,
  status,
  showGuideTab = true,
  // Optional "save the current working config as a SESSION" action. Present
  // only in the pe.command shell (App passes it); the default shell leaves it
  // out, so the button never renders there.
  onSaveSession = null,
  // Optional "promote the working config back into the MODEL library" action —
  // onSaveModel(asNew) posts to /api/model (asNew=false => UPDATE the source
  // model, asNew=true => NEW model). The "Update model" button shows only when
  // a source model is known (canUpdateModel); "Save as new model" is always
  // available when onSaveModel is passed.
  onSaveModel = null,
  canUpdateModel = false,
  // pe mode locks the shell to the model chosen on the welcome page — "Back
  // to models" (frontend/src/pe/PeApp.jsx's ModelToolbar) is the only way to
  // switch models, so the in-editor template splice control is hidden here.
  // Save/Add/Duplicate/Remove stay: they operate within the current model,
  // not across models. Unscoped (default) shell: unchanged, always shown.
  hideLoadTemplate = false,
}) {
  const [selectedTemplate, setSelectedTemplate] = useS(templates?.[0]?.id || "blank");
  const sections = [
    { id: "build", label: "Model" },
    { id: "canvas", label: "Canvas" },
    { id: "validation", label: "Validation" },
    { id: "analysis", label: "Analysis" },
    { id: "scenario", label: "Scenario" },
    ...(showGuideTab ? [{ id: "guide", label: "Guide" }] : []),
  ];
  useE(() => {
    if (templates.length && !templates.some((item) => item.id === selectedTemplate)) {
      setSelectedTemplate(templates[0].id);
    }
  }, [templates]);

  return (
    <header className="hdr">
      <div className="hdr-top">
        <div className="hdr-brand">
          <div className="mark">
            <svg viewBox="0 0 40 40" width="28" height="28">
              <circle cx="20" cy="20" r="18" fill="none" stroke="currentColor" strokeWidth="1.5"/>
              <path d="M4 26 Q14 22 20 20 T36 14" fill="none" stroke="currentColor" strokeWidth="1.5"/>
              <line x1="4" x2="36" y1="20" y2="20" stroke="currentColor" strokeWidth="1" strokeDasharray="2 2"/>
              <circle cx="20" cy="20" r="3" fill="currentColor"/>
            </svg>
          </div>
          <div>
            <div className="brand-title">Clearing</div>
            <div className="brand-sub">{status}</div>
          </div>
        </div>
        <div className="hdr-actions">
          <nav className="hdr-sections">
            {sections.map((section) => (
              <button
                key={section.id}
                className={"section-tab " + (activeSection === section.id ? "on" : "")}
                onClick={() => onSelectSection(section.id)}
              >
                {section.label}
              </button>
            ))}
          </nav>
          {onSaveSession && (
            <button className="ghost-btn" onClick={onSaveSession}>Save as session</button>
          )}
          {onSaveModel && canUpdateModel && (
            <button className="ghost-btn" onClick={() => onSaveModel(false)}>Update model</button>
          )}
          {onSaveModel && (
            <button className="ghost-btn" onClick={() => onSaveModel(true)}>Save as new model</button>
          )}
        </div>
      </div>
      {activeSection === "build" && (
        <div className="hdr-tools">
          {!hideLoadTemplate && (
            <>
              <select value={selectedTemplate} onChange={(e) => setSelectedTemplate(e.target.value)}>
                {templates.map((template) => <option key={template.id} value={template.id}>{template.name}</option>)}
              </select>
              <button className="ghost-btn" onClick={() => onLoadTemplate(selectedTemplate)}>Load template</button>
            </>
          )}
          <button className="ghost-btn" onClick={onSaveScenario}>Save scenario</button>
          <button className="ghost-btn" onClick={onAddScenario}>Add scenario</button>
          <button className="ghost-btn" onClick={onDuplicateScenario}>Duplicate scenario</button>
          <button className="ghost-btn danger-btn" onClick={onRemoveScenario} disabled={scenarios.length <= 1}>Remove scenario</button>
        </div>
      )}
      <nav className="hdr-scenarios">
        {scenarios.map((scenario) => (
          <button
            key={scenario.id}
            className={"pill-btn " + (activeId === scenario.id ? "on" : "")}
            onClick={() => onSelectScenario(scenario.id)}
            style={{ "--c": scenario.color }}
          >
            <i className="sw" style={{ background: scenario.color }}></i>{scenario.name}
          </button>
        ))}
      </nav>
    </header>
  );
}

function ScenarioHero({ scenario, activeYear, onYearChange, results, primaryMetric = null, secondaryMetric = null, showYearStrip = true }) {
  const resByYear = results?.[scenario.name] || {};
  return (
    <section className="wb-hero">
      <div className="scenario-meta">
        <div className="eyebrow">Scenario</div>
        <h1 style={{ color: scenario.color }}>{scenario.name}</h1>
        <p className="lede">{scenario.description}</p>
        {showYearStrip && (
          <div className="year-strip">
            {scenario.years.map((year) => (
              <button
                key={year.year}
                className={"ystep " + (String(year.year) === String(activeYear) ? "on" : "")}
                onClick={() => onYearChange(String(year.year))}
              >
                <div className="yv">{year.year}</div>
                <div className="yp">{fmt.price(resByYear[String(year.year)]?.price)}</div>
              </button>
            ))}
          </div>
        )}
      </div>
      <div className="hero-side">
        {primaryMetric}
        {secondaryMetric}
      </div>
    </section>
  );
}

function SeriesTrajectoryEditor({ years, draft, setDraft, meta }) {
  const svgRef = useR(null);
  const [dragYear, setDragYear] = useS(null);
  const [activeEditYear, setActiveEditYear] = useS(null);
  const W = 820;
  const H = 280;
  const PAD = { t: 24, r: 24, b: 46, l: 76 };
  const innerW = W - PAD.l - PAD.r;
  const innerH = H - PAD.t - PAD.b;
  const orderedYears = useM(() => (years || []).map((year) => String(year.year)), [years]);
  const values = orderedYears.map((year) => Number(draft[year] ?? 0));
  const minValue = meta.min ?? Math.min(0, ...values);
  const dataMax = Math.max(...values, 0);
  const floorMax = meta.max ?? 100;
  const domainMax = dataMax > floorMax ? dataMax * 1.1 : floorMax;
  const xAt = (index) => PAD.l + (orderedYears.length <= 1 ? innerW / 2 : (index / (orderedYears.length - 1)) * innerW);
  const yAt = (value) => {
    const ratio = (Number(value ?? 0) - minValue) / (domainMax - minValue);
    return PAD.t + innerH - Math.max(0, Math.min(1, ratio)) * innerH;
  };
  const updateFromPointer = (event) => {
    if (!dragYear || !svgRef.current) return;
    const rect = svgRef.current.getBoundingClientRect();
    const y = event.clientY - rect.top;
    const ratio = 1 - (y - PAD.t) / innerH;
    const unclamped = minValue + Math.max(0, Math.min(1, ratio)) * (domainMax - minValue);
    const next = meta.step && meta.step < 1
      ? Math.round(unclamped / meta.step) * meta.step
      : Math.round(unclamped / (meta.step || 1)) * (meta.step || 1);
    const clamped = Math.max(meta.min ?? -Infinity, Math.min(meta.max ?? Infinity, Number(next.toFixed(4))));
    setDraft((current) => ({ ...current, [dragYear]: clamped }));
  };
  useE(() => {
    if (!dragYear) return undefined;
    const handleMove = (event) => updateFromPointer(event);
    const handleUp = () => setDragYear(null);
    window.addEventListener("mousemove", handleMove);
    window.addEventListener("mouseup", handleUp);
    return () => {
      window.removeEventListener("mousemove", handleMove);
      window.removeEventListener("mouseup", handleUp);
    };
  }, [dragYear, minValue, domainMax, meta.step, meta.min, meta.max]);
  useE(() => {
    if (dragYear) setActiveEditYear(null);
  }, [dragYear]);
  const tickValues = Array.from({ length: 5 }, (_, index) => minValue + ((domainMax - minValue) * index) / 4);
  const path = orderedYears
    .map((year, index) => `${index === 0 ? "M" : "L"}${xAt(index)},${yAt(draft[year])}`)
    .join(" ");

  return (
    <div className="series-chart-panel">
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        className="series-chart"
        onMouseMove={updateFromPointer}
      >
        {tickValues.map((tick, index) => (
          <g key={`tick-${index}`}>
            <line x1={PAD.l} x2={W - PAD.r} y1={yAt(tick)} y2={yAt(tick)} className="gridline" />
            <text x={PAD.l - 10} y={yAt(tick)} className="axis-label" textAnchor="end" dy="0.32em">
              {meta.format(tick)}
            </text>
          </g>
        ))}
        {orderedYears.map((year, index) => (
          <g key={year}>
            <line x1={xAt(index)} x2={xAt(index)} y1={PAD.t} y2={H - PAD.b} className="gridline subtle" />
            <text x={xAt(index)} y={H - PAD.b + 18} className="axis-label" textAnchor="middle">
              {year}
            </text>
          </g>
        ))}
        <line x1={PAD.l} x2={W - PAD.r} y1={H - PAD.b} y2={H - PAD.b} className="axis" />
        <line x1={PAD.l} x2={PAD.l} y1={PAD.t} y2={H - PAD.b} className="axis" />
        {meta.unit && (
          <text
            x={14}
            y={PAD.t + (H - PAD.t - PAD.b) / 2}
            className="axis-title"
            textAnchor="middle"
            transform={`rotate(-90, 14, ${PAD.t + (H - PAD.t - PAD.b) / 2})`}
          >
            {meta.unit}
          </text>
        )}
        <path d={path} className="series-line" />
        {orderedYears.map((year, index) => (
          <g key={`point-${year}`}>
            <circle
              cx={xAt(index)}
              cy={yAt(draft[year])}
              r="6"
              className={"series-point " + (dragYear === year ? "dragging" : "")}
              onMouseDown={() => setDragYear(year)}
              onClick={() => setActiveEditYear(year)}
            />
            <text
              x={xAt(index)}
              y={yAt(draft[year]) - 12}
              className="point-label point-label-interactive"
              textAnchor="middle"
              onClick={() => setActiveEditYear(year)}
            >
              {meta.format(draft[year])}
            </text>
            {activeEditYear === year && (
              <foreignObject x={xAt(index) - 42} y={yAt(draft[year]) - 48} width="84" height="34">
                <input
                  className="series-point-input"
                  type="number"
                  autoFocus
                  step={meta.step}
                  min={meta.min}
                  max={meta.max}
                  value={draft[year] ?? 0}
                  onChange={(event) =>
                    setDraft((current) => ({
                      ...current,
                      [year]: clampSeriesValue(event.target.value, meta),
                    }))
                  }
                  onBlur={() => setActiveEditYear(null)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === "Escape") {
                      setActiveEditYear(null);
                    }
                  }}
                />
              </foreignObject>
            )}
          </g>
        ))}
      </svg>
      <div className="series-chart-help">
        <span>Drag a point to edit the value for that year.</span>
        <span>Click the value label on the chart to type an exact number inline.</span>
      </div>
    </div>
  );
}

function clampSeriesValue(value, meta) {
  const min = meta.min ?? -Infinity;
  const max = meta.max ?? Infinity;
  const step = meta.step || 1;
  const rounded = step < 1
    ? Math.round(Number(value) / step) * step
    : Math.round(Number(value) / step) * step;
  return Number(Math.max(min, Math.min(max, rounded)).toFixed(4));
}

function generateSeriesPath({
  years,
  draft,
  meta,
  rule,
  startValue,
  endValue,
  holdUntilYear,
  percentRate,
  applyStartYear,
  applyEndYear,
}) {
  const orderedYears = (years || []).map((year) => String(year.year));
  if (!orderedYears.length) return draft;
  const requestedStart = orderedYears.indexOf(String(applyStartYear));
  const requestedEnd = orderedYears.indexOf(String(applyEndYear));
  const firstIndex = requestedStart >= 0 ? requestedStart : 0;
  const lastIndex = requestedEnd >= 0 ? requestedEnd : orderedYears.length - 1;
  const rangeStart = Math.min(firstIndex, lastIndex);
  const rangeEnd = Math.max(firstIndex, lastIndex);
  const start = clampSeriesValue(startValue, meta);
  const end = clampSeriesValue(endValue, meta);
  const holdIndex = Math.max(rangeStart, Math.min(rangeEnd, orderedYears.indexOf(String(holdUntilYear))));
  const next = { ...draft };

  orderedYears.forEach((yearKey, index) => {
    if (index < rangeStart || index > rangeEnd) {
      return;
    }
    const progress = rangeEnd === rangeStart ? 1 : (index - rangeStart) / (rangeEnd - rangeStart);
    let value = start;
    if (rule === "linear") {
      value = start + (end - start) * progress;
    } else if (rule === "step") {
      value = index < rangeEnd ? start : end;
    } else if (rule === "percent_decline") {
      value = start * Math.pow(1 - Number(percentRate || 0) / 100, index - rangeStart);
    } else if (rule === "hold_then_drop") {
      if (index <= holdIndex) {
        value = start;
      } else {
        const tailDenom = Math.max(1, rangeEnd - holdIndex);
        const tailProgress = (index - holdIndex) / tailDenom;
        value = start + (end - start) * tailProgress;
      }
    } else if (rule === "s_curve") {
      const k = 10;
      const logistic = 1 / (1 + Math.exp(-k * (progress - 0.5)));
      const normalized = (logistic - 1 / (1 + Math.exp(k / 2))) / ((1 / (1 + Math.exp(-k / 2))) - (1 / (1 + Math.exp(k / 2))));
      value = start + (end - start) * normalized;
    } else if (rule === "copy_forward") {
      value = index === firstIndex ? start : Number(next[orderedYears[index - 1]] ?? start);
    }
    next[yearKey] = clampSeriesValue(value, meta);
  });
  return next;
}

function YearSeriesModal({ title, field, years, onClose, onSave, values, description, step, min, max }) {
  const meta = {
    ...getSeriesFieldMeta(field),
    ...(step != null ? { step } : {}),
    ...(min != null ? { min } : {}),
    ...(max != null ? { max } : {}),
  };
  const [viewMode, setViewMode] = useS("chart");
  const orderedYears = useM(() => (years || []).map((year) => String(year.year)), [years]);
  const [draft, setDraft] = useS(() =>
    Object.fromEntries((years || []).map((year) => [String(year.year), values?.[String(year.year)] ?? year[field] ?? 0]))
  );
  const [generatorRule, setGeneratorRule] = useS("linear");
  const [generatorStart, setGeneratorStart] = useS(() => values?.[orderedYears[0]] ?? years?.[0]?.[field] ?? 0);
  const [generatorEnd, setGeneratorEnd] = useS(() => values?.[orderedYears[orderedYears.length - 1]] ?? years?.[years?.length - 1]?.[field] ?? 0);
  const [holdUntilYear, setHoldUntilYear] = useS(() => orderedYears[Math.max(0, Math.floor((orderedYears.length - 1) / 2))] || "");
  const [percentRate, setPercentRate] = useS(5);
  const [applyStartYear, setApplyStartYear] = useS(() => orderedYears[0] || "");
  const [applyEndYear, setApplyEndYear] = useS(() => orderedYears[orderedYears.length - 1] || "");
  useE(() => {
    const lastYear = years?.[Math.max(0, (years?.length || 1) - 1)];
    const midYear = years?.[Math.max(0, Math.floor(((years?.length || 1) - 1) / 2))];
    setDraft(Object.fromEntries((years || []).map((year) => [String(year.year), values?.[String(year.year)] ?? year[field] ?? 0])));
    setGeneratorStart(values?.[String(years?.[0]?.year)] ?? years?.[0]?.[field] ?? 0);
    setGeneratorEnd(values?.[String(lastYear?.year)] ?? lastYear?.[field] ?? 0);
    setHoldUntilYear(String(midYear?.year ?? ""));
    setApplyStartYear(String(years?.[0]?.year ?? ""));
    setApplyEndYear(String(lastYear?.year ?? ""));
  }, [field, years, values]);
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className="modal-card modal-card-wide" onClick={(event) => event.stopPropagation()}>
        <div className="panel-head">
          <div>
            <div className="eyebrow">Year series editor</div>
            <h2>{title}</h2>
            <p className="muted">{description || "Edit this value across the full scenario period using either a chart or a table."}</p>
          </div>
          <button className="ghost-btn" onClick={onClose}>Close</button>
        </div>
        <div className="series-editor-head">
          <div className="seg">
            <button className={viewMode === "chart" ? "on" : ""} onClick={() => setViewMode("chart")}>Chart</button>
            <button className={viewMode === "table" ? "on" : ""} onClick={() => setViewMode("table")}>Table</button>
          </div>
          <div className="series-editor-meta">
            <span>Field: {meta.label}</span>
            <span>Step: {meta.step}</span>
          </div>
        </div>
        <div className="series-generator">
          <div className="series-generator-head">
            <div>
              <div className="eyebrow">Pathway generator</div>
              <h3>Generate a trajectory, then refine it</h3>
              <p className="muted">Choose a pathway rule to populate the full series. The generated curve stays editable in both chart and table views.</p>
            </div>
            <div className="seg">
              <button className={generatorRule === "linear" ? "on" : ""} onClick={() => setGeneratorRule("linear")}>Linear</button>
              <button className={generatorRule === "step" ? "on" : ""} onClick={() => setGeneratorRule("step")}>Step</button>
              <button className={generatorRule === "percent_decline" ? "on" : ""} onClick={() => setGeneratorRule("percent_decline")}>% decline</button>
              <button className={generatorRule === "hold_then_drop" ? "on" : ""} onClick={() => setGeneratorRule("hold_then_drop")}>Hold then drop</button>
              <button className={generatorRule === "s_curve" ? "on" : ""} onClick={() => setGeneratorRule("s_curve")}>S-curve</button>
            </div>
          </div>
          <div className="series-generator-grid">
            <label>
              <span>Apply from year</span>
              <select value={applyStartYear} onChange={(event) => setApplyStartYear(event.target.value)}>
                {orderedYears.map((year) => <option key={`start-${year}`} value={year}>{year}</option>)}
              </select>
            </label>
            <label>
              <span>Apply to year</span>
              <select value={applyEndYear} onChange={(event) => setApplyEndYear(event.target.value)}>
                {orderedYears.map((year) => <option key={`end-${year}`} value={year}>{year}</option>)}
              </select>
            </label>
            <label>
              <span>Start value</span>
              <input type="number" step={meta.step} min={meta.min} max={meta.max} value={generatorStart} onChange={(event) => setGeneratorStart(Number(event.target.value))} />
            </label>
            <label>
              <span>End value</span>
              <input type="number" step={meta.step} min={meta.min} max={meta.max} value={generatorEnd} onChange={(event) => setGeneratorEnd(Number(event.target.value))} />
            </label>
            {generatorRule === "hold_then_drop" && (
              <label>
                <span>Hold until year</span>
                <select value={holdUntilYear} onChange={(event) => setHoldUntilYear(event.target.value)}>
                  {orderedYears.map((year) => <option key={year} value={year}>{year}</option>)}
                </select>
              </label>
            )}
            {generatorRule === "percent_decline" && (
              <label>
                <span>Decline per step (%)</span>
                <input type="number" step="0.1" min="0" max="100" value={percentRate} onChange={(event) => setPercentRate(Number(event.target.value))} />
              </label>
            )}
          </div>
          <div className="series-generator-actions">
            <button
              className="ghost-btn"
              onClick={() => {
                setDraft(
                  generateSeriesPath({
                    years,
                    draft,
                    meta,
                    rule: generatorRule,
                    startValue: generatorStart,
                    endValue: generatorEnd,
                    holdUntilYear,
                    percentRate,
                    applyStartYear,
                    applyEndYear,
                  })
                );
                setViewMode("chart");
              }}
            >
              Generate pathway
            </button>
            <button
              className="ghost-btn"
              onClick={() => {
                const flatValue = clampSeriesValue(generatorStart, meta);
                setDraft((current) => {
                  const next = { ...current };
                  const startIndex = orderedYears.indexOf(String(applyStartYear));
                  const endIndex = orderedYears.indexOf(String(applyEndYear));
                  const rangeStart = Math.min(startIndex >= 0 ? startIndex : 0, endIndex >= 0 ? endIndex : orderedYears.length - 1);
                  const rangeEnd = Math.max(startIndex >= 0 ? startIndex : 0, endIndex >= 0 ? endIndex : orderedYears.length - 1);
                  orderedYears.forEach((year, index) => {
                    if (index >= rangeStart && index <= rangeEnd) next[year] = flatValue;
                  });
                  return next;
                });
                setViewMode("chart");
              }}
            >
              Copy start value across selected range
            </button>
          </div>
        </div>
        {viewMode === "chart" ? (
          <SeriesTrajectoryEditor years={years} draft={draft} setDraft={setDraft} meta={meta} />
        ) : (
          <div className="pathway-table-wrap">
            <table className="pathway-table">
              <thead>
                <tr><th>Year</th><th>Value</th></tr>
              </thead>
              <tbody>
                {(years || []).map((year) => (
                  <tr key={year.year}>
                    <td>{year.year}</td>
                    <td>
                      <input
                        className="text"
                        type="number"
                        step={meta.step}
                        min={meta.min}
                        max={meta.max}
                        value={draft[String(year.year)]}
                        onChange={(event) => setDraft((current) => ({
                          ...current,
                          [String(year.year)]: Number(event.target.value),
                        }))}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="hero-actions">
          <button className="ghost-btn" onClick={onClose}>Cancel</button>
          <button className="ghost-btn on" onClick={() => { onSave(field, draft); onClose(); }}>Save series</button>
        </div>
      </div>
    </div>
  );
}

function MiniMarket({ year, result }) {
  const W = 280, H = 120;
  const PAD = { t: 10, r: 10, b: 22, l: 30 };
  const iw = W - PAD.l - PAD.r, ih = H - PAD.t - PAD.b;
  const curve = result.demandCurve || [];
  const xMin = year.price_lower_bound ?? 0;
  const xMax = year.price_upper_bound ?? 250;
  const yMax = Math.max(result.Q * 1.4, ...curve.map((point) => point.total), 10);
  const yMin = Math.min(0, ...curve.map((point) => point.total));
  const xs = (p) => PAD.l + ((p - xMin) / (xMax - xMin)) * iw;
  const ys = (a) => PAD.t + ih - ((a - yMin) / (yMax - yMin)) * ih;
  const d = curve.map((point, index) => `${index === 0 ? "M" : "L"}${xs(point.p)},${ys(point.total)}`).join(" ");
  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="mini-chart">
      <line x1={PAD.l} x2={W - PAD.r} y1={H - PAD.b} y2={H - PAD.b} className="axis"/>
      <line x1={PAD.l} x2={PAD.l} y1={PAD.t} y2={H - PAD.b} className="axis"/>
      <line x1={PAD.l} x2={W - PAD.r} y1={ys(result.Q)} y2={ys(result.Q)} className="supply-line"/>
      <path d={d} className="demand-line"/>
      {isFinite(result.price) && (
        <>
          <line x1={xs(result.price)} x2={xs(result.price)} y1={ys(result.Q)} y2={H - PAD.b} className="eq-guide" strokeDasharray="2 2"/>
          <circle cx={xs(result.price)} cy={ys(result.Q)} r="4" className="eq-dot"/>
        </>
      )}
    </svg>
  );
}

function Tweaks({ open, state, setState }) {
  if (!open) return null;
  const set = (patch) => {
    const next = { ...state, ...patch };
    setState(next);
    window.parent?.postMessage({ type: "__edit_mode_set_keys", edits: patch }, "*");
  };
  return (
    <div className="tweaks">
      <div className="tweaks-head">Tweaks</div>
      <label><span>Theme</span>
        <div className="seg">
          <button className={state.dark ? "" : "on"} onClick={() => set({ dark: false })}>Light</button>
          <button className={state.dark ? "on" : ""} onClick={() => set({ dark: true })}>Dark</button>
        </div>
      </label>
      <label><span>Chart style</span>
        <div className="seg">
          {["institutional", "editorial", "terminal"].map((key) => (
            <button key={key} className={state.chartStyle === key ? "on" : ""} onClick={() => set({ chartStyle: key })}>{key}</button>
          ))}
        </div>
      </label>
      <label><span>Density</span>
        <div className="seg">
          {["comfortable", "compact"].map((key) => (
            <button key={key} className={state.density === key ? "on" : ""} onClick={() => set({ density: key })}>{key}</button>
          ))}
        </div>
      </label>
    </div>
  );
}

function TooltipButton({ className, onClick, tooltip, children }) {
  const [visible, setVisible] = useS(false);
  const timerRef = useR(null);
  useE(() => () => clearTimeout(timerRef.current), []);
  const handleEnter = () => { timerRef.current = setTimeout(() => setVisible(true), 2000); };
  const handleLeave = () => { clearTimeout(timerRef.current); setVisible(false); };
  return (
    <div className="tooltip-wrap">
      <button className={className} onClick={onClick} onMouseEnter={handleEnter} onMouseLeave={handleLeave}>
        {children}
      </button>
      {visible && tooltip && <div className="tooltip-box">{tooltip}</div>}
    </div>
  );
}

function slugify(value) {
  return String(value).toLowerCase().replaceAll(" ", "_");
}

export {
  makeBlankParticipant,
  makeBlankYear,
  makeBlankScenario,
  makeBlankSector,
  buildDraftResult,
  configsEqual,
  buildTechnologyPathway,
  describeUnsoldTreatment,
  buildAuctionPathway,
  makeIssue,
  validateMacBlocks,
  validateTechnology,
  validateParticipant,
  validateScenario,
  KPI,
  ValidationPanel,
  AuctionDiagnosticsPanel,
  AuctionPathwayPanel,
  Header,
  ScenarioHero,
  clampSeriesValue,
  generateSeriesPath,
  SeriesTrajectoryEditor,
  YearSeriesModal,
  MiniMarket,
  Tweaks,
  TooltipButton,
  slugify,
  getSeriesFieldMeta,
  valueDiffersFromDefault,
  isYearAttributeConfigured,
  isScenarioFieldConfigured,
  isScenarioSectionConfigured,
  visibleYearAttributeFields,
  };
