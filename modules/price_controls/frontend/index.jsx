// Price controls feature — price floor/ceiling trajectories and the
// auction guardrail fields (cancelled allowances, reserve price, minimum
// bid coverage, unsold treatment). Extracted verbatim from
// frontend/src/components/Editor.jsx.
//
// editorSections[0] = floor/ceiling trajectory rows, rendered inside
// "Allocation & policy trajectories" alongside the core cap trajectory row
// (same TrajectoryRangeRow component, reused not duplicated).
// editorSections[1] = auction guardrail fields, rendered inside "Supply &
// price bounds" between the core allowance-bucket fields and the core
// price floor/ceiling fields — the exact position they held before
// extraction. "Cancelled allowances" was moved in here from Editor.jsx's
// core render (it was ungated there despite being price_controls-owned
// everywhere else — see CancelledAllowancesBullet below, which was already
// gated) as its first field, so the default (unscoped) shell's field order
// is unchanged (price_controls is always active there).

import { TrajectoryRangeRow, numInput, fieldWithPathButton } from "@core/components/EditorPrimitives.jsx";
import { fmt } from "@core/components/MarketChart.jsx";
import { describeUnsoldTreatment } from "@core/components/AppShared.jsx";

const PRICE_BOUND_TRAJECTORY_ROWS = [
  { key: "price_floor_trajectory", label: "Price floor trajectory", hint: "Rising price floor. Overrides per-year price_lower_bound.", unit: "$/t" },
  { key: "price_ceiling_trajectory", label: "Price ceiling trajectory", hint: "Rising/declining price ceiling. Overrides per-year price_upper_bound.", unit: "$/t" },
];

function PriceBoundTrajectories({ ctx }) {
  const { workingScenario, updateScenario } = ctx;
  return (
    <>
      {PRICE_BOUND_TRAJECTORY_ROWS.map((row) => (
        <TrajectoryRangeRow
          key={row.key}
          scenario={workingScenario}
          updateScenario={updateScenario}
          rowKey={row.key}
          label={row.label}
          hint={row.hint}
          unit={row.unit}
        />
      ))}
    </>
  );
}

function AuctionGuardrailFields({ ctx }) {
  const { workingYear, updateYear, openMarketSeriesEditor, yearFieldVisible = () => true } = ctx;
  return (
    <>
      {yearFieldVisible("cancelled_allowances") && (
      <label>
        <span className="ekey">{fieldWithPathButton("Cancelled allowances", () => openMarketSeriesEditor("cancelled_allowances"), false, true)}</span>
        {numInput(workingYear.cancelled_allowances || 0, (value) => updateYear({ cancelled_allowances: value }), 1, 0)}
      </label>
      )}
      {yearFieldVisible("auction_reserve_price") && (
      <label>
        <span className="ekey">{fieldWithPathButton("Auction reserve price", () => openMarketSeriesEditor("auction_reserve_price"), false, true)}</span>
        {numInput(workingYear.auction_reserve_price || 0, (value) => updateYear({ auction_reserve_price: value }), 1, 0)}
      </label>
      )}
      {yearFieldVisible("minimum_bid_coverage") && (
      <label>
        <span className="ekey">{fieldWithPathButton("Minimum bid coverage", () => openMarketSeriesEditor("minimum_bid_coverage"), false, true)}</span>
        {numInput(workingYear.minimum_bid_coverage || 0, (value) => updateYear({ minimum_bid_coverage: value }), 0.05, 0)}
      </label>
      )}
      {yearFieldVisible("unsold_treatment") && (
      <label>
        <span className="ekey">Unsold treatment <span className="field-flag optional">optional</span></span>
        <select
          value={workingYear.unsold_treatment || "reserve"}
          onChange={(event) => updateYear({ unsold_treatment: event.target.value })}
        >
          <option value="reserve">reserve</option>
          <option value="cancel">cancel</option>
          <option value="carry_forward">carry_forward</option>
        </select>
      </label>
      )}
    </>
  );
}

// ── Result-side: "Auction rules" analysis bullets (WO-F2) ────────────────
// Extracted verbatim from frontend/src/components/AppViews.jsx (AnalysisView,
// "Auction rules" list). analysisBullets[0..2] render at their original
// position (before the core "Reserved allowances" bullet); [3] renders
// between the core "Reserved allowances" and "Expectation rule" bullets —
// the exact interleaved order the list held before extraction.

function ReservePriceBullet({ ctx }) {
  const { yearObj } = ctx;
  return <li>Reserve price: {yearObj.auction_reserve_price > 0 ? `auction sales cannot clear below ${fmt.price(yearObj.auction_reserve_price)}.` : "no separate reserve price is active."}</li>;
}

function MinBidCoverageBullet({ ctx }) {
  const { yearObj } = ctx;
  return <li>Minimum bid coverage: {yearObj.minimum_bid_coverage > 0 ? `at least ${fmt.num(yearObj.minimum_bid_coverage * 100, 0)}% of offered volume must be covered by bids.` : "no bid-coverage threshold is active."}</li>;
}

function UnsoldTreatmentBullet({ ctx }) {
  const { yearObj } = ctx;
  return <li>Unsold treatment: {describeUnsoldTreatment(yearObj.unsold_treatment || "reserve")}.</li>;
}

function CancelledAllowancesBullet({ ctx }) {
  const { yearObj } = ctx;
  return <li>Cancelled allowances: {fmt.num(yearObj.cancelled_allowances || 0, 0)} are permanently removed from the annual cap.</li>;
}

// ── Guide: pe-shell module section (only rendered when this model uses
// price controls — see frontend/src/components/GuideView.jsx).

function PriceControlsGuideSection() {
  return (
    <div className="guide-body">
      <p className="guide-lead">
        <strong>Price controls</strong> add rising or falling price floor/ceiling trajectories
        on top of the per-year price bounds, plus auction guardrails: a
        <strong> reserve price</strong> below which auction volume goes unsold, a
        <strong> minimum bid coverage</strong> threshold, and a rule for what happens to
        <strong> unsold allowances</strong> (return to reserve, cancel, or carry forward).
      </p>
      <div className="guide-tip">
        <strong>Where to look:</strong> price bound trajectories live in "Allocation & policy
        trajectories"; the auction guardrail fields live in "Supply &amp; price bounds"; the
        resulting auction rules and auction pathway both appear on the Analysis tab.
      </div>
    </div>
  );
}

export default {
  id: "price_controls",
  scenarioDefaults: {
    price_floor_trajectory: {},
    price_ceiling_trajectory: {},
  },
  editorSections: [PriceBoundTrajectories, AuctionGuardrailFields],
  analysisBullets: [ReservePriceBullet, MinBidCoverageBullet, UnsoldTreatmentBullet, CancelledAllowancesBullet],
  guideSections: [{ id: "module-price_controls", tag: "PXC", title: "Price controls", content: PriceControlsGuideSection }],
};
