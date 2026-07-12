# D3 Multi-commodity spec — steel↔carbon partial equilibrium

Authored by ets-lead-economist (design gate, 2026-07-12). The economics spec for
the D3 multi-commodity flagship. Reuses the D2 joint engine (`engine/scc.py` +
damped Gauss-Seidel in `engine/joint.py`) UNCHANGED and names precisely the one
new solver primitive. Companion architecture plan: `docs/multi-commodity-plan.md`
(lead-modeller). Economic judgment calls are tagged **[JC#]**; platform strains
**[STRAIN#]**.

---

## 1. Product-market primitive — clearing on a demand curve

**The genuinely new object.** Every market today clears a *compliance-obligation
flow*: `clearing.py` solves `total_net_demand(P) = auction_offered`, where net
demand = Σ(residual_i − free_alloc_i) is the quantity of permits firms must buy,
supply is the exogenous cap-derived auction volume, and the price is the *shadow
price of the cap constraint* (decreasing in P — higher P → more abatement → less
residual). A product market is different in kind: it clears a **goods market** on
a behavioral **demand curve** against **optimizing supply**.

Steel market clearing:

$$ S_{\text{dom}}(P_s, P_c) + M(P_s) \;=\; D(P_s), \qquad S_{\text{dom}} = \sum_i q_i(P_s, P_c). $$

**[JC1] Demand form.** Linear demand for the hand anchor, parameterized through a
reference point so the elasticity lever (§4b) is explicit:

$$ D(P_s) = A_d - b_d\,P_s, \qquad b_d = \eta_{\text{ref}}\,\frac{Q_{\text{ref}}}{P_{\text{ref}}}. $$

Offer constant-elasticity $D = \kappa P_s^{-\eta}$ as a config option (numerically
solved, realistic for pass-through studies); linear is the closed-form anchor.

**Contrast (state in the doc):** in the carbon market *supply is exogenous* (the
cap) and *demand is derived* from compliance; the clearing price is a Lagrange
multiplier. In the steel market *both blades are behavioral and price-responsive*
— an upward-sloping optimizing supply and a downward-sloping consumer demand —
and the price is a Walrasian goods price. The joint engine does not care (each
market still "returns a price given inputs"), but the economic object each
computes is distinct.

---

## 2. Multi-commodity agent — two decarbonization margins

Producer $i$ chooses output $q_i$ AND intensity abatement $a_i$ to maximize

$$ \pi_i = P_s q_i - \big(\gamma_i q_i + \tfrac12\delta_i q_i^2\big) - \tfrac12\beta_i a_i^2 q_i - P_c(\sigma_i - a_i)q_i + P_c F_i, $$

baseline intensity $\sigma_i$ (tCO₂/t), abatement $a_i\in[0,a_{\max,i}]$, free
allocation $F_i = F_i^{\text{lump}} + \varphi_i^{\text{OBA}} q_i$. MC $=\gamma_i+\delta_i q_i$.

**[JC2]** Abatement cost is *per unit of output* ($\tfrac12\beta_i a_i^2 q_i$) —
the intensity-MAC formulation; makes $a_i^*$ independent of $q_i$ and maps to the
platform's existing MAC=P optimization. **[JC3]** Production cost is quadratic
($\delta_i>0$) so marginal cost slopes up and supply is well-defined; $\delta_i=0$
(horizontal supply, indeterminate output at MC=P) is disallowed.

**FOC in $a_i$** (intensity margin): abate until MAC $=\beta_i a_i = P_c$:

$$ a_i^* = P_c/\beta_i \quad (\text{clipped to } [0, a_{\max,i}]). $$

Pure function of the carbon price — this IS the platform's abatement rule.

**FOC in $q_i$** (output margin), substituting $a_i^*$:

$$ q_i^*(P_s,P_c) = \frac{P_s - \gamma_i - P_c\sigma_i + \tfrac12 P_c^2/\beta_i + P_c\varphi_i^{\text{OBA}}}{\delta_i}, \qquad e_i^* = (\sigma_i - P_c/\beta_i)\,q_i^*. $$

**How the carbon price splits effort (the load-bearing decomposition).** The
*intensity margin* responds linearly and first ($a^*=P_c/\beta$); the *output
margin* responds to the *residual* burden after abatement, $B_i = P_c\sigma_i -
\tfrac12 P_c^2/\beta_i$ (the convex $\tfrac12 P_c^2/\beta$ is the abatement saving
that cushions output). A **cheap-abatement firm (low $\beta$)** leans on
intensity, preserving output; an **expensive-abatement firm (high $\beta$)** sheds
output instead. Crucially **OBA raises $q^*$ (it enters the output FOC) but leaves
$a^*$ untouched** — it blunts the output margin while preserving the abatement
incentive. That asymmetry is the whole OBA-vs-leakage story (§4d).

---

## 3. Carbon coupling and the joint fixed point

Carbon market: $\sum_i e_i(P_s,P_c) = \text{Cap} \Rightarrow P_c$ given $P_s$ —
reconciles with the platform's existing clearing exactly (Σresidual = auction +
Σfree_alloc = Cap), $e_i$ now $P_s$-dependent through $q_i$. Steel market:
$\sum_i q_i(P_s,P_c) + M(P_s) = D(P_s) \Rightarrow P_s$ given $P_c$. Two equations,
two prices — the joint fixed point over $(P_s, P_c)$.

**Existence (Brouwer).** Both clearing maps continuous ($q_i, e_i, a_i$ continuous
in prices; corner solutions are kinks, not jumps), prices in a compact box, so
$T:\text{box}\to\text{box}$ continuous ⇒ a fixed point exists. Slack cap ⇒ $P_c=0$
boundary equilibrium; discrete investment adoption reintroduces the Kakutani/
eventually-continuous case (joint-equilibrium.md §2/§4).

**Loop gain / contraction.** The Gauss-Seidel loop gain is the product of the two
structural price responses, $g = s_c\cdot s_s$, with
$\partial G/\partial P_s = \sum_i(\sigma_i-a_i^*)/\delta_i>0$, $\partial G/\partial P_c<0$,
$\partial H/\partial P_s = \sum_i 1/\delta_i + M' + b_d>0$,
$\partial H/\partial P_c = \sum_i[-(\sigma_i-a_i^*)+\varphi_i^{\text{OBA}}]/\delta_i<0$.
Both $s_c,s_s>0$ ⇒ $g>0$: the steel↔carbon coupling is a **positive feedback →
monotone convergence**. Contraction $|g| = s_c s_s < 1$ is a diagonal-dominance
condition (own-market clearing slopes dominate cross-slopes), **checkable per
config** from $\{\delta_i,\beta_i,\sigma_i,b_d,M'\}$ — maps to the D2 $|g|<1$
condition **verbatim**; the D2 WARNING ($\hat g\ge1$) fires on strongly-coupled
calibrations (inelastic demand + emission-intensive + tight cap). The joint engine
solves it **unchanged** ($w=0.5$ default handles $g$ up to 3, cycle-detect and
per-market relative norm as built).

**[STRAIN1] First genuine MIXED-UNIT SCC** — USD/t-steel coupled to USD/tCO₂. The
V-D2-3 per-market relative convergence norm is now *required*, not decorative (the
same-unit joint flagships never exercised it). Confirm the norm is live on this SCC.

---

## 4. The levers

Each composes (additive in the FOCs); a config turns on any subset.

- **(a) Cap tightness** — `total_cap`/`cap_trajectory`. Tighter → higher $P_c$ →
  more abatement + output loss → lower emissions/output, higher steel price.
  Shows $P_c$ endogenous to the cap (a shadow price) and its real-economy incidence.
- **(b) Demand elasticity** — $\eta_{\text{ref}}$ / $b_d$. Elastic ⇒ no pass-through
  ⇒ output loss + leakage dominate; inelastic ⇒ pass-through to $P_s$, consumers
  bear the cost. The **incidence split**.
- **(c) Intensity + abatement curve** — $\sigma_i,\beta_i$. Low $\beta$ → intensity
  margin, output preserved; high $\beta$ → output margin + leakage; high $\sigma$ →
  more exposed. The intensity-vs-scale decomposition + firm heterogeneity.
- **(d) Free allocation / OBA** — $F_i^{\text{lump}}$ vs $\varphi_i^{\text{OBA}}$.
  **Lump-sum** enters as $+P_c F^{\text{lump}}$, infra-marginal, absent from both
  FOCs ⇒ **pure transfer, no output/abatement effect**. **OBA** enters as
  $+P_c\varphi^{\text{OBA}}q$, marginal ⇒ an **output subsidy** $P_c\varphi^{\text{OBA}}$/unit,
  raising $q^*$ by $P_c\varphi^{\text{OBA}}/\delta_i$ vs auctioning, leaving $a^*$
  untouched — the textbook result. The free-allocation design debate: OBA fights
  leakage on the output margin but subsidizes residual-emitting output.
- **(e) CBAM (price-active)** — `cbam_enabled`, $\sigma_{\text{foreign}}$, coverage
  $c$. Import charge $c\,P_c\,\sigma_{\text{foreign}}$/unit: $M = m(P_s - c P_c\sigma_{\text{foreign}})$.
  Levels domestic vs imported carbon cost ⇒ leakage falls. **[STRAIN2]
  Contradicts today's F6 CBAM** (post-clearing reporting, price-inert); the
  multi-commodity CBAM feeds INTO steel clearing — a distinct, price-active object
  that must NOT reuse the inert F6 path.
- **(f) Foreign imports → leakage** — $M(P_s)=M_0+m P_s$ (carbon-free, elastic).
  Domestic $P_c$ → domestic output falls → imports rise → emissions shift abroad.
  **Leakage rate** $L = \sigma_{\text{foreign}}\Delta M / (-\Delta e_{\text{dom}})$
  = foreign emissions gained / domestic emissions cut.
- **(g) Investment (long-run margin)** — `invest_trigger` on a cleaner-tech option
  (lower $\sigma'_i$). Dixit-Pindyck adopts when $P_c \ge M\theta$; **reuse
  investment-in-cycle verbatim** — adoption nests as the MIDDLE loop inside the
  joint $(P_s,P_c)$ fixed point, adoption-as-outer-floor (monotone). On adoption
  $\sigma$ drops → emissions fall → cap loosens → $P_c$ falls (ex-post regret
  permitted) → output recovers. The **third decarbonization margin** (beyond
  reversible intensity and output): a durable downward shift of the intensity curve.

**Narrative:** carbon price → output loss + leakage (a,b,c,f); OBA (output margin)
and CBAM (import margin) as the two anti-leakage levers on *different* margins;
investment as the long-run margin.

---

## 5. Hand-anchored minimal example (the multi-commodity "J1")

2 identical domestic producers (aggregate $\gamma=10,\delta=1,\sigma=2$), no
intensity abatement (**[JC4]** $\beta\to\infty$, $a^*=0$ — output-margin-only, the
cleanest leakage story, fully linear), linear demand $A_d=120, b_d=1$, carbon-free
elastic imports $M=m P_s$ with $m=1$, $\sigma_{\text{foreign}}=2$, fixed cap $=40$.

Cap binds ⇒ $q^* = \text{Cap}/\sigma = 20$. Steel clearing $q + mP_s = A_d - b_d P_s$:

$$ P_s^* = \frac{A_d - \text{Cap}/\sigma}{m+b_d} = \frac{120-20}{2} = 50, \quad P_c^* = \frac{P_s^*-\gamma-\delta\,\text{Cap}/\sigma}{\sigma} = \frac{50-10-20}{2} = 10, \quad M^*=50,\ D=70. $$

No-policy counterfactual ($P_c=0$): $P_s^0=130/3=43.33$, $q^0=33.33$, $M^0=43.33$,
$e^0=66.67$. **Leakage** $L = \frac{2(50-43.33)}{66.67-40} = \frac{13.33}{26.67} = \mathbf{0.50}$
— half the domestic cut leaks abroad.

**[JC6/STRAIN3] Honesty flag:** with $\beta\to\infty$ and a binding cap, $q$ is
pinned by the cap, $s_s=\partial P_s/\partial P_c = 0$, $g=0$ — this minimal anchor
is **block-recursive** (steel→carbon), the D2 SCC-collapse corner (J3). It shows
the product-market primitive, leakage, and CBAM cleanly, but the *genuine 2-way
cycle* requires finite $\beta$ (then $q=\text{Cap}/(\sigma-P_c/\beta)$ varies with
$P_c$, closing the loop). **Ship a SECOND anchor with finite $\beta$** (quadratic
in $P_c$ → numerically golden-pinned) labeled the true cyclic case, asserting
convergence under damped Gauss-Seidel. The teaching point: *the cycle is born when
abatement lets output vary at a fixed cap.*

**Levers-on variant (CBAM, coverage $c=0.5$).** $M = P_s - P_c$; $q=20$,
$P_c=(P_s-30)/2$:

$$ 20 + (P_s - P_c) = 120 - P_s \Rightarrow P_s^*=56.67,\ P_c^*=13.33,\ M^*=43.33. $$

$e_{\text{foreign}} = 2(43.33) = 86.67 = e^0 \Rightarrow \boxed{L=0}$ — the
half-CBAM restores imports to baseline, **leakage neutralized**, at a higher
domestic carbon price (13.33 vs 10: blocking the import escape valve makes the cap
bind harder). Full coverage $c=1$ over-corrects ($L=-1$). The didactic payoff:
**cap-only 50% leakage → cap+half-CBAM 0% leakage.**

**OBA in this anchor:** $\beta\to\infty$ pins $q$ at the cap, so OBA cannot move
output — an honest limitation: **OBA fights leakage through the output margin,
which needs abatement (finite $\beta$) active; CBAM fights it through the import
margin regardless.** The finite-$\beta$ golden shows OBA biting.

---

## 6. Platform mapping

**A steel producer is a participant in TWO markets** — the carbon SCC-market
(contributing $e_i$ to Σe=Cap) and the steel SCC-market (contributing $q_i$ to
Σq+M=D). **[STRAIN4]** Today a `MarketParticipant` belongs to one market; the
multi-commodity agent has decision state ($q_i$) and reads both prices.

**Design choice — couple via a SHARED AGENT, not an external PriceLink:** the
agent's optimization intrinsically depends on both prices (its FOCs), so register
one producer object in both SCC-markets and have each market read the relevant
output of its `optimize()`; the carbon→steel and steel→carbon "links" are implicit
in the shared agent. Reserve external D1 PriceLinks (`mac_cost`) for *reduced-form*
cost pass-throughs between otherwise-separate markets. The steel→carbon coupling
(product price → output → emissions) would not fit the D1 R35 whitelist — the
shared-agent design avoids needing to whitelist it.

**Reused (no new economics):** the joint engine (SCC + damped Gauss-Seidel +
cycle-detect + mixed-unit norm); the abatement optimization (MAC=P ⇒ $a^*=P_c/\beta$);
the OBA relationship free_allocation = benchmark_intensity × output (`builder.py`)
— the *formula* reused, its *input* now endogenous; the investment machinery
(Dixit-Pindyck, adoption-as-outer-floor, investment-in-cycle) verbatim for the
clean-tech option. **The elastic-baseline overlay (Option A, `activity_multiplier`)
is the reduced-form ancestor of the steel market** — a price-elasticity on a
*fixed* baseline; the multi-commodity model subsumes it with a structural output
market.

**Genuinely new (the minimal new primitive) — exactly four things:**
1. **A ProductMarket clearing on a demand curve** — Brent root-find on
   $D(P_s) - \sum q_i(P_s,P_c) - M(P_s) = 0$, distinct from `CarbonMarket.solve_equilibrium`.
   The one real new solver primitive.
2. **The producer's OUTPUT FOC** $q_i(P_s,P_c)$ — a second optimization margin
   alongside the existing abatement FOC (the two-margin agent).
3. **Carbon-free import supply + the leakage diagnostic** — a new supply block and
   the $L$ reporting column (guarded, multi-market-only).
4. **Price-active CBAM** feeding into steel clearing — distinct from the inert F6
   reporting CBAM (**[STRAIN2]**).

**[STRAIN5] `production_output` migrates from build-time config to solve-time
state.** OBA free allocation today reads `production_output` at build time; with
endogenous $q_i^*$ it is known only after the steel market clears, so OBA
free-allocation must be recomputed each Gauss-Seidel sweep as $q_i$ updates — the
build-time→solve-time migration (cf. the invest-feedback adoption-mask precedent).
One sanctioned recompute point, not a build transform.

**Judgment calls:** [JC1] linear demand (elasticity via reference point) anchor,
constant-elasticity numeric option; [JC2] per-unit-output abatement cost; [JC3]
$\delta>0$ required; [JC4] $\beta=\infty$ anchor is the output-margin-only
recursive corner; [JC5] elastic carbon-free imports for a well-defined leakage
rate; [JC6] OBA (output margin) and CBAM (import margin) act on different margins;
[JC7] Σe=Cap reconciles with the platform's auction=cap clearing exactly.

**Bottom line:** the D3 flagship is implementable as *one* new market type
(ProductMarket), *one* extended agent (two-margin producer, shared across two
markets), and *one* price-active CBAM channel, on top of the unchanged D2 joint
engine — the steel↔carbon SCC becoming the first real mixed-unit joint equilibrium,
with the leakage/OBA/CBAM/investment levers composing into the anti-leakage policy
narrative.

---

## 7. V-D3 verdicts closed (2026-07-12) + the finite-β cyclic anchor

**V-D3-1 (existence/uniqueness): CONFIRMED, δ>0 sufficient.** The program is not
jointly concave, but solves sequentially: a\*(q)=P_c/β is independent of q, so the
reduced profit π̃(q)=(P_s−γ−B)q−½δq² is strictly concave iff δ>0. q\*, a\*
single-valued + continuous ⇒ Brouwer joint-FP existence, no bang-bang/Kakutani.
Reject δ=0 at validation; discrete investment is the only discontinuity (handled by
adoption-as-outer-floor).

**V-D3-2 (FOCs): CONFIRMED — code the a_max-clipped GENERAL form, not the interior
shortcut:** a\* = clip(P_c/β, 0, a_max); B = ½·β·a\*² + P_c(σ−a\*) − P_c·φ_OBA;
q\* = max(0, (P_s−γ−B)/δ); e\* = (σ−a\*)q\*. The §2 ½P_c²/β is the unclipped (a_max
non-binding) special case; a firm past P_c>β·a_max sits at a\*=a_max and can only
shed output. Both clips are continuous kinks (V-D3-1 holds).

**V-D3-3 (coupling): CONFIRMED price-driven; [STRAIN5] DISSOLVED.** Each market
re-derives q\*, e\* from BOTH prices; no quantity threaded ⇒ `engine/joint.py`
verbatim, price norm suffices. Producer authored once in the steel body; the carbon
market gets a build-time emitter VIEW that computes e\* on demand from the current
price pair each sweep (a reference, never a cached copy, never solve-time injection).
Because q\* is a pure function of prices, OBA free-alloc φ·q\* is too ⇒ NO
build-time→solve-time migration hazard ([STRAIN5] dissolved). The multi-commodity
carbon market has NO free-alloc supply bucket — OBA enters only as the marginal FOC
subsidy P_c·φ; clearing is purely Σe\*=Cap.

**V-D3-4 (levers): CONFIRMED.** Guards: floor imports at zero, M=max(0, m(P_s −
c·P_c·σ_foreign)) (continuous kink); the leakage rate must NAME its counterfactual
(no-policy vs cap-only) or it is ambiguous.

**V-D3-5b — the genuine finite-β cyclic anchor (the flagship D3-6 golden):**
Parameters: 2 identical producers γ=5, δ=2, σ=5, β=10, a_max=5; linear demand
A_d=40, b_d=0.3; carbon-free imports m=0.2, σ_foreign=5; fixed cap=40.
Converged (exact, hand-verified): **P_s\*=60, P_c\*=10, a_i\*=1, q_i\*=5** (agg 10),
Σe\*=(σ−a\*)q\*=40=Cap, M\*=12, D=22, **leakage L=0.353**. Loop gain
**g = s_c·s_s = 0.235·2.667 = 0.627 ∈ (0,1)**; damped GS at w=0.5 has eigenvalue
0.813 → converges (undamped also, |g|<1). The emission cut 85 = intensity margin 25
+ output margin 60 (both active — the cycle is BORN because finite β makes output
endogenous at a fixed cap: q=Cap/(σ−P_c/β)). No-policy counterfactual: P_s⁰=30,
q⁰=25, e⁰=125, M⁰=6. CBAM variant (numerically pinned, not closed-form): full c=1
over-corrects (P_c↑≈17.9, q↑≈12.5, imports collapse, leakage negative); partial
coverage tunes leakage toward zero — the didactic payoff.

**R37 ADAPTATION (required for D3):** R37's conservative ĝ=Π|φ| with s_m←1 is a
D1/D2 EXTERNAL-link device — it does NOT apply to the shared-agent STRUCTURAL
coupling (there is no external φ; the structural s_s=2.667 is not bounded by 1). For
D3, **R37 must evaluate the ACTUAL loop gain g=s_c·s_s from the linearized 2×2
clearing Jacobian at the one-way seed** (a cheap evaluation), warning iff |g|≥1. For
this anchor g=0.627 ⇒ no false-fire.

### V-D3-5 lever rulings (2026-07-12)

**#1 Investment trigger — keep θ/M separation; P\* is a derived DISPLAY.** The
clean-tech config retains explicit θ (Marshallian break-even, required) + the
M-inputs (σ, credibility q, r, y => M=β/(β−1)), reusing the Phase-1 AdoptionSpec —
do NOT fold M into one "trigger" number (that discards the irreversibility-under-
uncertainty economics). The engine REPORTS P\*=M·θ as a diagnostic;
`trigger_multiple_override` (M=1) is the documented escape hatch. The D3-6 golden
uses `trigger_mode="break_even"` (M≡1 => P\*=θ).

**#2 Leakage counterfactual under adoption — fix at the UN-ADOPTED σ.** Headline
leakage holds the P_c=0 counterfactual at the baseline (un-adopted) technology, so
it measures the whole-policy effect INCLUDING the induced tech-switch (adoption
lowers leakage by preserving domestic output). The post-adoption-σ' number is at
most a secondary "conditional leakage" diagnostic.

**#3 Cross-leg adoption — accepted with a REQUIRED leg-agreement assertion.** The
two producer faces accumulate independent monotone floors that agree at the joint
fixed point (monotone => no oscillation; unique adoption equilibrium; convergence
forces leg-agreement). REQUIRED: a loud convergence-time assertion that the two
legs' adoption floors AGREE in the reported equilibrium — a leg-inconsistent
"converged" state (same firm σ on one face, σ' on the other) must never be reported
(D2-5 CALL-2 ex-post consistency, checked against the converged vector; transient
disagreement permitted). Recommended: decide adoption once per sweep on the carbon
leg's SOLVED P_c and mirror to the steel leg (delivered-price doctrine).

**#4 OBA clearing identity — CONFIRMED Σe = Cap + φ·Σq (corrects the earlier
"Σe=Cap").** Output-based allocation issues φΣq free allowances ON TOP of the
auctioned volume, so total allowances = Q_auction + φΣq and, with a binding price,
Σe = Cap + φ·Σq. **OBA is NOT emissions-neutral — it RELAXES the cap** (floats up
with output) in exchange for leakage protection. This corrects §3/§6's "clearing is
purely Σe*=Cap" (true only for the no-OBA / fixed-cap case). **Key contrast: CBAM is
cap-PRESERVING (Σe=Cap), OBA is cap-RELAXING (Σe>Cap).** In the anchor CBAM cuts
leakage far more (0.353→0.111) while holding Σe=Cap; OBA barely dents leakage
(0.353→0.326) AND inflates gross emissions +33% — CBAM dominates here (calibration-
dependent ranking; the structural cap-preserving-vs-relaxing fact is general). Name
the OBA design `output_based` in the golden; the single-market `oba_output_allocation.json`
is the different `fixed_cap`/exogenous-output design (distributional, Σe=Cap).
