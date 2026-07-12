import { useEffect, useRef, useState } from "react";
import { PeModelView } from "./PeModelView.jsx";

// PE — model-scoped shell. Reached only via `?mode=pe` (see main.jsx).
// LANDING: a plain list of models from GET /api/templates (this file does
// not know or care how many there are — the backend example suite grows
// independently of this UI), with each entry's module chips filled in from
// GET /api/model-manifest?id=<id>, fetched in small concurrent batches and
// cached for the life of the shell (see fetchManifestsBatched / manifest
// cache below) so re-visiting the landing page never re-fetches. SELECTED:
// the model is shown as a LEFT-TO-RIGHT block diagram via PeModelView — the
// same shared ModelGraph canvas the composer uses, but MODULE-LOCKED (the
// market/mechanism structure is fixed by the loaded model) and DATA-EDITABLE
// (companies / sectors / technology options can be added, removed, and their
// values edited, two-way bound to the config through the graph's compile).
// The manifest still drives the ModelToolbar's module chips; the diagram
// itself is config-driven (a node/param renders iff the config declares it).
//
// No new CSS: reuses .hdr/.hdr-top/.hdr-brand/.hdr-tools (main Header),
// .panel/.panel-head/.eyebrow (AppShared/AppViews panels),
// .builder-list/.builder-list-item/.builder-item-meta (Editor's
// participant/technology picker lists), .hdr-scenarios (Header's pill row,
// reused as the chip strip inside each list item), .pill-btn (Header's
// scenario pills, reused here as plain module-name chips), .ghost-btn, and
// the .server-warnings-* banner (App's own run-warnings banner).

const MANIFEST_BATCH_SIZE = 6;

function sourceLabel(template) {
  if (template.source === "user") return "User model";
  if (template.source === "example") return "Example";
  return "Blank";
}

function ModuleChips({ manifest }) {
  if (!manifest) return null;
  const features = manifest.features || [];
  if (!features.length) return null;
  return (
    <span className="hdr-scenarios">
      {features.map((feature) => (
        <span key={feature} className="pill-btn on">{feature}</span>
      ))}
    </span>
  );
}

function ModelGroup({ eyebrow, title, description, templates, manifests, onSelect }) {
  if (!templates.length) return null;
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <div className="eyebrow">{eyebrow}</div>
          <h2>{title}</h2>
          <p className="muted">{description}</p>
        </div>
      </div>
      <div className="builder-list">
        {templates.map((template) => (
          <button
            key={template.id}
            type="button"
            className="builder-list-item"
            onClick={() => onSelect(template.id)}
          >
            <span>{template.name}</span>
            <span className="builder-item-meta">{sourceLabel(template)}</span>
            <ModuleChips manifest={manifests[template.id]} />
          </button>
        ))}
      </div>
    </section>
  );
}

function ModelLanding({ templates, manifests, status, error, onDismissError, onSelect }) {
  const examples = templates.filter((template) => template.source === "example");
  const userModels = templates.filter((template) => template.source === "user");
  const other = templates.filter((template) => template.source !== "example" && template.source !== "user");
  return (
    <div className="app">
      <header className="hdr">
        <div className="hdr-top">
          <div className="hdr-brand">
            <div>
              <div className="brand-title">Clearing — PE</div>
              <div className="brand-sub">{status}</div>
            </div>
          </div>
        </div>
      </header>
      {error && (
        <div className="server-warnings-banner">
          <span className="server-warnings-icon">⚠</span>
          <div className="server-warnings-list">
            <div className="server-warning-item">{error}</div>
          </div>
          <button className="server-warnings-close" onClick={onDismissError} title="Dismiss">✕</button>
        </div>
      )}
      <div className="wb">
        <section className="wb-hero">
          <div className="scenario-meta">
            <div className="eyebrow">Start</div>
            <h1>Choose a model</h1>
            <p className="lede">Select a model — the interface loads only that model's modules. Every model opens with only the mechanisms it actually uses; no unrelated MSR, CCR, CBAM, sector, or OBA sections.</p>
          </div>
        </section>
        <ModelGroup
          eyebrow="Start"
          title="Blank configuration"
          description="An empty scenario, built up from scratch."
          templates={other}
          manifests={manifests}
          onSelect={onSelect}
        />
        <ModelGroup
          eyebrow="Examples"
          title="Example models"
          description="Pre-built scenarios, each exercising a specific policy mechanism."
          templates={examples}
          manifests={manifests}
          onSelect={onSelect}
        />
        <ModelGroup
          eyebrow="Your models"
          title="Saved models"
          description="Models saved to the local registry."
          templates={userModels}
          manifests={manifests}
          onSelect={onSelect}
        />
        {!templates.length && status === "Loaded" && (
          <section className="panel">
            <div className="builder-empty large">No models found.</div>
          </section>
        )}
      </div>
    </div>
  );
}

