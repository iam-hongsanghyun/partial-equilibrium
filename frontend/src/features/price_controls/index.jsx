// Price controls feature — price floor/ceiling trajectories and the
// auction guardrail fields (reserve price, minimum bid coverage, unsold
// treatment). Extracted verbatim from frontend/src/components/Editor.jsx.
//
// editorSections[0] = floor/ceiling trajectory rows, rendered inside
// "Allocation & policy trajectories" alongside the core cap trajectory row
// (same TrajectoryRangeRow component, reused not duplicated).
// editorSections[1] = auction guardrail fields, rendered inside "Supply &
// price bounds" between the core allowance-bucket fields and the core
// price floor/ceiling fields — the exact position they held before
// extraction.

import { TrajectoryRangeRow, numInput, fieldWithPathButton } from "../../components/EditorPrimitives.jsx";
import { fmt } from "../../components/MarketChart.jsx";
import { describeUnsoldTreatment } from "../../components/AppShared.jsx";

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
  const { workingYear, updateYear, openMarketSeriesEditor } = ctx;
  return (
    <>
      <label>
        <span className="ekey">{fieldWithPathButton("Auction reserve price", () => openMarketSeriesEditor("auction_reserve_price"), false, true)}</span>
        {numInput(workingYear.auction_reserve_price || 0, (value) => updateYear({ auction_reserve_price: value }), 1, 0)}
      </label>
      <label>
        <span className="ekey">{fieldWithPathButton("Minimum bid coverage", () => openMarketSeriesEditor("minimum_bid_coverage"), false, true)}</span>
        {numInput(workingYear.minimum_bid_coverage || 0, (value) => updateYear({ minimum_bid_coverage: value }), 0.05, 0)}
      </label>
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

export default {
  id: "price_controls",
  scenarioDefaults: {
    price_floor_trajectory: {},
    price_ceiling_trajectory: {},
  },
  editorSections: [PriceBoundTrajectories, AuctionGuardrailFields],
  analysisBullets: [ReservePriceBullet, MinBidCoverageBullet, UnsoldTreatmentBullet, CancelledAllowancesBullet],
};
