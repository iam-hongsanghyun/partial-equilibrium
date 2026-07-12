import { useEffect, useState } from "react";

// Backend param.type vocabulary is Python-style (config_io ground truth):
// "str" | "float" | "int" | "bool" | "list" | "dict" | "enum".
const COMPLEX_TYPES = new Set(["list", "dict"]);
const NUMERIC_TYPES = new Set(["float", "int"]);

// One field renderer, branching only on the declared param `type` — never on
// block identity or param name. New block kinds automatically get a working
// form as long as their ParamSpec.type is one of the handled types.
function ParamField({ spec, value, onChange }) {
  if (spec.type === "bool") {
    return (
      <label>
        <span className="ekey">
          {spec.name.replaceAll("_", " ")}
          {spec.unit ? ` (${spec.unit})` : ""}
        </span>
        <input
          type="checkbox"
          checked={!!value}
          onChange={(event) => onChange(event.target.checked)}
        />
        {spec.description && <span className="cell-note">{spec.description}</span>}
      </label>
    );
  }
  if (spec.type === "enum") {
    return (
      <label>
        <span className="ekey">
          {spec.name.replaceAll("_", " ")}
          {spec.unit ? ` (${spec.unit})` : ""}
        </span>
        <select value={value ?? spec.default ?? ""} onChange={(event) => onChange(event.target.value)}>
          {(spec.enum || []).map((option) => (
            <option key={option} value={option}>{option}</option>
          ))}
        </select>
        {spec.description && <span className="cell-note">{spec.description}</span>}
      </label>
    );
  }
  if (NUMERIC_TYPES.has(spec.type)) {
    return (
      <label>
        <span className="ekey">
          {spec.name.replaceAll("_", " ")}
          {spec.unit ? ` (${spec.unit})` : ""}
        </span>
        <input
          type="number"
          step={spec.type === "int" ? 1 : "any"}
          min={spec.min ?? undefined}
          max={spec.max ?? undefined}
          value={value ?? ""}
          onChange={(event) =>
            onChange(
              event.target.value === ""
                ? null
                : spec.type === "int"
                  ? parseInt(event.target.value, 10)
                  : Number(event.target.value)
            )
          }
        />
        {spec.description && <span className="cell-note">{spec.description}</span>}
      </label>
    );
  }
  if (COMPLEX_TYPES.has(spec.type)) {
    return <JsonField spec={spec} value={value} onChange={onChange} />;
  }
  // "str" (and anything else unrecognized) — plain text input.
  return (
    <label>
      <span className="ekey">
        {spec.name.replaceAll("_", " ")}
        {spec.unit ? ` (${spec.unit})` : ""}
      </span>
      <input
        type="text"
        value={value ?? ""}
        onChange={(event) => onChange(event.target.value)}
      />
      {spec.description && <span className="cell-note">{spec.description}</span>}
    </label>
  );
}

// "list"/"dict" params are structured values (arrays or keyed maps) with no
// fixed shape in the catalogue — edited as JSON text, parsed on blur so
// partial edits don't get clobbered mid-keystroke.
function JsonField({ spec, value, onChange }) {
  const [text, setText] = useState(() => JSON.stringify(value ?? spec.default ?? null, null, 2));
  const [invalid, setInvalid] = useState(false);

  useEffect(() => {
    setText(JSON.stringify(value ?? spec.default ?? null, null, 2));
    setInvalid(false);
  }, [value, spec.default]);

  const commit = () => {
    try {
      const parsed = JSON.parse(text);
      setInvalid(false);
      onChange(parsed);
    } catch (error) {
      setInvalid(true);
    }
  };

  return (
    <label className="editor-span-2">
      <span className="ekey">
        {spec.name.replaceAll("_", " ")} ({spec.type})
      </span>
      <textarea
        className="builder-textarea"
        value={text}
        onChange={(event) => setText(event.target.value)}
        onBlur={commit}
      />
      {invalid && <span className="cell-note composer-field-error">Invalid JSON — edit not applied.</span>}
      {spec.description && <span className="cell-note">{spec.description}</span>}
    </label>
  );
}

function ParamPanel({ node, block, onChangeParam, onRemoveNode }) {
  if (!node || !block) {
    return (
      <div className="builder-card composer-param-empty">
        <div className="builder-card-head">
          <div>
            <div className="eyebrow">Parameters</div>
            <h4>No block selected</h4>
          </div>
        </div>
        <p className="muted">Select a block on the canvas to edit its parameters.</p>
      </div>
    );
  }
  return (
    <div className="builder-card">
      <div className="builder-card-head">
        <div>
          <div className="eyebrow">{block.category}</div>
          <h4>{block.label}</h4>
        </div>
        {onRemoveNode && <button className="ghost-btn danger-btn" onClick={onRemoveNode}>Remove node</button>}
      </div>
      {block.doc && <p className="muted composer-param-doc">{block.doc}</p>}
      <div className="builder-form-grid">
        {(block.params || []).map((spec) => (
          <ParamField
            key={spec.name}
            spec={spec}
            value={node.data.params?.[spec.name]}
            onChange={(nextValue) => onChangeParam(spec.name, nextValue)}
          />
        ))}
        {!(block.params || []).length && <p className="muted">This block has no configurable parameters.</p>}
      </div>
    </div>
  );
}

export { ParamPanel };
