// Shared editor primitives — reused by the core Editor (Editor.jsx) and by
// feature modules (modules/*/frontend) that contribute editorSections,
// participantEditorSections, or approachOptions. Kept in a neutral module
// (rather than inside Editor.jsx) so features can import them without a
// circular dependency on Editor.jsx, which itself imports the feature
// registry.

export function CollapsibleGroup({ title, defaultOpen = true, children, badge = null }) {
  return (
    <details className="cg" open={defaultOpen || undefined}>
      <summary className="cg-summary">
        <span className="cg-title">{title}</span>
        {badge ? <span className="cg-badge">{badge}</span> : null}
        <span className="cg-chevron">▾</span>
      </summary>
      <div className="cg-body">{children}</div>
    </details>
  );
}

export function numInput(value, onValueChange, step = 1, min = undefined, title = "") {
  return (
    <input
      type="number"
      className="num"
      value={value}
      step={step}
      min={min}
      title={title}
      onChange={(event) => onValueChange(Number(event.target.value))}
    />
  );
}

export function fieldWithPathButton(label, onClick, required = false, optional = false) {
  return (
    <span className="field-title-row">
      <span>
        {label}{" "}
        {required ? <span className="field-flag required">required</span> : null}
        {optional ? <span className="field-flag optional">optional</span> : null}
      </span>
      <button className="field-path-btn" type="button" onClick={onClick}>Edit path</button>
    </span>
  );
}

// A single start/end-year x start/end-value trajectory row, as used by the
// cap trajectory (core) and by the price_controls feature's floor/ceiling
// trajectories. One implementation, reused rather than duplicated.
export function TrajectoryRangeRow({ scenario, updateScenario, rowKey, label, hint, unit }) {
  const traj = scenario[rowKey] || {};
  const active = !!(traj.start_year && traj.end_year && traj.start_value !== undefined && traj.end_value !== undefined);
  return (
    <div className="traj-section">
      <div className="traj-head">
        <span className="traj-label">{label}</span>
        <span className="approach-params-hint">{hint}</span>
        {active
          ? <button type="button" className="ghost-btn" style={{fontSize:11, padding:"2px 8px"}} onClick={() => updateScenario({ [rowKey]: {} })}>Clear</button>
          : <button type="button" className="ghost-btn on" style={{fontSize:11, padding:"2px 8px"}} onClick={() => updateScenario({ [rowKey]: { start_year: "2026", end_year: "2035", start_value: 0, end_value: 0 } })}>Enable</button>
        }
      </div>
      {active && (
        <div className="traj-row" style={{gridTemplateColumns:"80px 80px 110px 110px", gap: 8, padding: "8px 12px"}}>
          <div className="builder-form-field" style={{margin:0}}>
            <label style={{fontSize:11}}>Start year</label>
            <input type="text" value={traj.start_year ?? ""} onChange={(e) => updateScenario({ [rowKey]: { ...traj, start_year: e.target.value } })} />
          </div>
          <div className="builder-form-field" style={{margin:0}}>
            <label style={{fontSize:11}}>End year</label>
            <input type="text" value={traj.end_year ?? ""} onChange={(e) => updateScenario({ [rowKey]: { ...traj, end_year: e.target.value } })} />
          </div>
          <div className="builder-form-field" style={{margin:0}}>
            <label style={{fontSize:11}}>Start value ({unit})</label>
            <input type="number" step="1" value={traj.start_value ?? ""} onChange={(e) => updateScenario({ [rowKey]: { ...traj, start_value: +e.target.value } })} />
          </div>
          <div className="builder-form-field" style={{margin:0}}>
            <label style={{fontSize:11}}>End value ({unit})</label>
            <input type="number" step="1" value={traj.end_value ?? ""} onChange={(e) => updateScenario({ [rowKey]: { ...traj, end_value: +e.target.value } })} />
          </div>
        </div>
      )}
    </div>
  );
}
