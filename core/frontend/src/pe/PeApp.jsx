import { useEffect, useRef, useState } from "react";
import App from "../app.jsx";

// PE — model-scoped shell. Reached only via `?mode=pe` (see main.jsx).
// LANDING: a plain list of models from GET /api/templates (this file does
// not know or care how many there are — the backend example suite grows
// independently of this UI), with each entry's module chips filled in from
// GET /api/model-manifest?id=<id>, fetched in small concurrent batches and
// cached for the life of the shell (see fetchManifestsBatched / manifest
// cache below) so re-visiting the landing page never re-fetches. SELECTED:
// the same manifest (reused from cache when already fetched) is passed down
// whole to the SAME App component the default shell uses
// (App({ enabledFeatures, manifest, initialTemplateId })) so every
// registry-driven host (Editor's editorSections / participantEditorSections
// / approachOptions / the modelling-approach lock / the "Banking, borrowing
// & expectations" visibility, AnalysisView's analysisBullets /
// summaryPanels, ParticipantPanel's resultStats, GuideView's guideSections,
// AppShared's makeBlankScenario / makeBlankParticipant / validateScenario)
// filters automatically — this shell only supplies the manifest.
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

function SessionGroup({ sessions, onSelect, onRename, onDelete }) {
  if (!sessions.length) return null;
  return (
    <section className="panel">
      <div className="panel-head">
        <div>
          <div className="eyebrow">Resume</div>
          <h2>Saved sessions</h2>
          <p className="muted">Working configs saved from the editor. A session carries its full config, not just a model's structure.</p>
        </div>
      </div>
      <div className="builder-list">
        {sessions.map((session) => (
          // A wrapper grid (reusing .builder-list' gap) so the open button and
          // its rename/delete actions stack without a nested <button>.
          <div key={session.id} className="builder-list">
            <button
              type="button"
              className="builder-list-item"
              onClick={() => onSelect(session)}
            >
              <span>{session.name}</span>
              <span className="builder-item-meta">Session</span>
            </button>
            <div className="editor-actions">
              <button type="button" className="ghost-btn" onClick={() => onRename(session)}>Rename</button>
              <button type="button" className="ghost-btn danger-btn" onClick={() => onDelete(session)}>Delete</button>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}

function ModelLanding({ templates, manifests, sessions, status, error, onDismissError, onSelect, onSelectSession, onRenameSession, onDeleteSession }) {
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
        <SessionGroup sessions={sessions} onSelect={onSelectSession} onRename={onRenameSession} onDelete={onDeleteSession} />
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
  const [selected, setSelected] = useState(null); // { id, name, manifest, initialConfig?, sourceModelId? }
  const [sessions, setSessions] = useState([]);
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

  // List saved sessions for the "Saved sessions" restore strip. Re-fetched each
  // time we return to the landing (selected -> null) so a just-saved session
  // shows without a reload.
  useEffect(() => {
    if (selected) return;
    let cancelled = false;
    fetch("/api/sessions")
      .then((response) => response.json())
      .then((payload) => {
        if (!cancelled) setSessions(payload.sessions || []);
      })
      .catch(() => {
        if (!cancelled) setSessions([]);
      });
    return () => {
      cancelled = true;
    };
  }, [selected]);

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

  // Restore a saved session: load its full config (GET /api/session/<id>) and
  // open it in the SAME editor a model opens in, seeded with the session's
  // config. The shell is scoped by a manifest derived from that config (POST
  // /api/model-manifest), exactly as a model's manifest scopes it.
  async function selectSession(session) {
    setError(null);
    setStatus("Loading session…");
    try {
      const response = await fetch(`/api/session/${encodeURIComponent(session.id)}`);
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.error || "This session could not be loaded.");
      let manifest = null;
      try {
        const manifestResponse = await fetch("/api/model-manifest", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload.config),
        });
        if (manifestResponse.ok) manifest = await manifestResponse.json();
      } catch {
        manifest = null;
      }
      setSelected({
        id: session.id,
        name: session.name,
        manifest,
        initialConfig: payload.config,
        sourceModelId: payload.source_model_id || null,
      });
      setStatus("Loaded");
    } catch (err) {
      setError(err.message || "This session could not be loaded.");
      setStatus("Loaded");
    }
  }

  // Rename / delete a saved session in place (PATCH / DELETE /api/session/<id>),
  // updating the local list so the strip reflects the change without a reload.
  async function renameSession(session) {
    const name = (window.prompt("Rename session to:", session.name) || "").trim();
    if (!name || name === session.name) return;
    try {
      const response = await fetch(`/api/session/${encodeURIComponent(session.id)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name }),
      });
      if (!response.ok) throw new Error();
      setSessions((prev) => prev.map((item) => (item.id === session.id ? { ...item, name } : item)));
    } catch {
      setError("This session could not be renamed.");
    }
  }

  async function deleteSession(session) {
    if (!window.confirm(`Delete session "${session.name}"? This cannot be undone.`)) return;
    try {
      const response = await fetch(`/api/session/${encodeURIComponent(session.id)}`, { method: "DELETE" });
      if (!response.ok) throw new Error();
      setSessions((prev) => prev.filter((item) => item.id !== session.id));
    } catch {
      setError("This session could not be deleted.");
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
        sessions={sessions}
        status={status}
        error={error}
        onDismissError={() => setError(null)}
        onSelect={selectModel}
        onSelectSession={selectSession}
        onRenameSession={renameSession}
        onDeleteSession={deleteSession}
      />
    );
  }

  return (
    <div className="app">
      <ModelToolbar name={selected.name} features={selected.manifest?.features} onBack={backToModels} />
      <App
        key={selected.id}
        enabledFeatures={selected.manifest?.features || null}
        manifest={selected.manifest}
        initialTemplateId={selected.sourceModelId ?? selected.id}
        initialConfig={selected.initialConfig ?? null}
      />
    </div>
  );
}
