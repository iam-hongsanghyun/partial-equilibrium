// Elastic baseline feature (Option A: price-elastic baseline). Owns the
// scenario-level reference_carbon_price field. Extracted verbatim from
// frontend/src/components/Editor.jsx, where it renders inline inside the
// Hotelling approach-params block (its pre-existing, if slightly unusual,
// visibility gate — preserved rather than "fixed", per the WO-F1 pixel/DOM
// equivalence bar). The hotelling feature imports ReferenceCarbonPriceField
// directly to embed it at that exact position; see modules/hotelling/frontend.

export function ReferenceCarbonPriceField({ ctx }) {
  const { workingScenario, updateScenario } = ctx;
  return (
    <label>
      <span className="ekey">Reference carbon price (Option A) <span className="field-flag optional">optional</span></span>
      <input
        type="number"
        className="text"
        step="1"
        min="0"
        value={workingScenario.reference_carbon_price ?? 0.0}
        onChange={(e) => updateScenario({ reference_carbon_price: Math.max(0, parseFloat(e.target.value) || 0) })}
      />
      <span className="approach-params-hint">Price-elastic baseline anchor P_ref. Activity contracts when the price exceeds it. Set with each participant's output_price_elasticity. 0 = inelastic baseline (default).</span>
    </label>
  );
}

// ── Guide: pe-shell module section (only rendered when this model uses
// the price-elastic baseline — see frontend/src/components/GuideView.jsx).

function ElasticBaselineGuideSection() {
  return (
    <div className="guide-body">
      <p className="guide-lead">
        The <strong>price-elastic baseline</strong> (Option A) lets a participant's baseline
        activity — and therefore its baseline emissions — contract as the carbon price rises
        above a scenario-wide <strong>reference carbon price</strong> P_ref, using each
        participant's own <strong>output price elasticity</strong>.
      </p>
      <div className="guide-tip">
        <strong>Where to look:</strong> the reference carbon price is set inside "Modelling
        approach"; each participant's output price elasticity is set on the Participants step
        alongside its OBA fields.
      </div>
    </div>
  );
}

export default {
  id: "elastic_baseline",
  scenarioDefaults: {
    reference_carbon_price: 0.0,
  },
  approachOptions: [ReferenceCarbonPriceField],
  guideSections: [{ id: "module-elastic_baseline", tag: "ELB", title: "Price-elastic baseline", content: ElasticBaselineGuideSection }],
};
