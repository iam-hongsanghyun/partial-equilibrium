// Banking feature.
//
// No banking-specific editor UI exists in Editor.jsx today (see WO-F1 note:
// "Banking, borrowing & expectations" stays core because those fields also
// feed the expectations kernel and CBAM gap calculation, not just banking).
//
// ── Result-side: banking-equilibrium summary panel (WO-F2) ───────────────
// No component rendered payload.summary's "Banking Aggregate Bank" /
// "Banking Regime" / window / "Banking Floor Cancelled" columns before this
// order — new, additive panel. Unlike msr/ccr (whose columns are always
// present, defaulted to 0.0), these columns are only added to the summary
// row when the banking-equilibrium solver actually ran
// (simulation.py: `if "banking_aggregate_bank" in item`) — so the self-hide
// check here is column presence, not a zero check.

import { SummaryPathwayPanel, orderedSummaryRows } from "@core/components/ResultPrimitives.jsx";

const BANK_METRICS = [
  { key: "Banking Aggregate Bank", label: "Aggregate Bank (Mt)" },
  { key: "Banking Regime", label: "Regime", format: (value) => (value ?? "—") },
  { key: "Banking Window Start", label: "Window Start", format: (value) => (value == null ? "—" : String(value)) },
  { key: "Banking Window End", label: "Window End", format: (value) => (value == null ? "—" : String(value)) },
  { key: "Banking Floor Cancelled", label: "Floor Cancelled (Mt)" },
];

function BankPanel({ ctx }) {
  const { scenario, summary } = ctx;
  const rows = orderedSummaryRows(scenario, summary);
  const hasData = rows.some((row) => "Banking Aggregate Bank" in row);
  if (!hasData) return null;
  return (
    <SummaryPathwayPanel
      eyebrow="Banking equilibrium"
      title="Bank, regime, and window by year"
      description={`Solved intertemporal bank, arbitrage regime, and banking window, for ${scenario.name}.`}
      scenario={scenario}
      rows={rows}
      metrics={BANK_METRICS}
    />
  );
}

// ── Guide: pe-shell module section (only rendered when this model uses
// banking — see frontend/src/components/GuideView.jsx).

function BankingGuideSection() {
  return (
    <div className="guide-body">
      <p className="guide-lead">
        The <strong>Banking equilibrium</strong> approach solves for an intertemporal,
        arbitrage-free price path: participants may bank unused allowances for later years (and,
        if borrowing is enabled, draw on a future year's allocation today), and the solver finds
        the bank and price path where no one can profit from shifting compliance between years.
      </p>
      <p>
        Banking and borrowing are set per year in "Banking, borrowing &amp; expectations"
        (banking allowed, borrowing allowed and its limit) along with the
        <strong> expectation rule</strong> participants use to forecast future prices when
        deciding whether to bank.
      </p>
      <div className="guide-tip">
        <strong>Where to look:</strong> the solved aggregate bank, arbitrage regime, and banking
        window by year appear as their own panel on the Analysis tab.
      </div>
    </div>
  );
}

export default {
  id: "banking",
  summaryPanels: [BankPanel],
  guideSections: [{ id: "module-banking", tag: "BANK", title: "Banking equilibrium", content: BankingGuideSection }],
};
