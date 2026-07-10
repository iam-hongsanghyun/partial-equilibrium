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
import { GuideView } from "./components/GuideView.jsx";

export default function App({ enabledFeatures = null } = {}) {
  const [templates, setTemplates] = useS([]);
  const [config, setConfig] = useS({ scenarios: [] });
  const [results, setResults] = useS({});
  const [summary, setSummary] = useS([]);
  const [analysis, setAnalysis] = useS([]);
  const [activeScenarioId, setActiveScenarioId] = useS(null);
  const [activeYear, setActiveYear] = useS(null);
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
        payload.templates?.find((item) => item.id === "example")?.config
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
      setActiveScenarioId(firstScenario?.id || null);
      setActiveYear(firstScenario?.years?.[0]?.year || null);
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
      if (scenario && !scenario.years.some((y) => String(y.year) === String(activeYear))) {
        setActiveYear(scenario.years?.[0]?.year || null);
      }
      setStatus("Complete");
    } catch (error) {
      setStatus("Run failed");
    }
  }

  const scenarios = config.scenarios || [];
  const activeScenario = scenarios.find((s) => s.id === activeScenarioId) || scenarios[0];
  const yearObj = activeScenario?.years?.find((y) => String(y.year) === String(activeYear)) || activeScenario?.years?.[0];
  const result = activeScenario && yearObj ? results?.[activeScenario.name]?.[String(yearObj.year)] : null;
  const displayResult = yearObj ? (result || buildDraftResult(yearObj)) : null;
  const hasEditedChanges = loadedConfigRef.current ? !configsEqual(config, loadedConfigRef.current) : false;
  const validationIssues = validateScenario(activeScenario, enabledFeatures);

  const commitConfig = (updater) => {
    setConfig((prev) => {
      const next = typeof updater === "function" ? updater(prev) : updater;
      configRef.current = next;
      return next;
    });
  };

  const updateYear = (newYear) => {
    commitConfig((prev) => ({
      ...prev,
      scenarios: prev.scenarios.map((scenario) =>
        scenario.id !== activeScenario.id
          ? scenario
          : {
              ...scenario,
              years: scenario.years.map((year) =>
                String(year.year) === String(yearObj.year) ? { ...year, ...newYear } : year
              ),
            }
      ),
    }));
  };

  const updateScenario = (patch) => {
    commitConfig((prev) => ({
      ...prev,
      scenarios: prev.scenarios.map((scenario) =>
        scenario.id === activeScenario.id ? { ...scenario, ...patch } : scenario
      ),
    }));
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
    if (!activeScenario) return;
    const existingYears = activeScenario.years.map((item) => Number(item.year)).filter(Number.isFinite);
    const nextYear = existingYears.length ? Math.max(...existingYears) + 5 : 2030;
    const templateParticipants = yearObj?.participants?.length
      ? yearObj.participants.map((participant) => ({ ...participant }))
      : [makeBlankParticipant(1, enabledFeatures)];
    const nextYearConfig = {
      ...makeBlankYear(nextYear),
      participants: templateParticipants,
    };

    commitConfig((prev) => ({
      ...prev,
      scenarios: prev.scenarios.map((scenario) =>
        scenario.id !== activeScenario.id
          ? scenario
          : { ...scenario, years: [...scenario.years, nextYearConfig] }
      ),
    }));
    setActiveYear(String(nextYear));
  };

  const saveScenarioYear = (scenarioDraft, yearDraft, originalYear) => {
    if (!activeScenario) return;
    commitConfig((prev) => ({
      ...prev,
      scenarios: prev.scenarios.map((scenario) =>
        scenario.id !== activeScenario.id
          ? scenario
          : {
              ...scenario,
              ...scenarioDraft,
              years: scenario.years.map((item) =>
                String(item.year) === String(originalYear) ? { ...yearDraft } : item
              ),
            }
      ),
    }));
    setActiveYear(String(yearDraft.year));
    setStatus("Saved");
  };

  const updateYearSeriesValue = (field, valuesByYear) => {
    if (!activeScenario) return;
    commitConfig((prev) => ({
      ...prev,
      scenarios: prev.scenarios.map((scenario) =>
        scenario.id !== activeScenario.id
          ? scenario
          : {
              ...scenario,
              years: scenario.years.map((item) => ({
                ...item,
                [field]: valuesByYear[String(item.year)] ?? item[field],
              })),
            }
      ),
    }));
    setStatus("Updated");
  };

  const removeYear = () => {
    if (!activeScenario || activeScenario.years.length <= 1) return;
    const nextYears = activeScenario.years.filter((item) => String(item.year) !== String(yearObj.year));
    commitConfig((prev) => ({
      ...prev,
      scenarios: prev.scenarios.map((scenario) =>
        scenario.id !== activeScenario.id ? scenario : { ...scenario, years: nextYears }
      ),
    }));
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
      const targetYear = activeScenario?.years?.find((item) => String(item.year) === String(target.year || activeYear)) || yearObj;
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
            status={status}
          />
          <GuideView />
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
        status={status}
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

      {activeSection === "build" && (
        <BuildView
          scenario={activeScenario}
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
        />
      )}

      {activeSection === "validation" && (
        <ValidationView
          scenario={activeScenario}
          activeYear={activeYear}
          onYearChange={(year) => { setActiveYear(year); setSelPart(null); }}
          validationIssues={validationIssues}
          onNavigateIssue={navigateValidationIssue}
        />
      )}

      {activeSection === "analysis" && (
        <AnalysisView
          scenario={activeScenario}
          yearObj={yearObj}
          onYearChange={(year) => { setActiveYear(year); setSelPart(null); }}
          activeYear={activeYear}
          result={displayResult}
          results={results}
          scenarios={scenarios}
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
        <Compare scenarios={scenarios} results={results} activeYear={activeYear} onYear={setActiveYear} />
      )}

      {activeSection === "guide" && <GuideView />}

      <Tweaks open={tweaksOpen} state={tweakState} setState={setTweakState} />
    </div>
  );
}
