import React from "react";
import { fmt } from "./MarketChart.jsx";
import {
  YearSeriesModal,
  getSeriesFieldMeta,
  isYearAttributeConfigured,
  isScenarioFieldConfigured,
  isScenarioSectionConfigured,
} from "./AppShared.jsx";
import { activeFeatureIds, collectSlot, FEATURES } from "../registry.js";
import {
  CollapsibleGroup,
  numInput,
  fieldWithPathButton,
  TrajectoryRangeRow,
} from "./EditorPrimitives.jsx";

// Re-exported for backward compatibility with any existing imports of these
// primitives from Editor.jsx; the implementations live in EditorPrimitives.jsx
// so feature modules (modules/*/frontend) can import them without a
// circular dependency on Editor.jsx (which imports the feature registry).
export { CollapsibleGroup, numInput, fieldWithPathButton, TrajectoryRangeRow };

// Every price-formation approach the backend accepts (mirrors
// ets/blocks/catalogue.py's _MODEL_APPROACHES 5-tuple). The default
// (unscoped) shell only ever showed four of these as clickable buttons —
// "banking" has never had a button, since a scenario only resolves to it by
// loading a template whose config already carries model_approach="banking".
// The pe shell's approach lock (see approachOptionsFor below) is the first
// place "banking" needs a label at all, so it is defined here rather than
// invented inline.
const CANONICAL_APPROACH_OPTIONS = [
  { id: "competitive", label: "Competitive", sub: "Walrasian price-taking equilibrium (default)" },
  { id: "hotelling", label: "Hotelling Rule", sub: "Optimal depletion — price rises at discount rate" },
  { id: "banking", label: "Banking equilibrium", sub: "Intertemporal banking and borrowing with arbitrage-free pricing" },
  { id: "nash_cournot", label: "Nash–Cournot", sub: "Strategic participants with market power" },
  { id: "all", label: "Run All", sub: "Compare all three approaches simultaneously" },
];

// Field lists for the two core "advanced numerical internals" subsections
// under "Modelling approach" (competitive solver tuning, market clearing) —
// see solverSectionVisible / PE_SOLVER_FIELD_DEFAULTS in AppShared.jsx. The
// hotelling / nash_cournot / calibration feature modules define their own
// equivalent lists next to their own solver-tuning blocks.
const COMPETITIVE_SOLVER_FIELDS = [
  "solver_competitive_max_iters",
  "solver_competitive_tolerance",
  "solver_price_bracket_expand_factor",
  "solver_price_bracket_max_expansions",
  "solver_slsqp_max_iters",
  "solver_slsqp_ftol",
];
const MARKET_CLEARING_FIELDS = ["solver_penalty_price_multiplier"];

const ALL_EXPANSION_IDS = ["competitive", "hotelling", "nash_cournot"];

function isAllApproachExpansion(approachIds) {
  const set = new Set(approachIds);
  return set.size === ALL_EXPANSION_IDS.length && ALL_EXPANSION_IDS.every((id) => set.has(id));
}

// The pe shell passes down the selected model's manifest approach list
// (see frontend/src/pe/PeApp.jsx); the default shell passes null, which
// must reproduce today's four-button grid byte-for-byte (never offering
// "banking" as a button — see comment above).
function approachOptionsFor(approachScope) {
  if (approachScope == null) {
    return CANONICAL_APPROACH_OPTIONS.filter((opt) => opt.id !== "banking");
  }
  return CANONICAL_APPROACH_OPTIONS.filter(
    (opt) => approachScope.includes(opt.id) || (opt.id === "all" && isAllApproachExpansion(approachScope))
  );
}

