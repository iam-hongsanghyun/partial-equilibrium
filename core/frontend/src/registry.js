// Frontend feature-module registry — the reviewed composition point that
// mirrors the backend wiring-literal doctrine (see docs/feature-modules-plan.md):
// a static literal, no dynamic registration, no import-order effects.
//
// Each feature's index.jsx default-exports a "fragment" object with the
// shape (all slots optional):
//   {
//     id: string,
//     scenarioDefaults: object,          // merged into makeBlankScenario()
//     participantDefaults: object,       // merged into makeBlankParticipant()
//     editorSections: [Component],       // scenario/market-level editor UI
//     participantEditorSections: [Component], // participant-level editor UI
//     approachOptions: [Component],      // model_approach-gated solver params
//     validators: [fn],                  // scenario -> issue[] (see AppShared.validateScenario)
//     guideSections: [{ id, tag, title, content: Component }],  // GuideView's
//       "Active modules" list (core/frontend/src/components/GuideView.jsx) — only
//       shown for a feature that is actually active, so a manifest-scoped pe
//       model only sees guide pages for the modules it uses. `content` takes
//       no props (it is a plain, non-`ctx` component, unlike every other slot
//       here — guide prose doesn't read live scenario state).
//   }
//
// WO-F1 wired the editor/config side (makeBlankScenario, makeBlankParticipant,
// validateScenario, and the Editor's editorSections / participantEditorSections
// / approachOptions slots). WO-F2 wired the result side (summaryPanels /
// analysisBullets / resultStats). WO-F3 wires the pe shell itself: the
// approach lock and "Banking, borrowing & expectations" visibility
// (core/frontend/src/components/Editor.jsx) and guideSections (this file / GuideView.jsx).

import msr from "@features/msr/frontend/index.jsx";
import ccr from "@features/ccr/frontend/index.jsx";
import cbam from "@features/cbam/frontend/index.jsx";
import sectors from "@features/sectors/frontend/index.jsx";
import oba from "@features/oba/frontend/index.jsx";
import price_controls from "@features/price_controls/frontend/index.jsx";
import banking from "@features/banking/frontend/index.jsx";
import hotelling from "@features/hotelling/frontend/index.jsx";
import nash_cournot from "@features/nash_cournot/frontend/index.jsx";
import transmission from "@features/transmission/frontend/index.jsx";
import elastic_baseline from "@features/elastic_baseline/frontend/index.jsx";
import calibration from "@features/calibration/frontend/index.jsx";
import endogenous_investment from "@features/endogenous_investment/frontend/index.jsx";

export const FEATURES = Object.freeze({
  msr,
  ccr,
  cbam,
  sectors,
  oba,
  price_controls,
  banking,
  hotelling,
  nash_cournot,
  transmission,
  elastic_baseline,
  calibration,
  endogenous_investment,
});

// enabledFeatures === null means "all features" (today's default shell).
// A provided array restricts composition to those ids, in FEATURES'
// (registry-literal) order — the array's own order is not significant.
export function activeFeatureIds(enabledFeatures) {
  if (enabledFeatures == null) return Object.keys(FEATURES);
  const enabled = new Set(enabledFeatures);
  return Object.keys(FEATURES).filter((id) => enabled.has(id));
}

// Flatten a named slot across active features, in registry order. Pass
// featureIds to scope the collection to a subset of features (used where a
// host location renders only one feature's contribution to a slot, e.g. the
// "Sectors" panel is sectors-only even though other features also
// contribute editorSections elsewhere in the editor).
export function collectSlot(enabledFeatures, slotName, featureIds = null) {
  const active = activeFeatureIds(enabledFeatures);
  const scoped = featureIds ? active.filter((id) => featureIds.includes(id)) : active;
  return scoped
    .map((id) => FEATURES[id])
    .filter(Boolean)
    .flatMap((feature) => feature[slotName] || []);
}
