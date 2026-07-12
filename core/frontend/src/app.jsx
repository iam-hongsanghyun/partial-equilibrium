import { useState as useS, useEffect as useE, useRef as useR } from "react";
import {
  makeBlankParticipant,
  makeBlankYear,
  makeBlankScenario,
  buildDraftResult,
  configsEqual,
  validateScenario,
  Header,
  Tweaks,
} from "./components/AppShared.jsx";
import { BuildView, ValidationView, AnalysisView, Compare } from "./components/AppViews.jsx";
import { GuideView, hasGuideContent } from "./components/GuideView.jsx";
import {
  flattenRunScenarios,
  jointRowsFromSummary,
  jointProblemsFromRows,
  jointRowForScenario,
  JointNonConvergenceBanner,
  JointConvergenceCard,
} from "./components/MultiMarket.jsx";
import { SectorInteraction } from "./components/SectorInteraction.jsx";
import { CanvasView } from "./pe/CanvasView.jsx";

export default function App({ enabledFeatures = null, manifest = null, initialTemplateId = null, initialConfig = null } = {}) {
  const [templates, setTemplates] = useS([]);
  const [config, setConfig] = useS({ scenarios: [] });
  const [results, setResults] = useS({});
  const [summary, setSummary] = useS([]);
  const [analysis, setAnalysis] = useS([]);
  const [activeScenarioId, setActiveScenarioId] = useS(null);
  const [activeYear, setActiveYear] = useS(null);
  // JOINT / multi-market only: which market of the active scenario is on screen.
  // Null selects the first market; ignored entirely for a single-market scenario.
  const [activeMarketId, setActiveMarketId] = useS(null);
  const [stacked, setStacked] = useS(true);
  const [activeSection, setActiveSection] = useS("build");
  const [selPart, setSelPart] = useS(null);
  const [validationTarget, setValidationTarget] = useS(null);
  const [status, setStatus] = useS("Loading…");
  const [serverWarnings, setServerWarnings] = useS([]);
  const [tweaksOpen, setTweaksOpen] = useS(false);
  const [tweakState, setTweakState] = useS({
    dark: false,
    chartStyle: "institutional",
    density: "comfortable",
  });
  const configRef = useR(config);
  const loadedConfigRef = useR(null);

  useE(() => {
    configRef.current = config;
  }, [config]);

  useE(() => {
    const onMsg = (e) => {
      if (!e.data || typeof e.data !== "object") return;
      if (e.data.type === "__activate_edit_mode") setTweaksOpen(true);
      if (e.data.type === "__deactivate_edit_mode") setTweaksOpen(false);
    };
    window.addEventListener("message", onMsg);
    window.parent?.postMessage({ type: "__edit_mode_available" }, "*");
    return () => window.removeEventListener("message", onMsg);
  }, []);

  useE(() => {
    document.documentElement.dataset.theme = tweakState.dark ? "dark" : "light";
    document.documentElement.dataset.chart = tweakState.chartStyle;
    document.documentElement.dataset.density = tweakState.density;
  }, [tweakState]);

  useE(() => {
    loadTemplates();
  }, []);

  function makeImportedScenarioName(baseName, existingScenarios) {
    const existingNames = new Set((existingScenarios || []).map((scenario) => scenario.name));
    if (!existingNames.has(baseName)) return baseName;
    let suffix = 2;
    while (existingNames.has(`${baseName} ${suffix}`)) suffix += 1;
    return `${baseName} ${suffix}`;
  }

  function importTemplateScenarios(templateConfig, existingScenarios, replacedScenarioId = null) {
    const otherScenarios = (existingScenarios || []).filter((scenario) => scenario.id !== replacedScenarioId);
    const imported = structuredClone(templateConfig?.scenarios || []).map((scenario, index) => ({
      ...scenario,
      id: `imported_scenario_${Date.now()}_${index}_${Math.random().toString(36).slice(2, 8)}`,
      name: makeImportedScenarioName(scenario.name || `Imported Scenario ${index + 1}`, otherScenarios),
    }));
    return imported;
  }

  async function loadTemplates() {
    try {
      const response = await fetch("/api/templates");
      const payload = await response.json();
      setTemplates(payload.templates || []);
      const defaultTemplate =
        // A restored SESSION seeds the editor from its own full config (more
        // specific than any model/template); models fall back to the picker.
        initialConfig
        || (initialTemplateId && payload.templates?.find((item) => item.id === initialTemplateId)?.config)
        || payload.templates?.find((item) => item.id === "example")?.config
        || payload.templates?.find((item) => item.config?.scenarios?.some((scenario) =>
          scenario.years?.some((year) => (year.participants || []).length > 0)
        ))?.config
        || payload.templates?.[0]?.config
        || { scenarios: [] };
      const initialConfig = structuredClone(defaultTemplate);
      setConfig(initialConfig);
      configRef.current = initialConfig;
      loadedConfigRef.current = structuredClone(defaultTemplate);
      const firstScenario = defaultTemplate.scenarios?.[0];
      // A JOINT scenario carries its years inside each market, not at the top
      // level — seed the active year from the first market's years then.
      const firstYears = Array.isArray(firstScenario?.markets) && firstScenario.markets.length
        ? (firstScenario.markets[0].years || [])
        : (firstScenario?.years || []);
      setActiveScenarioId(firstScenario?.id || null);
      setActiveYear(firstYears[0]?.year || null);
      setResults({});
      setSummary([]);
      setAnalysis([]);
      setStatus("Loaded");
    } catch (error) {
      setStatus("Load failed");
    }
  }

  async function saveActiveScenarioToLibrary() {
    if (!activeScenario) return;
    setStatus("Saving…");
    try {
      const response = await fetch("/api/save-scenario", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ scenario: activeScenario }),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Save failed.");
      }
      setTemplates((prev) => {
        const next = [...prev.filter((item) => item.id !== payload.template.id), payload.template];
        next.sort((left, right) => {
          if (left.id === "blank") return -1;
          if (right.id === "blank") return 1;
          return left.name.localeCompare(right.name);
        });
        return next;
      });
      setStatus("Saved");
    } catch (error) {
      setStatus("Save failed");
    }
  }

  async function runSimulation(configOverride = null) {
    const payloadConfig = structuredClone(configOverride || configRef.current);
    setStatus("Running…");
    try {
      const response = await fetch("/api/run", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payloadConfig),
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.error || "Run failed.");
      }
      setConfig(payload.config);
      setResults(payload.results || {});
      setSummary(payload.summary || []);
      setAnalysis(payload.analysis || []);
      setServerWarnings(payload.warnings || []);
      if (!activeScenarioId && payload.config?.scenarios?.length) {
        setActiveScenarioId(payload.config.scenarios[0].id);
      }
      const scenario = payload.config?.scenarios?.find((s) => s.id === activeScenarioId)
        || payload.config?.scenarios?.[0];
      // A JOINT scenario has no top-level years — check the active year against
      // its first market's years instead (a flat scenario reads scenario.years
      // exactly as before).
      const scenarioYears = Array.isArray(scenario?.markets) && scenario.markets.length
        ? (scenario.markets[0].years || [])
        : (scenario?.years || []);
      if (scenario && !scenarioYears.some((y) => String(y.year) === String(activeYear))) {
        setActiveYear(scenarioYears[0]?.year || null);
      }
      setStatus("Complete");
    } catch (error) {
      setStatus("Run failed");
    }
  }

  const scenarios = config.scenarios || [];
  const activeScenario = scenarios.find((s) => s.id === activeScenarioId) || scenarios[0];
  // A JOINT / multi-market scenario carries a `markets` array instead of a
  // top-level `years`, and the backend keys its results by the composite
  // `"<scenario> :: <market>"`. Flatten it into one pseudo-scenario per market
  // (the SAME helper the Composer uses) and drive every per-scenario view off
  // the SELECTED market's pseudo-scenario. Config-driven guard: a scenario with
  // no `markets` array sets activeIsJoint=false, so viewScenario===activeScenario,
  // viewScenarios===scenarios, activeMarket===null, and the single-market path
  // below stays byte-for-byte what it is today.
  const activeIsJoint = Array.isArray(activeScenario?.markets) && activeScenario.markets.length > 0;
  const marketScenarios = activeIsJoint ? flattenRunScenarios([activeScenario]) : null;
  const viewScenario = activeIsJoint
    ? (marketScenarios.find((m) => m.marketId === activeMarketId) || marketScenarios[0])
    : activeScenario;
  const viewScenarios = activeIsJoint ? marketScenarios : scenarios;
  const activeMarket = activeIsJoint ? (viewScenario?.marketId ?? null) : null;
  const yearObj = viewScenario?.years?.find((y) => String(y.year) === String(activeYear)) || viewScenario?.years?.[0];
  const result = viewScenario && yearObj ? results?.[viewScenario.name]?.[String(yearObj.year)] : null;
  const displayResult = yearObj ? (result || buildDraftResult(yearObj)) : null;
  const hasEditedChanges = loadedConfigRef.current ? !configsEqual(config, loadedConfigRef.current) : false;
  // "Update existing model" is only offered when initialTemplateId names a real
  // model in the loaded library — a session restored without a source model
  // carries a SESSION id there, which is not an updatable model target.
  const canUpdateSourceModel = Boolean(initialTemplateId && templates.some((item) => item.id === initialTemplateId));
  const validationIssues = validateScenario(viewScenario, enabledFeatures);
  // Joint-equilibrium convergence diagnostics — present-guarded summary rows the
  // backend stamps only on cyclic-SCC markets; empty (inert) for a flat run.
  const jointRows = jointRowsFromSummary(summary);
  const jointProblems = jointProblemsFromRows(jointRows);
  const activeJointRow = jointRowForScenario(jointRows, viewScenario?.name);

  const commitConfig = (updater) => {
    setConfig((prev) => {
      const next = typeof updater === "function" ? updater(prev) : updater;
      configRef.current = next;
      return next;
    });
  };

  // Replace the active scenario's year list. For a flat scenario that is
  // `scenario.years`; for a JOINT scenario it is the SELECTED market's
  // `markets[i].years`. `scenarioPatch` (flat only) preserves the pre-joint
  // saveScenarioYear behaviour of spreading the scenario-level draft. When
  // activeMarket is null (every single-market scenario) the else branch is the
  // exact old handler body, so flat edits are byte-for-byte unchanged.
  const mapActiveYears = (prev, mapYears, scenarioPatch = null) => ({
    ...prev,
    scenarios: prev.scenarios.map((scenario) => {
      if (scenario.id !== activeScenario.id) return scenario;
      if (activeMarket != null) {
        return {
          ...scenario,
          markets: (scenario.markets || []).map((market) =>
            String(market.market_id) === String(activeMarket)
              ? { ...market, years: mapYears(market.years || []) }
              : market
          ),
        };
      }
      return { ...scenario, ...(scenarioPatch || {}), years: mapYears(scenario.years) };
    }),
  });

  const updateYear = (newYear) => {
    commitConfig((prev) =>
      mapActiveYears(prev, (years) =>
        years.map((year) =>
          String(year.year) === String(yearObj.year) ? { ...year, ...newYear } : year
        )
      )
    );
  };

  const updateScenario = (patch) => {
    commitConfig((prev) => ({
      ...prev,
      scenarios: prev.scenarios.map((scenario) =>
        scenario.id === activeScenario.id ? { ...scenario, ...patch } : scenario
      ),
    }));
  };

  // Config write-back for the Canvas tab. Both reuse the App's existing
  // flat-vs-joint routing: updateScenarioYears delegates to mapActiveYears
  // (which targets the active market's years for a joint scenario, or the flat
  // scenario's years otherwise), and updateScenarioSectors mirrors it for the
  // scenario/market-level sectors list. This keeps ALL config-mutation routing
  // in the App — the Canvas only supplies pure array transforms — so an edit on
  // the Canvas lands in exactly the same place the Model forms edit.
  const updateScenarioYears = (mapYears) => {
    commitConfig((prev) => mapActiveYears(prev, mapYears));
  };

  const updateScenarioSectors = (mapSectors) => {
    commitConfig((prev) => ({
      ...prev,
      scenarios: prev.scenarios.map((scenario) => {
        if (scenario.id !== activeScenario.id) return scenario;
        if (activeMarket != null) {
          return {
            ...scenario,
            markets: (scenario.markets || []).map((market) =>
              String(market.market_id) === String(activeMarket)
                ? { ...market, sectors: mapSectors(market.sectors || []) }
                : market
            ),
          };
        }
        return { ...scenario, sectors: mapSectors(scenario.sectors || []) };
      }),
    }));
  };

  const saveAsSession = async () => {
    const suggested = activeScenario?.name ? `${activeScenario.name} session` : "Session";
    const name = (window.prompt("Save this working config as a session named:", suggested) || "").trim();
    if (!name) return;
    setStatus("Saving session…");
    try {
      const response = await fetch("/api/session", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name, config: configRef.current, source_model_id: initialTemplateId || null }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Session save failed.");
      setStatus("Session saved");
    } catch (error) {
      setStatus("Session save failed");
    }
  };

  // Promote the current working config back into the MODEL library via POST
  // /api/model (model_id present => UPDATE the source model, absent => NEW
  // model). The source model id is initialTemplateId, but only when it names a
  // real model in the loaded templates list — a session restored without a
  // source model has an initialTemplateId that is a SESSION id, which must not
  // be offered as an update target (see canUpdateSourceModel below).
  const saveAsModel = async (asNew) => {
    const suggested = activeScenario?.name || "Model";
    const prompt = asNew ? "Save as a NEW model named:" : "Update the source model — save it as model named:";
    const name = (window.prompt(prompt, suggested) || "").trim();
    if (!name) return;
    setStatus("Saving model…");
    try {
      const body = { name, config: configRef.current };
      if (!asNew && canUpdateSourceModel) body.model_id = initialTemplateId;
      const response = await fetch("/api/model", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "Model save failed.");
      setStatus(asNew ? "Model saved" : "Model updated");
    } catch (error) {
      setStatus("Model save failed");
    }
  };

  const addScenario = () => {
    const nextIndex = (scenarios || []).length + 1;
    const nextScenario = makeBlankScenario(nextIndex, enabledFeatures);
    commitConfig((prev) => ({
      ...prev,
      scenarios: [...prev.scenarios, nextScenario],
    }));
    setActiveScenarioId(nextScenario.id);
    setActiveYear(String(nextScenario.years[0]?.year || "2030"));
    setSelPart(null);
    setStatus("Scenario added");
  };

  const duplicateScenario = () => {
    if (!activeScenario) return;
    const nextScenario = structuredClone(activeScenario);
    nextScenario.id = `custom_scenario_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    nextScenario.name = `${activeScenario.name} Copy`;
    commitConfig((prev) => ({
      ...prev,
      scenarios: [...prev.scenarios, nextScenario],
    }));
    setActiveScenarioId(nextScenario.id);
    setActiveYear(String(nextScenario.years?.[0]?.year || "2030"));
    setSelPart(null);
    setStatus("Duplicated");
  };

  const removeScenario = () => {
    if (!activeScenario || scenarios.length <= 1) return;
    const remaining = scenarios.filter((scenario) => scenario.id !== activeScenario.id);
    commitConfig((prev) => ({
      ...prev,
      scenarios: remaining,
    }));
    setActiveScenarioId(remaining[0]?.id || null);
    setActiveYear(String(remaining[0]?.years?.[0]?.year || ""));
    setSelPart(null);
    setStatus("Removed");
  };

  const addYear = () => {
    if (!viewScenario) return;
    const existingYears = (viewScenario.years || []).map((item) => Number(item.year)).filter(Number.isFinite);
    const nextYear = existingYears.length ? Math.max(...existingYears) + 5 : 2030;
    const templateParticipants = yearObj?.participants?.length
      ? yearObj.participants.map((participant) => ({ ...participant }))
      : [makeBlankParticipant(1, enabledFeatures)];
    const nextYearConfig = {
      ...makeBlankYear(nextYear),
      participants: templateParticipants,
    };

    commitConfig((prev) => mapActiveYears(prev, (years) => [...years, nextYearConfig]));
    setActiveYear(String(nextYear));
  };

  const saveScenarioYear = (scenarioDraft, yearDraft, originalYear) => {
    if (!viewScenario) return;
    commitConfig((prev) =>
      mapActiveYears(
        prev,
        (years) =>
          years.map((item) =>
            String(item.year) === String(originalYear) ? { ...yearDraft } : item
          ),
        scenarioDraft
      )
    );
    setActiveYear(String(yearDraft.year));
    setStatus("Saved");
  };

  const updateYearSeriesValue = (field, valuesByYear) => {
    if (!viewScenario) return;
    commitConfig((prev) =>
      mapActiveYears(prev, (years) =>
        years.map((item) => ({
          ...item,
          [field]: valuesByYear[String(item.year)] ?? item[field],
        }))
      )
    );
    setStatus("Updated");
  };

  const removeYear = () => {
    if (!viewScenario || (viewScenario.years || []).length <= 1) return;
    const nextYears = viewScenario.years.filter((item) => String(item.year) !== String(yearObj.year));
    commitConfig((prev) => mapActiveYears(prev, () => nextYears));
    setActiveYear(String(nextYears[0]?.year || ""));
    setSelPart(null);
  };

  const dragSupply = (newQ) => {
    const clamped = Math.max(0, newQ);
    if (yearObj.auction_mode === "explicit") {
      updateYear({ ...yearObj, auction_offered: clamped });
    } else {
      const free = yearObj.participants.reduce(
        (sum, participant) => sum + (participant.initial_emissions || 0) * (participant.free_allocation_ratio || 0),
        0
      );
      updateYear({ ...yearObj, total_cap: clamped + free });
    }
  };

  const runBaseScenario = () => {
    const baseConfig = structuredClone(loadedConfigRef.current || configRef.current);
    setConfig(baseConfig);
    configRef.current = baseConfig;
    runSimulation(baseConfig);
  };

  const runAllScenarios = () => {
    runSimulation(configRef.current);
  };

  const loadTemplateIntoEditor = (templateId) => {
    const template = templates.find((item) => item.id === templateId);
    if (!template || !activeScenario) return;
    const importedScenarios = importTemplateScenarios(
      template.config,
      configRef.current?.scenarios || [],
      activeScenario.id
    );
    if (!importedScenarios.length) {
      setStatus("Load failed");
      return;
    }
    const [replacementScenario, ...additionalScenarios] = importedScenarios;
    const nextConfig = {
      ...structuredClone(configRef.current || { scenarios: [] }),
      scenarios: (configRef.current?.scenarios || []).flatMap((scenario) => {
        if (scenario.id !== activeScenario.id) return [scenario];
        return [replacementScenario, ...additionalScenarios];
      }),
    };
    setConfig(nextConfig);
    configRef.current = nextConfig;
    loadedConfigRef.current = structuredClone(nextConfig);
    setResults({});
    setSummary([]);
    setAnalysis([]);
    setActiveScenarioId(replacementScenario?.id || null);
    setActiveYear(replacementScenario?.years?.[0]?.year || null);
    setSelPart(null);
    setValidationTarget(null);
    setStatus("Loaded");
  };

  const navigateValidationIssue = (issue) => {
    const target = issue?.target;
    if (!target) return;
    if (target.year) {
      setActiveYear(String(target.year));
    }
    if (target.participantName) {
      const targetYear = viewScenario?.years?.find((item) => String(item.year) === String(target.year || activeYear)) || yearObj;
      const participantIndex = (targetYear?.participants || []).findIndex((item) => item.name === target.participantName);
      setSelPart(participantIndex >= 0 ? participantIndex : null);
    } else {
      setSelPart(null);
    }
    if (target.section && target.section !== "validation") {
      setValidationTarget({ ...target, token: Date.now() });
      setActiveSection(target.section);
      setStatus("Opened");
      return;
    }
    setStatus("Focused");
  };

  // "Tabs: ... if a tab would be empty, hide it" — core guide content is
  // unconditional (see GuideView.jsx), so this is always true today; the
  // check stays generic rather than hardcoded so a manifest-scoped shell
  // with no core content would correctly drop the tab.
  const showGuideTab = hasGuideContent(enabledFeatures);

  if (!activeScenario || !yearObj || !displayResult) {
    if (activeSection === "guide") {
      return (
        <div className="app">
          <Header
            scenarios={scenarios}
            templates={templates}
            activeId={null}
            onSelectScenario={setActiveScenarioId}
            activeSection={activeSection}
            onSelectSection={setActiveSection}
            onAddScenario={addScenario}
            onDuplicateScenario={duplicateScenario}
            onRemoveScenario={removeScenario}
            onLoadTemplate={loadTemplateIntoEditor}
            onSaveScenario={saveActiveScenarioToLibrary}
            onSaveSession={saveAsSession}
            onSaveModel={saveAsModel}
            canUpdateModel={canUpdateSourceModel}
            status={status}
            showGuideTab={showGuideTab}
            hideLoadTemplate={enabledFeatures != null}
          />
          <GuideView enabledFeatures={enabledFeatures} />
        </div>
      );
    }
    return <div className="wb"><p>{status}</p></div>;
  }

  return (
    <div className="app">
      <Header
        scenarios={scenarios}
        templates={templates}
        activeId={activeScenario.id}
        onSelectScenario={setActiveScenarioId}
        activeSection={activeSection}
        onSelectSection={setActiveSection}
        onAddScenario={addScenario}
        onDuplicateScenario={duplicateScenario}
        onRemoveScenario={removeScenario}
        onLoadTemplate={loadTemplateIntoEditor}
        onSaveScenario={saveActiveScenarioToLibrary}
        onSaveSession={saveAsSession}
        onSaveModel={saveAsModel}
        canUpdateModel={canUpdateSourceModel}
        status={status}
        showGuideTab={showGuideTab}
        hideLoadTemplate={enabledFeatures != null}
      />

      {serverWarnings.length > 0 && (
        <div className="server-warnings-banner">
          <span className="server-warnings-icon">⚠</span>
          <div className="server-warnings-list">
            {serverWarnings.map((w, i) => (
              <div key={i} className="server-warning-item">{w}</div>
            ))}
          </div>
          <button
            className="server-warnings-close"
            onClick={() => setServerWarnings([])}
            title="Dismiss"
          >✕</button>
        </div>
      )}

      {activeIsJoint && <JointNonConvergenceBanner problems={jointProblems} />}

      {activeIsJoint && (
        <div className="wb">
          <nav className="hdr-scenarios">
            {marketScenarios.map((market) => (
              <button
                key={market.id}
                type="button"
                className={"pill-btn " + (viewScenario?.id === market.id ? "on" : "")}
                style={{ "--c": market.color }}
                onClick={() => {
                  setActiveMarketId(market.marketId);
                  setActiveYear(String(market.years?.[0]?.year || activeYear || ""));
                  setSelPart(null);
                }}
              >
                <i className="sw" style={{ background: market.color }}></i>Market {market.marketId}
              </button>
            ))}
          </nav>
          <JointConvergenceCard row={activeJointRow} />
          <SectorInteraction summary={summary} scenarioName={activeScenario?.name} />
        </div>
      )}

      {activeSection === "build" && (
        <BuildView
          scenario={viewScenario}
          yearObj={yearObj}
          onYearChange={(year) => { setActiveYear(year); setSelPart(null); }}
          activeYear={activeYear}
          updateYear={updateYear}
          updateScenario={updateScenario}
          addYear={addYear}
          removeYear={removeYear}
          onSave={saveScenarioYear}
          onUpdateYearSeries={updateYearSeriesValue}
          onRunBase={runBaseScenario}
          onRunEdited={() => runSimulation()}
          onRunAll={runAllScenarios}
          hasEditedChanges={hasEditedChanges}
          navigationTarget={validationTarget}
          enabledFeatures={enabledFeatures}
          manifest={manifest}
        />
      )}

      {activeSection === "canvas" && (
        <CanvasView
          key={viewScenario?.id}
          scenario={viewScenario}
          activeYear={activeYear}
          updateScenarioYears={updateScenarioYears}
          updateScenarioSectors={updateScenarioSectors}
        />
      )}

      {activeSection === "validation" && (
        <ValidationView
          scenario={viewScenario}
          activeYear={activeYear}
          onYearChange={(year) => { setActiveYear(year); setSelPart(null); }}
          validationIssues={validationIssues}
          onNavigateIssue={navigateValidationIssue}
        />
      )}

      {activeSection === "analysis" && (
        <AnalysisView
          scenario={viewScenario}
          yearObj={yearObj}
          onYearChange={(year) => { setActiveYear(year); setSelPart(null); }}
          activeYear={activeYear}
          result={displayResult}
          results={results}
          scenarios={viewScenarios}
          stacked={stacked}
          onToggleStacked={() => setStacked((value) => !value)}
          dragSupply={dragSupply}
          selPart={selPart}
          setSelPart={setSelPart}
          analysis={analysis}
          summary={summary}
          enabledFeatures={enabledFeatures}
        />
      )}

      {activeSection === "scenario" && (
        <Compare scenarios={viewScenarios} results={results} activeYear={activeYear} onYear={setActiveYear} />
      )}

      {activeSection === "guide" && <GuideView enabledFeatures={enabledFeatures} />}

      <Tweaks open={tweaksOpen} state={tweakState} setState={setTweakState} />
    </div>
  );
}