export function Editor({
  scenario,
  year,
  onSave,
  onAddYear,
  onRemoveYear,
  onSelectYear,
  navigationTarget = null,
  enabledFeatures = null,
  manifest = null,
  // "Show advanced settings" — owned by BuildView (frontend/src/components/
  // AppViews.jsx), shared with the "Market timeline" metric list above this
  // editor so both surfaces respond to the same one switch. Only meaningful
  // in pe mode (see peMode below); the unscoped (default) shell ignores it —
  // solver tuning and every optional field stay unconditionally visible,
  // byte-identical to today.
  showAdvanced = false,
}) {
  const activeFeatures = activeFeatureIds(enabledFeatures);
  const isFeatureActive = (id) => activeFeatures.includes(id);
  // pe mode = a manifest-scoped shell (see frontend/src/pe/PeApp.jsx). Config-
  // driven field visibility (see AppShared.jsx's isYearAttributeConfigured /
  // isScenarioFieldConfigured) only applies here — the unscoped (default)
  // shell always shows every optional field, unchanged.
  const peMode = enabledFeatures != null;
  // A year-level optional field (Total cap, Price ceiling, Borrowing limit,
  // ...) is visible if the toggle is on, or if ANY year in this scenario's
  // working draft already sets it away from its backend default — the same
  // any-year-deviates rule ets/blocks/decompile.py uses to decide whether a
  // block (and therefore a feature) is "in play" for a config. Default shell:
  // always true.
  const yearFieldVisible = (field) =>
    !peMode || showAdvanced || isYearAttributeConfigured(workingScenario.years, field);
  // A scenario-level optional field (a single solver-tuning knob) is visible
  // under the same rule, compared against its own value instead of an
  // across-years OR.
  const scenarioFieldVisible = (field) =>
    !peMode || showAdvanced || isScenarioFieldConfigured(workingScenario, field);
  // A whole "Solver tuning"-style subsection is visible if the toggle is on,
  // or if any field inside it deviates from default (a model that ships
  // custom solver settings must not hide them silently). Default shell:
  // always true — these blocks are unconditional numerical internals today.
  const solverSectionVisible = (fields) =>
    !peMode || showAdvanced || isScenarioSectionConfigured(workingScenario, fields);
  // Manifest-driven approach lock (pe shell only — see approachOptionsFor
  // above). Prefer the active scenario's own breakdown when the manifest
  // has one (manifest.scenarios[name].approach — more precise for a
  // multi-scenario config where scenarios use different approaches),
  // falling back to the whole-config approach list for a scenario the
  // manifest doesn't know about yet (e.g. one added via "Add scenario"
  // after selecting the model in the pe shell).
  const approachScope = manifest
    ? manifest.scenarios?.[scenario.name]?.approach ?? manifest.approach ?? null
    : null;
  const visibleApproachOptions = approachOptionsFor(approachScope);
  // "Banking, borrowing & expectations" is core UI (no banking-specific
  // editor section exists — see modules/banking/frontend/index.jsx), so it is not
  // gated through the feature-slot mechanism. It stays visible whenever the
  // banking feature is in play OR the loaded config already turned banking
  // or borrowing on for some year — matching the same OR the backend uses
  // (banking_allowed/borrowing_allowed are meaningful on their own, not
  // only under model_approach="banking"). Unrestricted (default) shell
  // always shows it, unchanged.
  const bankingGroupVisible =
    enabledFeatures == null ||
    isFeatureActive("banking") ||
    (scenario.years || []).some((item) => item?.banking_allowed || item?.borrowing_allowed);
  const [workingScenario, setWorkingScenario] = React.useState(() => structuredClone(scenario));
  const [workingYear, setWorkingYear] = React.useState(() => structuredClone(year));
  const [activeStep, setActiveStep] = React.useState("scenario");
  const [selectedParticipantIndex, setSelectedParticipantIndex] = React.useState(0);
  const [selectedTechnologyIndex, setSelectedTechnologyIndex] = React.useState(0);
  const [selectedParticipantTemplate, setSelectedParticipantTemplate] = React.useState("steel_blast_furnace");
  const [wizardOpen, setWizardOpen] = React.useState(false);
  const [wizardArchetype, setWizardArchetype] = React.useState("auto");
  const [wizardReplacements, setWizardReplacements] = React.useState([]);
  const [wizardMode, setWizardMode] = React.useState("moderate");
  const [seriesEditor, setSeriesEditor] = React.useState(null);
  const participant = workingYear.participants?.[selectedParticipantIndex] || null;
  const technologyOptions = participant?.technology_options || [];
  const selectedTechnology = technologyOptions[selectedTechnologyIndex] || null;
  const participantNameLower = participant?.name?.toLowerCase() || "";

  React.useEffect(() => {
    setWorkingScenario(structuredClone(scenario));
    setWorkingYear(structuredClone(year));
    setSelectedParticipantIndex(0);
    setSelectedTechnologyIndex(0);
    setWizardOpen(false);
  }, [scenario.id, year.year]);

  React.useEffect(() => {
    if (selectedParticipantIndex >= (workingYear.participants || []).length) {
      setSelectedParticipantIndex(Math.max(0, (workingYear.participants || []).length - 1));
    }
  }, [workingYear.participants, selectedParticipantIndex]);

  React.useEffect(() => {
    const options = workingYear.participants?.[selectedParticipantIndex]?.technology_options || [];
    if (selectedTechnologyIndex >= options.length) {
      setSelectedTechnologyIndex(Math.max(0, options.length - 1));
    }
  }, [workingYear.participants, selectedParticipantIndex, selectedTechnologyIndex]);

  React.useEffect(() => {
    if (!participant) return;
    const autoArchetype =
      participant?.sector === "Power" && participantNameLower.includes("coal")
        ? "coal_transition"
        : participant?.sector === "Industry" && participantNameLower.includes("steel")
          ? "steel_transition"
          : participant?.sector === "Industry" && participantNameLower.includes("cement")
            ? "cement_transition"
            : participant?.sector === "Industry"
              ? "generic_industry"
              : "auto";
    setWizardArchetype(autoArchetype);
  }, [selectedParticipantIndex, participant?.sector, participantNameLower]);

  React.useEffect(() => {
    const allowed = wizardArchetypes[wizardArchetype]?.replacements || [];
    if (!allowed.length) {
      setWizardReplacements([]);
      return;
    }
    setWizardReplacements((current) => {
      const filtered = current.filter((item) => allowed.includes(item));
      return filtered.length ? filtered : [allowed[0]];
    });
  }, [wizardArchetype]);

  React.useEffect(() => {
    if (!navigationTarget) return;
    if (navigationTarget.step) {
      setActiveStep(navigationTarget.step);
    }
    if (navigationTarget.participantName) {
      const participantIndex = (workingYear.participants || []).findIndex(
        (item) => item.name === navigationTarget.participantName
      );
      if (participantIndex >= 0) {
        setSelectedParticipantIndex(participantIndex);
        const technologyName = navigationTarget.technologyName;
        if (technologyName) {
          const technologyIndex = (workingYear.participants?.[participantIndex]?.technology_options || []).findIndex(
            (item) => item.name === technologyName
          );
          if (technologyIndex >= 0) {
            setSelectedTechnologyIndex(technologyIndex);
          }
        }
      }
    }
  }, [navigationTarget, workingYear.participants]);

  const isDirty =
    JSON.stringify(workingScenario) !== JSON.stringify(scenario)
    || JSON.stringify(workingYear) !== JSON.stringify(year);

  const stepItems = [
    { id: "scenario", label: "1. Scenario" },
    { id: "market", label: "2. Market Rules" },
    { id: "participants", label: "3. Participants" },
    { id: "review", label: "4. Review" },
  ];

  const fieldHelp = {
    abatement_type: "Choose the participant abatement model: linear, threshold, or piecewise MAC blocks.",
    max_abatement: "Maximum abatement volume available to this participant.",
    cost_slope: "Used only for linear abatement. Lower slope means cheaper marginal abatement.",
    threshold_cost: "Used only for threshold abatement. Abatement activates when carbon price reaches this cost.",
    mac_blocks: "Used only for piecewise abatement. Enter blocks as amount@cost; amount@cost.",
    fixed_cost: "Fixed annual technology cost paid if this technology option is chosen.",
  };

  const scenarioYearsWithDraft = React.useMemo(
    () =>
      (workingScenario.years || []).map((item) =>
        String(item.year) === String(year.year) ? structuredClone(workingYear) : item
      ),
    [workingScenario.years, workingYear, year.year]
  );

  const wizardArchetypes = {
    auto: {
      label: "Auto detect",
      replacements: ["hydrogen_dri", "ccs_retrofit"],
      description: "Choose replacements based on the selected participant name and sector.",
    },
    steel_transition: {
      label: "Steel transition",
      replacements: ["hydrogen_dri", "scrap_eaf", "ccs_retrofit"],
      description: "Incumbent steel route moving toward hydrogen DRI, EAF, or CCS retrofit.",
    },
    coal_transition: {
      label: "Coal power transition",
      replacements: ["renewables_storage", "gas_ccs", "ccs_retrofit"],
      description: "Coal fleet moving toward renewables plus storage, gas with CCS, or retrofit.",
    },
    cement_transition: {
      label: "Cement transition",
      replacements: ["ccs_retrofit", "clinker_substitution"],
      description: "Cement kiln moving toward CCS retrofit or clinker substitution.",
    },
    generic_industry: {
      label: "Generic industry retrofit",
      replacements: ["ccs_retrofit", "electrification"],
      description: "Generic industrial asset moving toward low-carbon retrofit options.",
    },
  };

  const replacementCatalog = {
    hydrogen_dri: {
      label: "Hydrogen DRI",
      emissionsMultiplier: 0.42,
      freeRatioMultiplier: 0.8,
      fixedCostMultiplier: 1.1,
      blockCostMultiplier: 0.58,
      blockAmountMultiplier: 1.15,
    },
    scrap_eaf: {
      label: "Scrap EAF",
      emissionsMultiplier: 0.3,
      freeRatioMultiplier: 0.7,
      fixedCostMultiplier: 0.95,
      blockCostMultiplier: 0.52,
      blockAmountMultiplier: 1.1,
    },
    renewables_storage: {
      label: "Renewables + Storage",
      emissionsMultiplier: 0.12,
      freeRatioMultiplier: 0.35,
      fixedCostMultiplier: 0.7,
      blockCostMultiplier: 0.45,
      blockAmountMultiplier: 1.25,
    },
    gas_ccs: {
      label: "Gas + CCS",
      emissionsMultiplier: 0.38,
      freeRatioMultiplier: 0.7,
      fixedCostMultiplier: 0.85,
      blockCostMultiplier: 0.62,
      blockAmountMultiplier: 1.05,
    },
    ccs_retrofit: {
      label: "CCS Retrofit",
      emissionsMultiplier: 0.55,
      freeRatioMultiplier: 0.85,
      fixedCostMultiplier: 0.9,
      blockCostMultiplier: 0.7,
      blockAmountMultiplier: 1.05,
    },
    clinker_substitution: {
      label: "Clinker Substitution",
      emissionsMultiplier: 0.68,
      freeRatioMultiplier: 0.85,
      fixedCostMultiplier: 0.55,
      blockCostMultiplier: 0.72,
      blockAmountMultiplier: 0.95,
    },
    electrification: {
      label: "Electrification",
      emissionsMultiplier: 0.48,
      freeRatioMultiplier: 0.75,
      fixedCostMultiplier: 0.8,
      blockCostMultiplier: 0.6,
      blockAmountMultiplier: 1.1,
    },
  };

  const wizardModeConfig = {
    conservative: { emissions: 1.05, fixedCost: 1.15, blockCost: 1.1, blockAmount: 0.95 },
    moderate: { emissions: 1.0, fixedCost: 1.0, blockCost: 1.0, blockAmount: 1.0 },
    aggressive: { emissions: 0.92, fixedCost: 0.9, blockCost: 0.9, blockAmount: 1.08 },
  };

  const participantTemplates = {
    steel_blast_furnace: {
      name: "Steel Blast Furnace",
      sector: "Industry",
      initial_emissions: 100,
      free_allocation_ratio: 0.9,
      penalty_price: Math.max(250, workingYear.price_upper_bound || 100),
      abatement_type: "piecewise",
      max_abatement: 22,
      cost_slope: 1,
      threshold_cost: 0,
      mac_blocks: [
        { amount: 6, marginal_cost: 20 },
        { amount: 8, marginal_cost: 55 },
        { amount: 8, marginal_cost: 110 },
      ],
      technology_options: [],
    },
    steel_hydrogen_dri: {
      name: "Steel Hydrogen DRI",
      sector: "Industry",
      initial_emissions: 70,
      free_allocation_ratio: 0.65,
      penalty_price: Math.max(250, workingYear.price_upper_bound || 100),
      abatement_type: "piecewise",
      max_abatement: 26,
      cost_slope: 1,
      threshold_cost: 0,
      mac_blocks: [
        { amount: 8, marginal_cost: 15 },
        { amount: 10, marginal_cost: 35 },
        { amount: 8, marginal_cost: 70 },
      ],
      technology_options: [],
    },
    coal_generator: {
      name: "Coal Generator",
      sector: "Power",
      initial_emissions: 140,
      free_allocation_ratio: 0.25,
      penalty_price: Math.max(250, workingYear.price_upper_bound || 100),
      abatement_type: "piecewise",
      max_abatement: 40,
      cost_slope: 1,
      threshold_cost: 0,
      mac_blocks: [
        { amount: 8, marginal_cost: 25 },
        { amount: 12, marginal_cost: 50 },
        { amount: 20, marginal_cost: 95 },
      ],
      technology_options: [],
    },
    renewable_generator: {
      name: "Renewable Generator",
      sector: "Power",
      initial_emissions: 5,
      free_allocation_ratio: 0,
      penalty_price: Math.max(250, workingYear.price_upper_bound || 100),
      abatement_type: "piecewise",
      max_abatement: 4,
      cost_slope: 1,
      threshold_cost: 0,
      mac_blocks: [
        { amount: 2, marginal_cost: 5 },
        { amount: 2, marginal_cost: 12 },
      ],
      technology_options: [],
    },
    cement_kiln: {
      name: "Cement Kiln",
      sector: "Industry",
      initial_emissions: 85,
      free_allocation_ratio: 0.75,
      penalty_price: Math.max(250, workingYear.price_upper_bound || 100),
      abatement_type: "piecewise",
      max_abatement: 24,
      cost_slope: 1,
      threshold_cost: 0,
      mac_blocks: [
        { amount: 5, marginal_cost: 18 },
        { amount: 7, marginal_cost: 48 },
        { amount: 12, marginal_cost: 115 },
      ],
      technology_options: [],
    },
  };

  const blankParticipant = (index) => ({
    name: `Participant ${index}`,
    sector: "Other",
    initial_emissions: 0,
    free_allocation_ratio: 0,
    penalty_price: workingYear.price_upper_bound || 100,
    abatement_type: "linear",
    max_abatement: 0,
    cost_slope: 1,
    threshold_cost: 0,
    mac_blocks: [],
    technology_options: [],
  });

  const blankTechnologyOption = (index) => ({
    name: `Technology ${index}`,
    initial_emissions: participant?.initial_emissions || 0,
    free_allocation_ratio: participant?.free_allocation_ratio || 0,
    penalty_price: participant?.penalty_price || workingYear.price_upper_bound || 100,
    abatement_type: participant?.abatement_type || "linear",
    max_abatement: participant?.max_abatement || 0,
    cost_slope: participant?.cost_slope || 1,
    threshold_cost: participant?.threshold_cost || 0,
    mac_blocks: [],
    fixed_cost: 0,
    max_activity_share: 1,
  });

  const serializeMacBlocks = (item) =>
    (item?.mac_blocks || [])
      .map((block) => `${block.amount}@${block.marginal_cost}`)
      .join("; ");

  const parseMacBlocks = (rawValue) => {
    const trimmed = rawValue.trim();
    if (!trimmed) return [];
    return trimmed
      .split(";")
      .map((item) => {
        const [amountText, costText] = item.split("@").map((value) => value.trim());
        return {
          amount: Number(amountText || 0),
          marginal_cost: Number(costText || 0),
        };
      })
      .filter((block) => !Number.isNaN(block.amount) && !Number.isNaN(block.marginal_cost));
  };

  const updateScenario = (patch) => setWorkingScenario((current) => ({ ...current, ...patch }));
  const updateYear = (patch) => setWorkingYear((current) => ({ ...current, ...patch }));

  const updateParticipants = (participants) => setWorkingYear((current) => ({ ...current, participants }));

  const syncScenarioYearDraft = (nextYearDraft) => {
    setWorkingScenario((current) => ({
      ...current,
      years: (current.years || []).map((item) =>
        String(item.year) === String(year.year) ? structuredClone(nextYearDraft) : item
      ),
    }));
  };

  const updateParticipant = (index, patch) => {
    const participants = (workingYear.participants || []).map((item, rowIndex) =>
      rowIndex === index ? { ...item, ...patch } : item
    );
    updateParticipants(participants);
  };

  const updateTechnologyOption = (participantIndex, technologyIndex, patch) => {
    const participants = (workingYear.participants || []).map((item, rowIndex) => {
      if (rowIndex !== participantIndex) return item;
      const nextOptions = (item.technology_options || []).map((option, optionIndex) =>
        optionIndex === technologyIndex ? { ...option, ...patch } : option
      );
      return { ...item, technology_options: nextOptions };
    });
    updateParticipants(participants);
  };

  const updateMacBlocks = (record, onPatch, updater) => {
    const nextBlocks = updater([...(record?.mac_blocks || [])]).map((block) => ({
      amount: Number(block.amount || 0),
      marginal_cost: Number(block.marginal_cost || 0),
    }));
    onPatch({
      mac_blocks: nextBlocks,
      max_abatement: nextBlocks.length
        ? nextBlocks.reduce((sum, block) => sum + Number(block.amount || 0), 0)
        : record.max_abatement || 0,
    });
  };

  const applyParticipantTemplate = (templateKey, mode = "add") => {
    const template = participantTemplates[templateKey];
    if (!template) return;
    const nextRecord = structuredClone(template);
    if (mode === "replace" && participant) {
      updateParticipant(selectedParticipantIndex, {
        ...nextRecord,
        technology_options: participant.technology_options || nextRecord.technology_options,
      });
      return;
    }
    const participants = [...(workingYear.participants || []), nextRecord];
    updateParticipants(participants);
    setSelectedParticipantIndex(participants.length - 1);
    setSelectedTechnologyIndex(0);
    setActiveStep("participants");
  };

  const addParticipant = () => {
    const nextIndex = (workingYear.participants || []).length + 1;
    const participants = [...(workingYear.participants || []), blankParticipant(nextIndex)];
    updateParticipants(participants);
    setSelectedParticipantIndex(participants.length - 1);
    setSelectedTechnologyIndex(0);
    setActiveStep("participants");
  };

  const duplicateParticipant = (index) => {
    const source = workingYear.participants?.[index];
    if (!source) return;
    const participants = [...(workingYear.participants || [])];
    participants.splice(index + 1, 0, {
      ...structuredClone(source),
      name: `${source.name} Copy`,
    });
    updateParticipants(participants);
    setSelectedParticipantIndex(index + 1);
  };

  const removeParticipant = (index) => {
    const participants = (workingYear.participants || []).filter((_, rowIndex) => rowIndex !== index);
    updateParticipants(participants);
  };

  const addTechnologyOption = (participantIndex) => {
    const participantRecord = workingYear.participants?.[participantIndex];
    if (!participantRecord) return;
    const nextOptionIndex = (participantRecord.technology_options || []).length + 1;
    const participants = (workingYear.participants || []).map((item, rowIndex) => {
      if (rowIndex !== participantIndex) return item;
      return {
        ...item,
        technology_options: [...(item.technology_options || []), blankTechnologyOption(nextOptionIndex)],
      };
    });
    updateParticipants(participants);
    setSelectedTechnologyIndex(nextOptionIndex - 1);
  };

  const removeTechnologyOption = (participantIndex, technologyIndex) => {
    const participants = (workingYear.participants || []).map((item, rowIndex) => {
      if (rowIndex !== participantIndex) return item;
      return {
        ...item,
        technology_options: (item.technology_options || []).filter((_, optionIndex) => optionIndex !== technologyIndex),
      };
    });
    updateParticipants(participants);
    setSelectedTechnologyIndex(0);
  };

  const buildTechnologyPathway = (participantIndex) => {
    const source = workingYear.participants?.[participantIndex];
    if (!source) return;
    const incumbentName = source.name || `Participant ${participantIndex + 1}`;
    const lowCarbonName =
      source.sector === "Power"
        ? "Renewables + Storage"
        : source.name?.toLowerCase().includes("steel")
          ? "Hydrogen DRI"
          : "Low-Carbon Retrofit";
    const incumbent = {
      name: `${incumbentName} Incumbent`,
      initial_emissions: Number(source.initial_emissions || 0),
      free_allocation_ratio: Number(source.free_allocation_ratio || 0),
      penalty_price: Number(source.penalty_price || workingYear.price_upper_bound || 100),
      abatement_type: source.abatement_type || "piecewise",
      max_abatement: Number(source.max_abatement || 0),
      cost_slope: Number(source.cost_slope || 1),
      threshold_cost: Number(source.threshold_cost || 0),
      mac_blocks: structuredClone(source.mac_blocks || []),
      fixed_cost: 0,
    };
    const lowCarbonBlocks = source.abatement_type === "piecewise" && (source.mac_blocks || []).length
      ? source.mac_blocks.map((block, index) => ({
          amount: Math.max(1, Math.round(Number(block.amount || 0) * (index === 0 ? 1.1 : 1.2))),
          marginal_cost: Math.max(1, Math.round(Number(block.marginal_cost || 0) * 0.65)),
        }))
      : [
          { amount: Math.max(1, Math.round(Number(source.max_abatement || 0) * 0.4)), marginal_cost: 15 },
          { amount: Math.max(1, Math.round(Number(source.max_abatement || 0) * 0.6)), marginal_cost: 40 },
        ];
    const lowCarbon = {
      name: lowCarbonName,
      initial_emissions: Math.max(0, Number(source.initial_emissions || 0) * (source.sector === "Power" ? 0.15 : 0.55)),
      free_allocation_ratio: Math.max(0, Number(source.free_allocation_ratio || 0) * 0.8),
      penalty_price: Number(source.penalty_price || workingYear.price_upper_bound || 100),
      abatement_type: "piecewise",
      max_abatement: lowCarbonBlocks.reduce((sum, block) => sum + Number(block.amount || 0), 0),
      cost_slope: 1,
      threshold_cost: 0,
      mac_blocks: lowCarbonBlocks,
      fixed_cost: Math.max(25, Math.round(Number(source.initial_emissions || 0) * (source.sector === "Power" ? 0.45 : 0.85))),
      max_activity_share: 1,
    };
    updateParticipant(participantIndex, { technology_options: [incumbent, lowCarbon] });
    setSelectedTechnologyIndex(1);
  };

  const toggleWizardReplacement = (replacementId) => {
    setWizardReplacements((current) =>
      current.includes(replacementId)
        ? current.filter((item) => item !== replacementId)
        : [...current, replacementId]
    );
  };

  const deriveBlocksForReplacement = (source, replacementId) => {
    const replacement = replacementCatalog[replacementId];
    const mode = wizardModeConfig[wizardMode];
    const sourceBlocks = source?.mac_blocks?.length
      ? source.mac_blocks
      : [
          { amount: Math.max(1, Math.round(Number(source?.max_abatement || 10) * 0.35)), marginal_cost: 20 },
          { amount: Math.max(1, Math.round(Number(source?.max_abatement || 10) * 0.65)), marginal_cost: 60 },
        ];
    return sourceBlocks.map((block) => ({
      amount: Math.max(1, Math.round(Number(block.amount || 0) * replacement.blockAmountMultiplier * mode.blockAmount)),
      marginal_cost: Math.max(1, Math.round(Number(block.marginal_cost || 0) * replacement.blockCostMultiplier * mode.blockCost)),
    }));
  };

  const buildWizardPreview = () => {
    if (!participant) return [];
    const baseName = participant.name || `Participant ${selectedParticipantIndex + 1}`;
    const mode = wizardModeConfig[wizardMode];
    const incumbent = {
      name: `${baseName} Incumbent`,
      initial_emissions: Number(participant.initial_emissions || 0),
      free_allocation_ratio: Number(participant.free_allocation_ratio || 0),
      penalty_price: Number(participant.penalty_price || workingYear.price_upper_bound || 100),
      abatement_type: participant.abatement_type || "piecewise",
      max_abatement: Number(participant.max_abatement || 0),
      cost_slope: Number(participant.cost_slope || 1),
      threshold_cost: Number(participant.threshold_cost || 0),
      mac_blocks: structuredClone(participant.mac_blocks || []),
      fixed_cost: 0,
      max_activity_share: 1,
    };
    const lowCarbonOptions = wizardReplacements
      .map((replacementId) => {
        const replacement = replacementCatalog[replacementId];
        if (!replacement) return null;
        const macBlocks = deriveBlocksForReplacement(participant, replacementId);
        return {
          name: replacement.label,
          initial_emissions: Math.max(
            0,
            Number(participant.initial_emissions || 0) * replacement.emissionsMultiplier * mode.emissions
          ),
          free_allocation_ratio: Math.max(
            0,
            Math.min(1, Number(participant.free_allocation_ratio || 0) * replacement.freeRatioMultiplier)
          ),
          penalty_price: Number(participant.penalty_price || workingYear.price_upper_bound || 100),
          abatement_type: "piecewise",
          max_abatement: macBlocks.reduce((sum, block) => sum + Number(block.amount || 0), 0),
          cost_slope: 1,
          threshold_cost: 0,
          mac_blocks: macBlocks,
          fixed_cost: Math.max(
            10,
            Math.round(Number(participant.initial_emissions || 0) * replacement.fixedCostMultiplier * mode.fixedCost)
          ),
          max_activity_share: 1,
        };
      })
      .filter(Boolean);
    return [incumbent, ...lowCarbonOptions];
  };

  const applyWizardPathway = () => {
    if (!participant) return;
    const preview = buildWizardPreview();
    updateParticipant(selectedParticipantIndex, { technology_options: preview });
    setSelectedTechnologyIndex(Math.min(1, Math.max(0, preview.length - 1)));
    setWizardOpen(false);
  };

  const renderMacBlockEditor = (record, onPatch, prefix = "") => {
    const blocks = record?.mac_blocks || [];
    return (
      <div className="builder-mac">
        <div className="builder-card-subhead compact">
          <div>
            <div className="eyebrow">Visual MAC blocks</div>
            <div className="muted">Add abatement blocks as tonnage and marginal cost steps.</div>
          </div>
          <div className="editor-actions">
            <button
              className="ghost-btn"
              type="button"
              onClick={() => updateMacBlocks(record, onPatch, (items) => [...items, { amount: 5, marginal_cost: 20 }])}
            >
              Add block
            </button>
            <button
              className="ghost-btn"
              type="button"
              onClick={() =>
                updateMacBlocks(record, onPatch, () => [
                  { amount: 5, marginal_cost: 15 },
                  { amount: 8, marginal_cost: 35 },
                  { amount: 10, marginal_cost: 75 },
                ])
              }
            >
              Load starter
            </button>
          </div>
        </div>
        {blocks.length ? (
          <div className="builder-mac-table">
            <div className="builder-mac-head">
              <span>Block</span>
              <span>Amount</span>
              <span>Marginal cost</span>
              <span></span>
            </div>
            {blocks.map((block, index) => (
              <div key={`${prefix}mac-${index}`} className="builder-mac-row">
                <span className="builder-mac-index">{index + 1}</span>
                {numInput(
                  block.amount || 0,
                  (value) =>
                    updateMacBlocks(record, onPatch, (items) =>
                      items.map((item, itemIndex) => itemIndex === index ? { ...item, amount: value } : item)
                    ),
                  1,
                  0
                )}
                {numInput(
                  block.marginal_cost || 0,
                  (value) =>
                    updateMacBlocks(record, onPatch, (items) =>
                      items.map((item, itemIndex) => itemIndex === index ? { ...item, marginal_cost: value } : item)
                    ),
                  1,
                  0
                )}
                <button
                  className="ghost-btn danger-btn"
                  type="button"
                  onClick={() => updateMacBlocks(record, onPatch, (items) => items.filter((_, itemIndex) => itemIndex !== index))}
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        ) : (
          <div className="builder-empty">No MAC blocks yet. Add a block or load a starter profile.</div>
        )}
        <label className="builder-span-2">
          <span className="ekey">{prefix}MAC blocks raw</span>
          <input
            className="text"
            value={serializeMacBlocks(record)}
            onChange={(event) => onPatch({ mac_blocks: parseMacBlocks(event.target.value) })}
            placeholder="6@20; 8@55; 8@110"
            title={fieldHelp.mac_blocks}
          />
        </label>
      </div>
    );
  };

  const renderAbatementFields = (record, onPatch, prefix = "") => (
    <div className="builder-form-grid">
      <label>
        <span className="ekey">{prefix}Abatement type</span>
        <select
          value={record.abatement_type || "linear"}
          onChange={(event) => onPatch({ abatement_type: event.target.value })}
          title={fieldHelp.abatement_type}
        >
          <option value="linear">linear</option>
          <option value="threshold">threshold</option>
          <option value="piecewise">piecewise</option>
        </select>
      </label>
      <label>
        <span className="ekey">{prefix}Max abate</span>
        {numInput(record.max_abatement || 0, (value) => onPatch({ max_abatement: value }), 1, 0, fieldHelp.max_abatement)}
      </label>
      <label>
        <span className="ekey">{prefix}Cost slope</span>
        {numInput(record.cost_slope || 0, (value) => onPatch({ cost_slope: value }), 0.1, 0, fieldHelp.cost_slope)}
      </label>
      <label>
        <span className="ekey">{prefix}Threshold cost</span>
        {numInput(record.threshold_cost || 0, (value) => onPatch({ threshold_cost: value }), 0.1, 0, fieldHelp.threshold_cost)}
      </label>
      <label className="builder-span-2">
        <span className="ekey">{prefix}MAC block editor</span>
        {renderMacBlockEditor(record, onPatch, prefix)}
      </label>
    </div>
  );

  const openMarketSeriesEditor = (field) => {
    setSeriesEditor({
      type: "market",
      title: getSeriesFieldMeta(field).label,
      field,
      values: Object.fromEntries(
        scenarioYearsWithDraft.map((item) => [String(item.year), Number(item[field] ?? 0)])
      ),
      description: "Edit this market-rule trajectory across all scenario years using a chart or the table.",
    });
  };

  const openParticipantSeriesEditor = (field) => {
    if (!participant) return;
    setSeriesEditor({
      type: "participant",
      title: `${participant.name || "Participant"} · ${getSeriesFieldMeta(field).label}`,
      field,
      values: Object.fromEntries(
        scenarioYearsWithDraft.map((item) => [
          String(item.year),
          Number(item.participants?.[selectedParticipantIndex]?.[field] ?? 0),
        ])
      ),
      description: "Edit the selected participant across all years. The same participant index is updated year by year.",
      participantIndex: selectedParticipantIndex,
    });
  };

  const openTechnologySeriesEditor = (field) => {
    if (!selectedTechnology) return;
    setSeriesEditor({
      type: "technology",
      title: `${selectedTechnology.name || "Technology"} · ${getSeriesFieldMeta(field).label}`,
      field,
      values: Object.fromEntries(
        scenarioYearsWithDraft.map((item) => [
          String(item.year),
          Number(item.participants?.[selectedParticipantIndex]?.technology_options?.[selectedTechnologyIndex]?.[field] ?? 0),
        ])
      ),
      description: "Edit this technology option across all years. The selected participant and technology index are updated year by year.",
      participantIndex: selectedParticipantIndex,
      technologyIndex: selectedTechnologyIndex,
    });
  };

  const applySeriesEdit = (field, valuesByYear) => {
    setWorkingScenario((current) => {
      const nextYears = scenarioYearsWithDraft.map((item) => {
        const yearKey = String(item.year);
        const nextValue = valuesByYear[yearKey];
        if (seriesEditor?.type === "market") {
          return { ...item, [field]: nextValue ?? item[field] };
        }
        if (seriesEditor?.type === "participant") {
          const participants = (item.participants || []).map((entry, index) =>
            index === seriesEditor.participantIndex ? { ...entry, [field]: nextValue ?? entry[field] } : entry
          );
          return { ...item, participants };
        }
        if (seriesEditor?.type === "technology") {
          const participants = (item.participants || []).map((entry, index) => {
            if (index !== seriesEditor.participantIndex) return entry;
            const technologyOptions = (entry.technology_options || []).map((option, optionIndex) =>
              optionIndex === seriesEditor.technologyIndex ? { ...option, [field]: nextValue ?? option[field] } : option
            );
            return { ...entry, technology_options: technologyOptions };
          });
          return { ...item, participants };
        }
        return item;
      });
      const currentYearDraft = nextYears.find((item) => String(item.year) === String(workingYear.year)) || workingYear;
      setWorkingYear(structuredClone(currentYearDraft));
      return { ...current, years: nextYears };
    });
  };

  // Context objects handed to feature-module editor slots (see
  // modules/*/frontend). Feature components read/write through these
  // rather than reaching into Editor's closure directly. `activeFeatures`
  // is included so a feature component that embeds ANOTHER feature's field
  // inline (e.g. hotelling embedding elastic_baseline's reference-carbon
  // price at its original DOM position) can self-gate on that feature's
  // enablement too, not just its own.
  const scenarioCtx = {
    scenario,
    workingScenario,
    updateScenario,
    workingYear,
    updateYear,
    openMarketSeriesEditor,
    activeFeatures,
    peMode,
    showAdvanced,
    yearFieldVisible,
    scenarioFieldVisible,
    solverSectionVisible,
  };
  const participantCtx = {
    workingScenario,
    workingYear,
    participant,
    selectedParticipantIndex,
    updateParticipant,
    openParticipantSeriesEditor,
    activeFeatures,
    peMode,
    showAdvanced,
  };
  // Technology-scoped sibling of participantCtx — for feature modules whose
  // editor UI is per-(participant, technology) rather than per-participant
  // (today: endogenous_investment's investment_trigger sub-form). Rendered
  // at the technology editor, not the participant "Allocation" grid.
  const technologyCtx = {
    workingScenario,
    workingYear,
    participant,
    selectedParticipantIndex,
    technology: selectedTechnology,
    selectedTechnologyIndex,
    updateTechnologyOption,
    activeFeatures,
    peMode,
    showAdvanced,
  };

  return (
    <div className="editor builder">
      <div className="editor-toolbar">
        <div>
          <div className="eyebrow">Scenario builder</div>
          <h3>Build {workingScenario.name} step by step</h3>
        </div>
        <div className="editor-actions">
          <button
            className="ghost-btn"
            type="button"
            onClick={() => {
              setWorkingScenario(structuredClone(scenario));
              setWorkingYear(structuredClone(year));
            }}
            disabled={!isDirty}
          >
            Discard changes
          </button>
          <button
            className={"ghost-btn on " + (isDirty ? "edited-btn" : "")}
            type="button"
            onClick={() => onSave?.(workingScenario, workingYear, String(year.year))}
            disabled={!isDirty}
          >
            Save changes
          </button>
          <button className="ghost-btn" type="button" onClick={onAddYear}>Add year</button>
          <button
            className="ghost-btn"
            type="button"
            onClick={onRemoveYear}
            disabled={(workingScenario.years || []).length <= 1}
          >
            Remove year
          </button>
          <button className="ghost-btn on" type="button" onClick={addParticipant}>Add participant</button>
        </div>
      </div>

      <div className="builder-steps">
        {stepItems.map((step) => (
          <button
            key={step.id}
            type="button"
            className={"builder-step " + (activeStep === step.id ? "on" : "")}
            onClick={() => setActiveStep(step.id)}
          >
            {step.label}
          </button>
        ))}
      </div>

      {activeStep === "scenario" && (
        <section className="editor-section">
          <div className="editor-section-title">Scenario definition</div>
          <div className="editor-field-legend">
            <span className="field-flag required">required</span>
            <span className="field-flag optional">optional</span>
          </div>
          <CollapsibleGroup title="Scenario identity" defaultOpen={true}>
            <div className="builder-form-grid">
              <label>
                <span className="ekey">Scenario name <span className="field-flag required">required</span></span>
                <input
                  className="text"
                  value={workingScenario.name || ""}
                  onChange={(event) => updateScenario({ name: event.target.value })}
                />
              </label>
              <label>
                <span className="ekey">Scenario color <span className="field-flag optional">optional</span></span>
                <div className="color-input">
                  <input
                    type="color"
                    value={workingScenario.color || "#1f6f55"}
                    onChange={(event) => updateScenario({ color: event.target.value })}
                  />
                  <input
                    className="text"
                    value={workingScenario.color || "#1f6f55"}
                    onChange={(event) => updateScenario({ color: event.target.value })}
                  />
                </div>
              </label>
              <label className="builder-span-2">
                <span className="ekey">Scenario description <span className="field-flag optional">optional</span></span>
                <textarea
                  className="text builder-textarea"
                  value={workingScenario.description || ""}
                  onChange={(event) => updateScenario({ description: event.target.value })}
                />
              </label>
            </div>
          </CollapsibleGroup>

          {isFeatureActive("sectors") &&
            collectSlot(enabledFeatures, "editorSections", ["sectors"]).map((Section, index) => (
              <Section key={`sectors-editor-${index}`} ctx={scenarioCtx} />
            ))}
        </section>
      )}

      {activeStep === "market" && (
        <section className="editor-section">
          <div className="editor-section-title">Year {workingYear.year} market rules</div>
          <div className="editor-field-legend">
            <span className="field-flag required">required</span>
            <span className="field-flag optional">optional</span>
          </div>

          {/* ── Modelling approach selector ── */}
          <CollapsibleGroup title="Modelling approach" defaultOpen={true}>
          <div className="approach-selector">
            <div className="approach-selector-label">Modelling approach</div>
            {visibleApproachOptions.length === 1 ? (
              <div className="approach-selector-options">
                <div className="approach-option on approach-option-static">
                  <span className="approach-option-label">{visibleApproachOptions[0].label}</span>
                  <span className="approach-option-sub">{visibleApproachOptions[0].sub}</span>
                </div>
              </div>
            ) : (
              <div className="approach-selector-options">
                {visibleApproachOptions.map((opt) => (
                  <button
                    key={opt.id}
                    type="button"
                    className={"approach-option " + ((workingScenario.model_approach || "competitive") === opt.id ? "on" : "")}
                    onClick={() => updateScenario({ model_approach: opt.id })}
                  >
                    <span className="approach-option-label">{opt.label}</span>
                    <span className="approach-option-sub">{opt.sub}</span>
                  </button>
                ))}
              </div>
            )}
            {approachScope != null && (() => {
              const namedApproaches = visibleApproachOptions.filter((opt) => opt.id !== "all");
              return (
                <p className="approach-params-hint">
                  This model is scoped to the {namedApproaches.map((opt) => opt.label).join(", ")} approach{namedApproaches.length > 1 ? "es" : ""} only.
                </p>
              );
            })()}

            {/* Hotelling extra fields — feature-owned (includes the elastic_baseline
                reference-carbon-price field, embedded at its original position) */}
            {isFeatureActive("hotelling") &&
              (workingScenario.model_approach === "hotelling" || workingScenario.model_approach === "all") &&
              FEATURES.hotelling.approachOptions?.map((ApproachSection, index) => (
                <ApproachSection key={`hotelling-approach-${index}`} ctx={scenarioCtx} />
              ))}

            {/* Nash extra fields — feature-owned */}
            {isFeatureActive("nash_cournot") &&
              (workingScenario.model_approach === "nash_cournot" || workingScenario.model_approach === "all") &&
              FEATURES.nash_cournot.approachOptions?.map((ApproachSection, index) => (
                <ApproachSection key={`nash-approach-${index}`} ctx={scenarioCtx} />
              ))}

            {/* Competitive approach-params (shown when competitive or all).
                Solver tuning is numerical-internals plumbing, not a modelling
                choice — in pe mode it hides behind "Show advanced settings"
                unless this model's config already ships non-default values
                (see solverSectionVisible / COMPETITIVE_SOLVER_FIELDS). */}
            {(workingScenario.model_approach === "competitive" || workingScenario.model_approach === "all" || !workingScenario.model_approach) &&
              solverSectionVisible(COMPETITIVE_SOLVER_FIELDS) && (
              <div className="approach-params">
                <div className="approach-params-tuning-label">Solver tuning</div>
                <div className="solver-settings-grid">
                  <label>
                    <span className="ekey">Max iterations <span className="field-flag optional">optional</span></span>
                    <span className="solver-settings-desc">Perfect-foresight convergence loop. Default: 25</span>
                    {numInput(
                      workingScenario.solver_competitive_max_iters ?? 25,
                      (v) => updateScenario({ solver_competitive_max_iters: Math.max(1, Math.round(v)) }),
                      1, 1
                    )}
                  </label>
                  <label>
                    <span className="ekey">Price convergence tolerance <span className="field-flag optional">optional</span></span>
                    <span className="solver-settings-desc">Max allowed price delta between iterations. Default: 0.001</span>
                    {numInput(
                      workingScenario.solver_competitive_tolerance ?? 0.001,
                      (v) => updateScenario({ solver_competitive_tolerance: Math.max(1e-8, v) }),
                      0.0001, 1e-8
                    )}
                  </label>
                  <label>
                    <span className="ekey">Price bracket expand factor <span className="field-flag optional">optional</span></span>
                    <span className="solver-settings-desc">Multiplier applied to upper price bound when bracket fails. Default: 2.0</span>
                    {numInput(workingScenario.solver_price_bracket_expand_factor ?? 2.0, (v) => updateScenario({ solver_price_bracket_expand_factor: Math.max(1.1, v) }), 0.1, 1.1)}
                  </label>
                  <label>
                    <span className="ekey">Price bracket max expansions <span className="field-flag optional">optional</span></span>
                    <span className="solver-settings-desc">Max times the price bracket upper bound is expanded. Default: 10</span>
                    {numInput(workingScenario.solver_price_bracket_max_expansions ?? 10, (v) => updateScenario({ solver_price_bracket_max_expansions: Math.max(1, Math.round(v)) }), 1, 1)}
                  </label>
                  <label>
                    <span className="ekey">Mixed portfolio max iterations <span className="field-flag optional">optional</span></span>
                    <span className="solver-settings-desc">SLSQP iteration limit for mixed technology portfolio. Default: 400</span>
                    {numInput(workingScenario.solver_slsqp_max_iters ?? 400, (v) => updateScenario({ solver_slsqp_max_iters: Math.max(1, Math.round(v)) }), 10, 1)}
                  </label>
                  <label>
                    <span className="ekey">Mixed portfolio tolerance (ftol) <span className="field-flag optional">optional</span></span>
                    <span className="solver-settings-desc">SLSQP convergence tolerance for mixed technology portfolio. Default: 1e-9</span>
                    {numInput(workingScenario.solver_slsqp_ftol ?? 1e-9, (v) => updateScenario({ solver_slsqp_ftol: Math.max(1e-15, v) }), 1e-10, 1e-15)}
                  </label>
                </div>
              </div>
            )}

            {/* Market clearing — numerical internals, same advanced-toggle
                treatment as Solver tuning above. Default shell: always
                visible, unchanged. */}
            {solverSectionVisible(MARKET_CLEARING_FIELDS) && (
            <div className="approach-market-clearing">
              <span className="approach-params-tuning-label" style={{ borderTop: "none", paddingTop: 0 }}>Market clearing</span>
              <div className="solver-settings-grid">
                <label>
                  <span className="ekey">Penalty price multiplier <span className="field-flag optional">optional</span></span>
                  <span className="solver-settings-desc">
                    Auto price-ceiling = max penalty price × this factor.
                    Only used when no explicit price ceiling is set. Default: 1.25
                  </span>
                  {numInput(
                    workingScenario.solver_penalty_price_multiplier ?? 1.25,
                    (v) => updateScenario({ solver_penalty_price_multiplier: Math.max(1.0, v) }),
                    0.05, 1.0
                  )}
                </label>
              </div>
            </div>
            )}
          </div>
          </CollapsibleGroup>

          {/* ── Allocation & policy trajectories ─────────────────────────── */}
          <CollapsibleGroup title="Allocation & policy trajectories" defaultOpen={false}>
          {/* ── Free allocation trajectories ─────────────────────────────── */}
          <div className="eua-prices-panel">
            <div className="eua-prices-head">
              <span className="eua-prices-label">Free allocation phase-out trajectories <span className="field-flag optional">optional</span></span>
              <button type="button" className="ghost-btn on" style={{fontSize: 12}} onClick={() => {
                const years = (scenario.years || []);
                const startY = years.length ? String(years[0].year) : "2026";
                const endY   = years.length ? String(years[years.length - 1].year) : "2034";
                const trajs = [...(workingScenario.free_allocation_trajectories || []),
                  { participant_name: "", start_year: startY, end_year: endY, start_ratio: 0.9, end_ratio: 0.0 }];
                updateScenario({ free_allocation_trajectories: trajs });
              }}>+ Add trajectory</button>
            </div>
            <span className="approach-params-hint">Auto-computes free_allocation_ratio for each year via linear interpolation. Overrides per-year values for the named participant.</span>
            {(workingScenario.free_allocation_trajectories || []).map((traj, ti) => (
              <div key={ti} className="traj-row">
                <input type="text" className="text" placeholder="Participant name" value={traj.participant_name ?? ""} style={{width: 130}}
                  onChange={(e) => {
                    const trajs = [...(workingScenario.free_allocation_trajectories || [])];
                    trajs[ti] = { ...trajs[ti], participant_name: e.target.value };
                    updateScenario({ free_allocation_trajectories: trajs });
                  }} />
                <input type="text" className="text" placeholder="Start yr" value={traj.start_year ?? ""} style={{width: 70}}
                  onChange={(e) => {
                    const trajs = [...(workingScenario.free_allocation_trajectories || [])];
                    trajs[ti] = { ...trajs[ti], start_year: e.target.value };
                    updateScenario({ free_allocation_trajectories: trajs });
                  }} />
                <input type="text" className="text" placeholder="End yr" value={traj.end_year ?? ""} style={{width: 70}}
                  onChange={(e) => {
                    const trajs = [...(workingScenario.free_allocation_trajectories || [])];
                    trajs[ti] = { ...trajs[ti], end_year: e.target.value };
                    updateScenario({ free_allocation_trajectories: trajs });
                  }} />
                {numInput(traj.start_ratio ?? 0.9, (v) => {
                  const trajs = [...(workingScenario.free_allocation_trajectories || [])];
                  trajs[ti] = { ...trajs[ti], start_ratio: Math.min(1, Math.max(0, v)) };
                  updateScenario({ free_allocation_trajectories: trajs });
                }, 0.05, 0)}
                <span style={{fontSize: 11, color: "#666"}}>→</span>
                {numInput(traj.end_ratio ?? 0, (v) => {
                  const trajs = [...(workingScenario.free_allocation_trajectories || [])];
                  trajs[ti] = { ...trajs[ti], end_ratio: Math.min(1, Math.max(0, v)) };
                  updateScenario({ free_allocation_trajectories: trajs });
                }, 0.05, 0)}
                <button type="button" className="ghost-btn" style={{fontSize: 11, padding: "2px 6px"}} onClick={() => {
                  const trajs = (workingScenario.free_allocation_trajectories || []).filter((_, i) => i !== ti);
                  updateScenario({ free_allocation_trajectories: trajs });
                }}>✕</button>
              </div>
            ))}
          </div>

          {/* ── Cap & Price Bound Trajectories ─────────────────────────────── */}
          {/* Cap trajectory stays core; price floor/ceiling trajectories are
              owned by the price_controls feature (same TrajectoryRangeRow,
              reused rather than duplicated). */}
          <TrajectoryRangeRow
            scenario={workingScenario}
            updateScenario={updateScenario}
            rowKey="cap_trajectory"
            label="Cap trajectory"
            hint="Auto-declining total_cap. Overrides per-year total_cap when active."
            unit="Mt"
          />
          {isFeatureActive("price_controls") && (() => {
            // price_controls.editorSections[0] = floor/ceiling trajectory rows
            // (rendered here); [1] = auction guardrail fields (rendered further
            // below, inside "Supply & price bounds").
            const PriceBoundTrajectories = FEATURES.price_controls.editorSections?.[0];
            return PriceBoundTrajectories ? <PriceBoundTrajectories ctx={scenarioCtx} /> : null;
          })()}
          </CollapsibleGroup>

          <CollapsibleGroup title="Supply & price bounds" defaultOpen={true}>
          <div className="builder-form-grid">
            <label>
              <span className="ekey">Year label <span className="field-flag required">required</span></span>
              <select
                value={String(year.year)}
                onChange={(event) => onSelectYear?.(event.target.value)}
              >
                {(scenario.years || []).map((item) => (
                  <option key={item.year} value={String(item.year)}>
                    {item.year}
                  </option>
                ))}
              </select>
            </label>
            <label>
              <span className="ekey">Auction mode <span className="field-flag required">required</span></span>
              <select
                value={workingYear.auction_mode}
                onChange={(event) => updateYear({ auction_mode: event.target.value })}
              >
                <option value="explicit">explicit</option>
                <option value="derive_from_cap">derive_from_cap</option>
              </select>
            </label>
            {yearFieldVisible("total_cap") && (
            <label>
              <span className="ekey">{fieldWithPathButton("Total cap", () => openMarketSeriesEditor("total_cap"), true)}</span>
              {numInput(workingYear.total_cap, (value) => updateYear({ total_cap: value }), 1, 0)}
            </label>
            )}
            {yearFieldVisible("auction_offered") && (
            <label>
              <span className="ekey">{fieldWithPathButton("Auction offered", () => openMarketSeriesEditor("auction_offered"), true)}</span>
              {numInput(workingYear.auction_offered || 0, (value) => updateYear({ auction_offered: value }), 1, 0)}
            </label>
            )}
            {yearFieldVisible("reserved_allowances") && (
            <label>
              <span className="ekey">{fieldWithPathButton("Reserved allowances", () => openMarketSeriesEditor("reserved_allowances"), false, true)}</span>
              {numInput(workingYear.reserved_allowances || 0, (value) => updateYear({ reserved_allowances: value }), 1, 0)}
            </label>
            )}
            {isFeatureActive("price_controls") && (() => {
              // price_controls.editorSections[1] = auction guardrail fields
              // (reserve price, minimum bid coverage, unsold treatment).
              const AuctionGuardrailFields = FEATURES.price_controls.editorSections?.[1];
              return AuctionGuardrailFields ? <AuctionGuardrailFields ctx={scenarioCtx} /> : null;
            })()}
            {yearFieldVisible("price_lower_bound") && (
            <label>
              <span className="ekey">{fieldWithPathButton("Price floor", () => openMarketSeriesEditor("price_lower_bound"), true)}</span>
              {numInput(workingYear.price_lower_bound, (value) => updateYear({ price_lower_bound: value }), 1, 0)}
            </label>
            )}
            {yearFieldVisible("price_upper_bound") && (
            <label>
              <span className="ekey">{fieldWithPathButton("Price ceiling", () => openMarketSeriesEditor("price_upper_bound"), true)}</span>
              {numInput(workingYear.price_upper_bound, (value) => updateYear({ price_upper_bound: value }), 1, 0)}
            </label>
            )}
          </div>
          </CollapsibleGroup>

          {bankingGroupVisible && (
          <CollapsibleGroup title="Banking, borrowing & expectations" defaultOpen={false}>
          <div className="builder-form-grid">
            <label>
              <span className="ekey">Banking allowed <span className="field-flag optional">optional</span></span>
              <select
                value={workingYear.banking_allowed ? "true" : "false"}
                onChange={(event) => updateYear({ banking_allowed: event.target.value === "true" })}
              >
                <option value="false">false</option>
                <option value="true">true</option>
              </select>
            </label>
            <label>
              <span className="ekey">Borrowing allowed <span className="field-flag optional">optional</span></span>
              <select
                value={workingYear.borrowing_allowed ? "true" : "false"}
                onChange={(event) => updateYear({ borrowing_allowed: event.target.value === "true" })}
              >
                <option value="false">false</option>
                <option value="true">true</option>
              </select>
            </label>
            {yearFieldVisible("borrowing_limit") && (
            <label>
              <span className="ekey">{fieldWithPathButton("Borrowing limit", () => openMarketSeriesEditor("borrowing_limit"), false, true)}</span>
              {numInput(workingYear.borrowing_limit || 0, (value) => updateYear({ borrowing_limit: value }), 1, 0)}
            </label>
            )}
            <label>
              <span className="ekey">Expectation rule <span className="field-flag optional">optional</span></span>
              <select
                value={workingYear.expectation_rule || "next_year_baseline"}
                onChange={(event) => updateYear({ expectation_rule: event.target.value })}
              >
                <option value="myopic">myopic</option>
                <option value="next_year_baseline">next_year_baseline</option>
                <option value="perfect_foresight">perfect_foresight</option>
                <option value="manual">manual</option>
              </select>
            </label>
            {yearFieldVisible("manual_expected_price") && (
            <label>
              <span className="ekey">{fieldWithPathButton("Manual expected price", () => openMarketSeriesEditor("manual_expected_price"), false, true)}</span>
              {numInput(workingYear.manual_expected_price || 0, (value) => updateYear({ manual_expected_price: value }), 1, 0)}
            </label>
            )}
            {/* eua_price is a cbam-owned field (single-jurisdiction reference
                price) — feature-gated like every other cbam surface (the
                per-jurisdiction/ensemble EUA tables just below in "EUA &
                external prices" are already isFeatureActive("cbam")-gated;
                this scalar field had been left ungated, the one metric-list
                sweep gap price_controls-style extraction didn't already
                cover). Unscoped shell: isFeatureActive(null) is always true,
                so this stays unconditionally visible, unchanged. */}
            {isFeatureActive("cbam") && yearFieldVisible("eua_price") && (
            <label>
              <span className="ekey">{fieldWithPathButton("EUA price (external)", () => openMarketSeriesEditor("eua_price"), false, true)}</span>
              {numInput(workingYear.eua_price || 0, (value) => updateYear({ eua_price: value }), 1, 0)}
              <span className="approach-params-hint">EU ETS reference price used as default for CBAM gap calculation.</span>
            </label>
            )}
          </div>
          </CollapsibleGroup>
          )}

          {/* ── EUA & external prices ─────────────────────────────────────── */}
          {isFeatureActive("cbam") &&
            collectSlot(enabledFeatures, "editorSections", ["cbam"]).map((Section, index) => (
              <Section key={`cbam-editor-${index}`} ctx={scenarioCtx} />
            ))}

          {/* ── MSR panel ────────────────────────────────────────────────── */}
          {isFeatureActive("msr") &&
            collectSlot(enabledFeatures, "editorSections", ["msr"]).map((Section, index) => (
              <Section key={`msr-editor-${index}`} ctx={scenarioCtx} />
            ))}

          {/* ── CCR panel ────────────────────────────────────────────────── */}
          {isFeatureActive("ccr") &&
            collectSlot(enabledFeatures, "editorSections", ["ccr"]).map((Section, index) => (
              <Section key={`ccr-editor-${index}`} ctx={scenarioCtx} />
            ))}

          {isFeatureActive("calibration") &&
            collectSlot(enabledFeatures, "editorSections", ["calibration"]).map((Section, index) => (
              <Section key={`calibration-editor-${index}`} ctx={scenarioCtx} />
            ))}

          {/* ── Investment feedback panel ───────────────────────────────── */}
          {isFeatureActive("endogenous_investment") &&
            collectSlot(enabledFeatures, "editorSections", ["endogenous_investment"]).map((Section, index) => (
              <Section key={`endogenous-investment-editor-${index}`} ctx={scenarioCtx} />
            ))}

        </section>
      )}

      {activeStep === "participants" && (
        <section className="editor-section">
          <div className="editor-section-title">Participant builder</div>
          <div className="editor-field-legend">
            <span className="field-flag required">required</span>
            <span className="field-flag optional">optional</span>
          </div>
          <div className="builder-layout">
            <aside className="builder-sidebar">
              <div className="builder-sidebar-head">
                <div className="eyebrow">Participants</div>
                <button className="ghost-btn on" type="button" onClick={addParticipant}>Add</button>
              </div>
              <div className="builder-template-box">
                <div className="eyebrow">Add participant from template</div>
                <select
                  value={selectedParticipantTemplate}
                  onChange={(event) => setSelectedParticipantTemplate(event.target.value)}
                >
                  <option value="steel_blast_furnace">Steel Blast Furnace</option>
                  <option value="steel_hydrogen_dri">Steel Hydrogen DRI</option>
                  <option value="coal_generator">Coal Generator</option>
                  <option value="renewable_generator">Renewable Generator</option>
                  <option value="cement_kiln">Cement Kiln</option>
                </select>
                <div className="editor-actions spread">
                  <button className="ghost-btn" type="button" onClick={() => applyParticipantTemplate(selectedParticipantTemplate, "add")}>
                    Add from template
                  </button>
                  <button
                    className="ghost-btn"
                    type="button"
                    disabled={!participant}
                    onClick={() => applyParticipantTemplate(selectedParticipantTemplate, "replace")}
                  >
                    Apply to selected
                  </button>
                </div>
              </div>
              <div className="builder-list">
                {(workingYear.participants || []).map((item, index) => (
                  <button
                    key={`${item.name}-${index}`}
                    type="button"
                    className={"builder-list-item " + (selectedParticipantIndex === index ? "on" : "")}
                    onClick={() => {
                      setSelectedParticipantIndex(index);
                      setSelectedTechnologyIndex(0);
                    }}
                  >
                    <span>{item.name || `Participant ${index + 1}`}</span>
                    <span className="builder-item-meta">{item.sector || "Other"}</span>
                  </button>
                ))}
                {!(workingYear.participants || []).length && (
                  <div className="builder-empty">No participants yet. Add one to start building.</div>
                )}
              </div>
            </aside>

            <div className="builder-main">
              {participant ? (
                <>
                  <div className="builder-card">
                    <div className="builder-card-head">
                      <div>
                        <div className="eyebrow">Selected participant</div>
                        <h4>{participant.name || "Unnamed participant"}</h4>
                      </div>
                      <div className="editor-actions">
                        <button className="ghost-btn" type="button" onClick={() => duplicateParticipant(selectedParticipantIndex)}>Duplicate</button>
                        <button className="ghost-btn danger-btn" type="button" onClick={() => removeParticipant(selectedParticipantIndex)}>Remove</button>
                      </div>
                    </div>
                    <CollapsibleGroup title="Identity & emissions" defaultOpen={true}>
                    <div className="builder-form-grid">
                      <label>
                        <span className="ekey">Participant name <span className="field-flag required">required</span></span>
                        <input
                          className="text"
                          value={participant.name}
                          onChange={(event) => updateParticipant(selectedParticipantIndex, { name: event.target.value })}
                        />
                      </label>
                      <label>
                        <span className="ekey">Sector <span className="field-flag optional">optional</span></span>
                        <select
                          value={participant.sector || "Other"}
                          onChange={(event) => updateParticipant(selectedParticipantIndex, { sector: event.target.value })}
                        >
                          <option value="Industry">Industry</option>
                          <option value="Power">Power</option>
                          <option value="Other">Other</option>
                        </select>
                      </label>
                      <label>
                        <span className="ekey">{fieldWithPathButton("Initial emissions", () => openParticipantSeriesEditor("initial_emissions"), true)}</span>
                        {numInput(participant.initial_emissions, (value) => updateParticipant(selectedParticipantIndex, { initial_emissions: value }), 1, 0)}
                      </label>
                      {/* ── BAU Emissions Trajectory ───────────────────── */}
                      {(() => {
                        const traj = participant.initial_emissions_trajectory || {};
                        const active = !!(traj.start_year && traj.end_year && traj.start_value !== undefined && traj.end_value !== undefined);
                        const years = workingScenario.years || [];
                        const startY = years.length ? String(years[0].year) : "2026";
                        const endY = years.length ? String(years[years.length - 1].year) : "2035";
                        return (
                          <div className="traj-section" style={{ gridColumn: "1 / -1", marginBottom: 4 }}>
                            <div className="traj-head">
                              <span className="traj-label" style={{ fontSize: 11 }}>BAU emissions trajectory <span className="field-flag optional">optional</span></span>
                              <span className="approach-params-hint" style={{ fontSize: 10 }}>Auto-overrides initial_emissions each year via linear interpolation.</span>
                              {active
                                ? <button type="button" className="ghost-btn" style={{ fontSize: 10, padding: "1px 6px" }} onClick={() => updateParticipant(selectedParticipantIndex, { initial_emissions_trajectory: {} })}>Clear</button>
                                : <button type="button" className="ghost-btn on" style={{ fontSize: 10, padding: "1px 6px" }} onClick={() => updateParticipant(selectedParticipantIndex, { initial_emissions_trajectory: { start_year: startY, end_year: endY, start_value: Number(participant.initial_emissions || 0), end_value: Number(participant.initial_emissions || 0) * 0.8 } })}>Enable trajectory</button>
                              }
                            </div>
                            {active && (
                              <div className="traj-row" style={{ gridTemplateColumns: "70px 70px 110px 110px", gap: 6, padding: "6px 10px" }}>
                                <div className="builder-form-field" style={{ margin: 0 }}>
                                  <label style={{ fontSize: 10 }}>Start year</label>
                                  <input type="text" value={traj.start_year ?? ""} onChange={(e) => updateParticipant(selectedParticipantIndex, { initial_emissions_trajectory: { ...traj, start_year: e.target.value } })} />
                                </div>
                                <div className="builder-form-field" style={{ margin: 0 }}>
                                  <label style={{ fontSize: 10 }}>End year</label>
                                  <input type="text" value={traj.end_year ?? ""} onChange={(e) => updateParticipant(selectedParticipantIndex, { initial_emissions_trajectory: { ...traj, end_year: e.target.value } })} />
                                </div>
                                <div className="builder-form-field" style={{ margin: 0 }}>
                                  <label style={{ fontSize: 10 }}>Start value (Mt)</label>
                                  <input type="number" step="1" value={traj.start_value ?? ""} onChange={(e) => updateParticipant(selectedParticipantIndex, { initial_emissions_trajectory: { ...traj, start_value: +e.target.value } })} />
                                </div>
                                <div className="builder-form-field" style={{ margin: 0 }}>
                                  <label style={{ fontSize: 10 }}>End value (Mt)</label>
                                  <input type="number" step="1" value={traj.end_value ?? ""} onChange={(e) => updateParticipant(selectedParticipantIndex, { initial_emissions_trajectory: { ...traj, end_value: +e.target.value } })} />
                                </div>
                              </div>
                            )}
                          </div>
                        );
                      })()}
                    </div>
                    </CollapsibleGroup>

                    <CollapsibleGroup title="Allocation" defaultOpen={true}>
                    <div className="builder-form-grid">
                      {/* ── OBA / Benchmark fields (production_output, benchmark
                          intensity, output_price_elasticity, and the free
                          allocation ratio / sector allocation share choice) ── */}
                      {isFeatureActive("oba") &&
                        FEATURES.oba.participantEditorSections?.map((Field, index) => (
                          <Field key={`oba-participant-${index}`} ctx={participantCtx} />
                        ))}
                      <label>
                        <span className="ekey">{fieldWithPathButton("Penalty price", () => openParticipantSeriesEditor("penalty_price"), true)}</span>
                        {numInput(participant.penalty_price, (value) => updateParticipant(selectedParticipantIndex, { penalty_price: value }), 1, 0)}
                      </label>
                      {/* ── Sector group ─────────────────────────────────── */}
                      {isFeatureActive("sectors") &&
                        FEATURES.sectors.participantEditorSections?.map((Field, index) => (
                          <Field key={`sectors-participant-${index}`} ctx={participantCtx} />
                        ))}
                    </div>
                    </CollapsibleGroup>

                    {/* ── CBAM exposure + Scope 2 / Indirect emissions ─── */}
                    {isFeatureActive("cbam") &&
                      FEATURES.cbam.participantEditorSections?.map((Section, index) => (
                        <Section key={`cbam-participant-${index}`} ctx={participantCtx} />
                      ))}

                    <CollapsibleGroup title="Abatement" defaultOpen={true}>
                    {renderAbatementFields(
                      participant,
                      (patch) => updateParticipant(selectedParticipantIndex, patch),
                    )}
                    </CollapsibleGroup>
                  </div>

                  <div className="builder-card">
                    <div className="builder-card-head">
                      <div>
                        <div className="eyebrow">Technology options</div>
                        <h4>Alternative technologies for {participant.name}</h4>
                      </div>
                      <div className="editor-actions">
                        <button className="ghost-btn on" type="button" onClick={() => addTechnologyOption(selectedParticipantIndex)}>Add technology</button>
                        <button className="ghost-btn" type="button" onClick={() => setWizardOpen((value) => !value)}>
                          {wizardOpen ? "Hide transition wizard" : "Open transition wizard"}
                        </button>
                        <button className="ghost-btn" type="button" onClick={() => buildTechnologyPathway(selectedParticipantIndex)}>
                          Quick pathway
                        </button>
                      </div>
                    </div>
                    <p className="muted">
                      If technology options are added, the model chooses the lowest-cost technology in equilibrium.
                    </p>
                    {wizardOpen && participant ? (
                      <div className="builder-wizard">
                        <div className="builder-card-subhead compact">
                          <div>
                            <div className="eyebrow">Transition wizard</div>
                            <div className="muted">Choose the incumbent archetype, select replacement technologies, preview the pathway, then apply it.</div>
                          </div>
                        </div>
                        <div className="builder-form-grid">
                          <label>
                            <span className="ekey">Incumbent archetype</span>
                            <select value={wizardArchetype} onChange={(event) => setWizardArchetype(event.target.value)}>
                              {Object.entries(wizardArchetypes).map(([id, item]) => (
                                <option key={id} value={id}>{item.label}</option>
                              ))}
                            </select>
                          </label>
                          <label>
                            <span className="ekey">Transition mode</span>
                            <select value={wizardMode} onChange={(event) => setWizardMode(event.target.value)}>
                              <option value="conservative">conservative</option>
                              <option value="moderate">moderate</option>
                              <option value="aggressive">aggressive</option>
                            </select>
                          </label>
                          <div className="builder-span-2 builder-wizard-choice-box">
                            <span className="ekey">Replacement technologies</span>
                            <div className="builder-choice-grid">
                              {(wizardArchetypes[wizardArchetype]?.replacements || []).map((replacementId) => (
                                <label key={replacementId} className={"builder-choice-card " + (wizardReplacements.includes(replacementId) ? "on" : "")}>
                                  <input
                                    type="checkbox"
                                    checked={wizardReplacements.includes(replacementId)}
                                    onChange={() => toggleWizardReplacement(replacementId)}
                                  />
                                  <span>{replacementCatalog[replacementId]?.label || replacementId}</span>
                                </label>
                              ))}
                            </div>
                            <div className="muted">{wizardArchetypes[wizardArchetype]?.description}</div>
                          </div>
                        </div>
                        <div className="builder-wizard-preview">
                          <div className="builder-card-subhead compact">
                            <div>
                              <div className="eyebrow">Preview</div>
                              <div className="muted">This technology set will be written into the selected participant.</div>
                            </div>
                            <button
                              className="ghost-btn on"
                              type="button"
                              disabled={buildWizardPreview().length <= 1}
                              onClick={applyWizardPathway}
                            >
                              Apply pathway
                            </button>
                          </div>
                          <div className="builder-wizard-preview-grid">
                            {buildWizardPreview().map((option, index) => (
                              <div key={`${option.name}-${index}`} className="builder-preview-card">
                                <div className="builder-preview-head">
                                  <strong>{option.name}</strong>
                                  <span className={"builder-preview-tag " + (index === 0 ? "incumbent" : "transition")}>
                                    {index === 0 ? "Incumbent" : "Candidate"}
                                  </span>
                                </div>
                                <div className="builder-preview-metrics">
                                  <span>Emissions {fmt.num(option.initial_emissions || 0, 1)}</span>
                                  <span>Free ratio {fmt.num(option.free_allocation_ratio || 0, 2)}</span>
                                  <span>Fixed cost {fmt.num(option.fixed_cost || 0, 0)}</span>
                                  <span>Cap {fmt.num(option.max_activity_share ?? 1, 2)}</span>
                                  <span>MAC blocks {(option.mac_blocks || []).length}</span>
                                </div>
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>
                    ) : null}
                    <div className="builder-tech-layout">
                      <div className="builder-tech-list">
                        {(participant.technology_options || []).map((option, index) => (
                          <button
                            key={`${option.name}-${index}`}
                            type="button"
                            className={"builder-list-item " + (selectedTechnologyIndex === index ? "on" : "")}
                            onClick={() => setSelectedTechnologyIndex(index)}
                          >
                            <span>{option.name || `Technology ${index + 1}`}</span>
                            <span className="builder-item-meta">{fmt.num(option.initial_emissions || 0, 0)} emissions</span>
                          </button>
                        ))}
                        {!(participant.technology_options || []).length && (
                          <div className="builder-empty">No technology options added. The participant uses its base configuration.</div>
                        )}
                      </div>
                      {selectedTechnology ? (
                        <div className="builder-tech-editor">
                          <div className="builder-card-subhead">
                            <div className="eyebrow">Selected technology</div>
                            <button
                              className="ghost-btn danger-btn"
                              type="button"
                              onClick={() => removeTechnologyOption(selectedParticipantIndex, selectedTechnologyIndex)}
                            >
                              Remove technology
                            </button>
                          </div>
                          <CollapsibleGroup title="Technology parameters" defaultOpen={true}>
                          <div className="builder-form-grid">
                            <label>
                              <span className="ekey">Technology name <span className="field-flag required">required</span></span>
                              <input
                                className="text"
                                value={selectedTechnology.name}
                                onChange={(event) => updateTechnologyOption(selectedParticipantIndex, selectedTechnologyIndex, { name: event.target.value })}
                              />
                            </label>
                            <label>
                              <span className="ekey">{fieldWithPathButton("Fixed cost", () => openTechnologySeriesEditor("fixed_cost"), false, true)}</span>
                              {numInput(selectedTechnology.fixed_cost || 0, (value) => updateTechnologyOption(selectedParticipantIndex, selectedTechnologyIndex, { fixed_cost: value }), 1, 0, fieldHelp.fixed_cost)}
                            </label>
                            <label>
                              <span className="ekey">{fieldWithPathButton("Adoption share cap", () => openTechnologySeriesEditor("max_activity_share"), false, true)}</span>
                              {numInput(selectedTechnology.max_activity_share ?? 1, (value) => updateTechnologyOption(selectedParticipantIndex, selectedTechnologyIndex, { max_activity_share: value }), 0.05, 0)}
                            </label>
                            <label>
                              <span className="ekey">{fieldWithPathButton("Technology emissions", () => openTechnologySeriesEditor("initial_emissions"), true)}</span>
                              {numInput(selectedTechnology.initial_emissions || 0, (value) => updateTechnologyOption(selectedParticipantIndex, selectedTechnologyIndex, { initial_emissions: value }), 1, 0)}
                            </label>
                            <label>
                              <span className="ekey">{fieldWithPathButton("Technology free ratio", () => openTechnologySeriesEditor("free_allocation_ratio"), true)}</span>
                              {numInput(selectedTechnology.free_allocation_ratio || 0, (value) => updateTechnologyOption(selectedParticipantIndex, selectedTechnologyIndex, { free_allocation_ratio: value }), 0.05, 0)}
                            </label>
                            <label>
                              <span className="ekey">{fieldWithPathButton("Technology penalty price", () => openTechnologySeriesEditor("penalty_price"), true)}</span>
                              {numInput(selectedTechnology.penalty_price || 0, (value) => updateTechnologyOption(selectedParticipantIndex, selectedTechnologyIndex, { penalty_price: value }), 1, 0)}
                            </label>
                          </div>
                          </CollapsibleGroup>
                          <CollapsibleGroup title="Technology abatement" defaultOpen={true}>
                          {renderAbatementFields(
                            selectedTechnology,
                            (patch) => updateTechnologyOption(selectedParticipantIndex, selectedTechnologyIndex, patch),
                            "Technology ",
                          )}
                          </CollapsibleGroup>
                          {/* ── Investment trigger (per technology option) ── */}
                          {isFeatureActive("endogenous_investment") &&
                            FEATURES.endogenous_investment.participantEditorSections?.map((Section, index) => (
                              <Section key={`endogenous-investment-technology-${index}`} ctx={technologyCtx} />
                            ))}
                        </div>
                      ) : null}
                    </div>
                  </div>
                </>
              ) : (
                <div className="builder-empty large">Add a participant to start the step-by-step builder.</div>
              )}
            </div>
          </div>
        </section>
      )}

      {activeStep === "review" && (
        <section className="editor-section">
          <div className="editor-section-title">Scenario review</div>
          <div className="builder-review-grid">
            <div className="builder-review-card">
              <span className="ekey">Scenario</span>
              <strong>{workingScenario.name}</strong>
              <span className="muted">{workingScenario.description || "No description yet."}</span>
            </div>
            <div className="builder-review-card">
              <span className="ekey">Year</span>
              <strong>{workingYear.year}</strong>
              <span className="muted">Cap {fmt.num(workingYear.total_cap || 0, 0)} · Offered {fmt.num(workingYear.auction_offered || 0, 0)}</span>
            </div>
            <div className="builder-review-card">
              <span className="ekey">Participants</span>
              <strong>{(workingYear.participants || []).length}</strong>
              <span className="muted">
                {(workingYear.participants || []).reduce((sum, item) => sum + ((item.technology_options || []).length || 0), 0)} technology options configured
              </span>
            </div>
            <div className="builder-review-card">
              <span className="ekey">Intertemporal rules</span>
              <strong>{workingYear.banking_allowed ? "Banking on" : "Banking off"}</strong>
              <span className="muted">{workingYear.borrowing_allowed ? `Borrowing up to ${fmt.num(workingYear.borrowing_limit || 0, 0)}` : "Borrowing off"}</span>
              <span className="muted">Expectations: {workingYear.expectation_rule || "next_year_baseline"}{(workingYear.expectation_rule || "next_year_baseline") === "manual" ? ` (${fmt.price(workingYear.manual_expected_price || 0)})` : ""}</span>
            </div>
          </div>
          <div className="builder-review-table">
            <table className="pathway-table">
              <thead>
                <tr>
                  <th>Participant</th>
                  <th>Abatement model</th>
                  <th>MAC blocks</th>
                  <th>Technology options</th>
                </tr>
              </thead>
              <tbody>
                {(workingYear.participants || []).map((item, index) => (
                  <tr key={`${item.name}-${index}`}>
                    <td>{item.name}</td>
                    <td>{item.abatement_type}</td>
                    <td>{serializeMacBlocks(item) || "—"}</td>
                    <td>{(item.technology_options || []).map((option) => option.name).join(", ") || "Base only"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {seriesEditor ? (
        <YearSeriesModal
          title={seriesEditor.title}
          field={seriesEditor.field}
          years={scenarioYearsWithDraft}
          values={seriesEditor.values}
          description={seriesEditor.description}
          onClose={() => setSeriesEditor(null)}
          onSave={applySeriesEdit}
          step={getSeriesFieldMeta(seriesEditor.field).step}
          min={getSeriesFieldMeta(seriesEditor.field).min}
          max={getSeriesFieldMeta(seriesEditor.field).max}
        />
      ) : null}
    </div>
  );
}
