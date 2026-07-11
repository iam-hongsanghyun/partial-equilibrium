// Participant drilldown — a table + a horizontal diverging bar showing who buys vs who sells.
import { fmt } from "./MarketChart.jsx";
import { collectSlot } from "../registry.js";

export function ParticipantPanel({ year, result, onEdit, onSelectParticipant, selectedIdx, sectorColors, enabledFeatures = null }) {
  const rows = result.perParticipant;
  const maxAbs = Math.max(1, ...rows.map(r => Math.abs(r.net_trade)));

  return (
    <div className="drilldown">
      <div className="drilldown-header">
        <h3>Who buys. Who sells.</h3>
        <p className="muted">At ${fmt.num(result.price, 2)}/tCO₂, each participant's position in the market.</p>
      </div>
      <div className="participants">
        {rows.map((r, i) => {
          const isSelected = i === selectedIdx;
          const part = year.participants[i];
          const color = sectorColors[part.sector] || "#888";
          const widthPct = (Math.abs(r.net_trade) / maxAbs) * 48; // up to 48% each side
          const buyer = r.net_trade > 0.01;
          const seller = r.net_trade < -0.01;
          return (
            <div key={i} className={"prow" + (isSelected ? " selected" : "")}
                 onClick={() => onSelectParticipant?.(i)}>
              <div className="prow-ident">
                <div className="pname">{r.name}</div>
                <div className="psector" style={{ color }}>{part.sector}</div>
                {r.technology && <div className="ptech">{r.technology}</div>}
                {r.technology_mix ? <div className="ptech">{r.technology_mix}</div> : null}
              </div>
              <div className="prow-stats">
                <div className="stat"><span className="label">Emissions</span><span className="val">{fmt.num(r.initial, 0)}</span></div>
                <div className="stat"><span className="label">Free alloc</span><span className="val">{fmt.num(r.free, 0)}</span></div>
                <div className="stat"><span className="label">Abated</span><span className="val abate">{fmt.num(r.abatement, 1)}</span></div>
                {collectSlot(enabledFeatures, "resultStats").map((Stat, index) => (
                  <Stat key={index} ctx={{ r }} />
                ))}
              </div>
              <div className="prow-bar">
                <div className="bar-axis">
                  <div className="bar-center"></div>
                  {seller && (
                    <div className="bar bar-seller" style={{ width: widthPct + "%", right: "50%" }}>
                      <span>sells {fmt.num(-r.net_trade, 1)}</span>
                    </div>
                  )}
                  {buyer && (
                    <div className="bar bar-buyer" style={{ width: widthPct + "%", left: "50%" }}>
                      <span>buys {fmt.num(r.net_trade, 1)}</span>
                    </div>
                  )}
                </div>
              </div>
              <div className="prow-pos">
                <div className={"pos-chip " + (buyer ? "buyer" : seller ? "seller" : "neutral")}>
                  {buyer ? "Net buyer" : seller ? "Net seller" : "Balanced"}
                </div>
                <div className="cost">
                  {buyer ? `−${fmt.money(r.net_trade * result.price)}` : seller ? `+${fmt.money(-r.net_trade * result.price)}` : "—"}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