function ModelToolbar({ name, features, onBack }) {
  return (
    <header className="hdr">
      <div className="hdr-top">
        <div className="hdr-brand">
          <div>
            <div className="brand-title">{name}</div>
            <div className="brand-sub">pe model</div>
          </div>
        </div>
        <div className="hdr-tools">
          <button className="ghost-btn" type="button" onClick={onBack}>Back to models</button>
        </div>
      </div>
      <div className="hdr-scenarios">
        {(features || []).map((feature) => (
          <span key={feature} className="pill-btn on">{feature}</span>
        ))}
      </div>
    </header>
  );
}

async function fetchManifest(templateId) {
  const response = await fetch(`/api/model-manifest?id=${encodeURIComponent(templateId)}`);
  const payload = await response.json();
  if (!response.ok) {
    throw new Error(payload.error || "This model's manifest could not be loaded.");
  }
  return payload;
}

export function PeApp() {
  const [templates, setTemplates] = useState([]);
  const [status, setStatus] = useState("Loading…");
  const [error, setError] = useState(null);
  const [selected, setSelected] = useState(null); // { id, name, manifest }
  // Manifest cache, keyed by template id — persists for the life of the pe
  // shell (this component never unmounts between landing <-> model views),
  // so both the landing chips and selectModel below reuse one fetch per id.
  const [manifests, setManifests] = useState({});
  const manifestsRef = useRef(manifests);
  manifestsRef.current = manifests;

  useEffect(() => {
    let cancelled = false;
    fetch("/api/templates")
      .then((response) => response.json())
      .then((payload) => {
        if (cancelled) return;
        setTemplates(payload.templates || []);
        setStatus("Loaded");
      })
      .catch(() => {
        if (!cancelled) setStatus("Load failed");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Lazily batch-fetch every template's manifest so the landing page can
  // show module chips per entry without one request-per-render or one giant
  // blocking Promise.all — small concurrent batches, cached as they land.
  useEffect(() => {
    if (!templates.length) return;
    let cancelled = false;
    const ids = templates.map((template) => template.id).filter((id) => !(id in manifestsRef.current));
    (async () => {
      for (let start = 0; start < ids.length; start += MANIFEST_BATCH_SIZE) {
        if (cancelled) return;
        const batch = ids.slice(start, start + MANIFEST_BATCH_SIZE);
        const results = await Promise.all(
          batch.map((id) => fetchManifest(id).then((manifest) => [id, manifest]).catch(() => [id, null]))
        );
        if (cancelled) return;
        setManifests((prev) => {
          const next = { ...prev };
          results.forEach(([id, manifest]) => {
            next[id] = manifest;
          });
          return next;
        });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [templates]);

  async function selectModel(templateId) {
    setError(null);
    setStatus("Loading model…");
    try {
      const manifest = manifestsRef.current[templateId] || (await fetchManifest(templateId));
      const template = templates.find((item) => item.id === templateId);
      setManifests((prev) => (prev[templateId] ? prev : { ...prev, [templateId]: manifest }));
      setSelected({
        id: templateId,
        name: template?.name || templateId,
        manifest,
      });
      setStatus("Loaded");
    } catch (err) {
      setError(err.message || "This model could not be loaded.");
      setStatus("Loaded");
    }
  }

  function backToModels() {
    setSelected(null);
    setError(null);
  }

  if (!selected) {
    return (
      <ModelLanding
        templates={templates}
        manifests={manifests}
        status={status}
        error={error}
        onDismissError={() => setError(null)}
        onSelect={selectModel}
      />
    );
  }

  return (
    <div className="app">
      <ModelToolbar name={selected.name} features={selected.manifest?.features} onBack={backToModels} />
      <PeModelView key={selected.id} templateId={selected.id} />
    </div>
  );
}
