import { useState } from "react";

const STEPS = [
  {
    id: "what",
    number: "00",
    title: "What is this tool?",
    content: () => (
      <div className="guide-body">
        <p className="guide-lead">
          This is an <strong>Emissions Trading System (ETS) simulator</strong>. It lets you
          model how a carbon market works — who buys and sells emission allowances, at what
          price, and what that means for total emissions.
        </p>
        <div className="guide-concept-grid">
          <div className="guide-concept-card">
            <div className="guide-concept-icon">🏭</div>
            <h4>The basic idea</h4>
            <p>
              A government sets a hard limit (a <strong>cap</strong>) on total emissions from
              covered industries. Companies must hold one allowance per tonne of CO₂ they emit.
              They can buy, sell, and earn these allowances — creating a <strong>carbon market</strong>.
            </p>
          </div>
          <div className="guide-concept-card">
            <div className="guide-concept-icon">⚖️</div>
            <h4>Supply and demand</h4>
            <p>
              The government auctions a fixed supply of allowances. Companies bid for them based
              on whether it's cheaper to <strong>buy an allowance</strong> or <strong>cut their
              emissions</strong>. The crossing point sets the <strong>carbon price</strong>.
            </p>
          </div>
          <div className="guide-concept-card">
            <div className="guide-concept-icon">📉</div>
            <h4>Why it works</h4>
            <p>
              Each year the cap tightens. Allowances become scarcer, the price rises, and
              companies invest more in clean technologies. The total emission reduction is
              guaranteed by the cap — the price is what adjusts.
            </p>
          </div>
        </div>
        <div className="guide-flow">
          <div className="guide-flow-step">Set the cap</div>
          <div className="guide-flow-arrow">→</div>
          <div className="guide-flow-step">Auction allowances</div>
          <div className="guide-flow-arrow">→</div>
          <div className="guide-flow-step">Market finds price</div>
          <div className="guide-flow-arrow">→</div>
          <div className="guide-flow-step">Companies abate or buy</div>
          <div className="guide-flow-arrow">→</div>
          <div className="guide-flow-step">Read the results</div>
        </div>
      </div>
    ),
  },
  {
    id: "start",
    number: "01",
    title: "Load a template to get started",
    content: () => (
      <div className="guide-body">
        <p className="guide-lead">
          The fastest way to start is to load an example scenario. You can explore a
          working model before building your own.
        </p>
        <ol className="guide-steps">
          <li>
            <span className="guide-step-num">1</span>
            <div>
              Click the <strong>Model</strong> tab in the top navigation (it may already be
              selected when you open the app).
            </div>
          </li>
          <li>
            <span className="guide-step-num">2</span>
            <div>
              In the header toolbar, find the <strong>template dropdown</strong> — it looks
              like a small select menu with a scenario name. Click it to see the list of
              built-in examples.
            </div>
          </li>
          <li>
            <span className="guide-step-num">3</span>
            <div>
              Pick <em>"Climate Solutions — Full Featured Pathway"</em> for a rich example,
              or <em>"Climate Solutions — Basic Linear"</em> for something simpler.
            </div>
          </li>
          <li>
            <span className="guide-step-num">4</span>
            <div>
              Click <strong>Load template</strong>. The scenario is now active and you can
              run it immediately.
            </div>
          </li>
        </ol>
        <div className="guide-tip">
          <strong>Tip:</strong> The header shows the active scenario as a colored pill. You
          can have multiple scenarios loaded at the same time and switch between them by
          clicking their pills.
        </div>
      </div>
    ),
  },
  {
    id: "scenarios",
    number: "02",
    title: "Understanding scenarios",
    content: () => (
      <div className="guide-body">
        <p className="guide-lead">
          A <strong>scenario</strong> is a complete ETS model — it has a name, a set of
          years, the market rules for each year, and the companies participating.
        </p>
        <div className="guide-concept-grid guide-concept-grid-2">
          <div className="guide-concept-card">
            <h4>Scenario</h4>
            <p>
              The top-level container. Has a <strong>name</strong>, <strong>color</strong>,
              and <strong>description</strong>. You can run multiple scenarios and compare
              them side by side.
            </p>
            <p className="guide-example">
              Example: "Aggressive Decarbonisation" vs "Business As Usual"
            </p>
          </div>
          <div className="guide-concept-card">
            <h4>Year</h4>
            <p>
              Each scenario contains one or more <strong>years</strong>. Every year has its
              own market rules (cap size, auction volume, price bounds) and participant list.
            </p>
            <p className="guide-example">
              Example: 2030, 2035, 2040, 2045, 2050
            </p>
          </div>
          <div className="guide-concept-card">
            <h4>Participant</h4>
            <p>
              A company or sector inside the market. Each participant has an emissions
              baseline, free allowances received, and options for how cheaply they can
              reduce emissions.
            </p>
            <p className="guide-example">
              Example: Steel plant, Coal power station, Cement kiln
            </p>
          </div>
          <div className="guide-concept-card">
            <h4>Allowance</h4>
            <p>
              A permit to emit one tonne of CO₂. Companies must surrender one allowance per
              tonne at year-end. They can earn them free, buy them at auction, or trade with
              other participants.
            </p>
            <p className="guide-example">
              Unit: Mt CO₂e (megatonnes of CO₂ equivalent)
            </p>
          </div>
        </div>
        <div className="guide-tip">
          <strong>Add or duplicate scenarios</strong> using the buttons in the header
          toolbar. Use the colored pills in the header to switch between scenarios.
        </div>
      </div>
    ),
  },
  {
    id: "model-tab",
    number: "03",
    title: "The Model tab — market timeline",
    content: () => (
      <div className="guide-body">
        <p className="guide-lead">
          The <strong>Model tab</strong> is where you configure everything. It has two
          sections: the <strong>Market Timeline</strong> at the top, and the
          <strong> Scenario Editor</strong> below.
        </p>
        <h3 className="guide-section-title">Market Timeline</h3>
        <p>
          This is an interactive chart that lets you set how a market variable changes
          across years. Pick a variable from the left panel, then drag the dots on the
          chart or click a value label to type an exact number.
        </p>
        <div className="guide-field-table">
          <div className="guide-field-row guide-field-header">
            <span>Variable</span><span>What it controls</span>
          </div>
          <div className="guide-field-row">
            <span className="guide-field-name">Total cap</span>
            <span>The hard annual limit on total covered emissions (Mt CO₂e). The single most important lever.</span>
          </div>
          <div className="guide-field-row">
            <span className="guide-field-name">Auction offered</span>
            <span>How many allowances are sold at auction each year. The rest go to participants as free allocation.</span>
          </div>
          <div className="guide-field-row">
            <span className="guide-field-name">Price floor</span>
            <span>The carbon price cannot fall below this. Prevents the market from collapsing.</span>
          </div>
          <div className="guide-field-row">
            <span className="guide-field-name">Price ceiling</span>
            <span>The carbon price cannot rise above this. Acts as a safety valve for businesses.</span>
          </div>
          <div className="guide-field-row">
            <span className="guide-field-name">Auction reserve price</span>
            <span>Minimum price at auction. Allowances that don't reach this price go unsold.</span>
          </div>
          <div className="guide-field-row">
            <span className="guide-field-name">Reserved / Cancelled</span>
            <span>Allowances held back from market (reserved) or permanently retired (cancelled).</span>
          </div>
          <div className="guide-field-row">
            <span className="guide-field-name">Borrowing limit</span>
            <span>How many future-period allowances a participant can use today (only if borrowing is enabled).</span>
          </div>
        </div>
        <h3 className="guide-section-title" style={{marginTop: "20px"}}>Pathway Setting (right panel)</h3>
        <p>
          Instead of editing each year manually, use the <strong>Pathway generator</strong>.
          Choose a rule, set a start and end value, and click <strong>Generate pathway</strong>
          — it fills in all years automatically.
        </p>
        <div className="guide-field-table">
          <div className="guide-field-row guide-field-header">
            <span>Rule</span><span>What it does</span>
          </div>
          <div className="guide-field-row">
            <span className="guide-field-name">Linear</span>
            <span>Straight line from start value to end value over the selected years.</span>
          </div>
          <div className="guide-field-row">
            <span className="guide-field-name">% decline</span>
            <span>Reduces by a fixed percentage each step (e.g. −2% per year).</span>
          </div>
          <div className="guide-field-row">
            <span className="guide-field-name">Hold then drop</span>
            <span>Stays flat until a pivot year, then drops linearly to the end value.</span>
          </div>
          <div className="guide-field-row">
            <span className="guide-field-name">Step</span>
            <span>Jumps instantly to end value at start year, stays flat.</span>
          </div>
          <div className="guide-field-row">
            <span className="guide-field-name">S-curve</span>
            <span>Slow start, rapid middle, slow finish — models technology adoption curves.</span>
          </div>
        </div>
      </div>
    ),
  },
  {
    id: "editor",
    number: "04",
    title: "The Model tab — scenario editor",
    content: () => (
      <div className="guide-body">
        <p className="guide-lead">
          Click <strong>Edit scenario inputs</strong> to open the step-by-step editor. It
          has four steps — work through them in order.
        </p>
        <div className="guide-steps-vertical">
          <div className="guide-editor-step">
            <div className="guide-editor-step-num">Step 1</div>
            <div className="guide-editor-step-body">
              <h4>Scenario settings</h4>
              <p>Set the scenario <strong>name</strong>, <strong>color</strong> (used in charts), and an optional description. These are just labels — they don't affect the simulation.</p>
            </div>
          </div>
          <div className="guide-editor-step">
            <div className="guide-editor-step-num">Step 2</div>
            <div className="guide-editor-step-body">
              <h4>Market rules</h4>
              <p>Set the rules for the <strong>currently selected year</strong>:</p>
              <ul className="guide-list">
                <li><strong>Auction mode</strong> — "Explicit" lets you set the auction volume directly. "Residual" automatically auctions whatever is left after free allocation.</li>
                <li><strong>Banking</strong> — allow companies to save unused allowances for future years.</li>
                <li><strong>Borrowing</strong> — allow companies to use next year's allowances today.</li>
                <li><strong>Unsold treatment</strong> — what happens to allowances that don't sell at auction: hold in reserve, cancel permanently, or carry forward to next year.</li>
                <li><strong>Expectation rule</strong> — how companies predict future carbon prices when deciding whether to bank or borrow. "Myopic" means they assume tomorrow's price equals today's. "Perfect foresight" means they know future prices exactly.</li>
              </ul>
            </div>
          </div>
          <div className="guide-editor-step">
            <div className="guide-editor-step-num">Step 3</div>
            <div className="guide-editor-step-body">
              <h4>Participants</h4>
              <p>Add the companies or sectors covered by the ETS. For each participant:</p>
              <ul className="guide-list">
                <li><strong>Initial emissions</strong> — how many Mt CO₂e they emit before any abatement.</li>
                <li><strong>Free allocation ratio</strong> — what fraction of their emissions they receive as free allowances (0 = none free, 1 = all free). Industries at risk of "carbon leakage" to overseas often receive high free allocation.</li>
                <li><strong>Penalty price</strong> — the fine per tonne if they don't surrender enough allowances at year-end. Acts as a compliance ceiling: no one will pay more than this for an allowance.</li>
                <li><strong>Abatement model</strong> — how cheaply can they reduce emissions? (see next step)</li>
              </ul>
              <div className="guide-tip">
                <strong>Tip:</strong> Use the built-in participant templates (Steel, Coal, Cement, etc.) as starting points — they come pre-filled with realistic cost data.
              </div>
            </div>
          </div>
          <div className="guide-editor-step">
            <div className="guide-editor-step-num">Step 4</div>
            <div className="guide-editor-step-body">
              <h4>Review</h4>
              <p>A pre-run summary showing all configured values. Check for any highlighted issues before running the simulation.</p>
            </div>
          </div>
        </div>
      </div>
    ),
  },
  {
    id: "abatement",
    number: "05",
    title: "Abatement models — how companies cut emissions",
    content: () => (
      <div className="guide-body">
        <p className="guide-lead">
          An <strong>abatement model</strong> defines how much it costs a company to reduce
          its emissions. The simulator uses this to calculate how much each participant will
          abate at any given carbon price.
        </p>
        <div className="guide-concept-grid guide-concept-grid-3">
          <div className="guide-concept-card">
            <h4>Linear</h4>
            <p>Abatement cost rises smoothly with each additional tonne reduced. Set a <strong>max abatement</strong> (how much is possible) and a <strong>cost slope</strong> (how steeply the cost rises).</p>
            <p className="guide-example">Simple. Good for generic sectors or early-stage modelling.</p>
          </div>
          <div className="guide-concept-card">
            <h4>Threshold</h4>
            <p>No abatement happens until the carbon price reaches a <strong>threshold cost</strong>. Above it, abatement increases linearly. Models technologies that only become viable above a certain price.</p>
            <p className="guide-example">Good for breakthrough technologies like green hydrogen.</p>
          </div>
          <div className="guide-concept-card">
            <h4>Piecewise (MAC blocks)</h4>
            <p>The most realistic option. Defines "blocks" of abatement — each block has an <strong>amount</strong> (Mt) and a <strong>marginal cost</strong> ($/t). Blocks must be in order of increasing cost.</p>
            <p className="guide-example">Example: 6 Mt at $20/t, then 8 Mt at $55/t, then 8 Mt at $110/t.</p>
          </div>
        </div>
        <div className="guide-callout">
          <strong>How the simulation uses this:</strong> When the model solves for equilibrium, it
          compares the carbon price to each participant's marginal abatement cost. A participant
          abates whenever the carbon price <em>exceeds</em> their marginal cost — because it's
          cheaper to reduce emissions than to buy an allowance.
        </div>
        <h3 className="guide-section-title" style={{marginTop: "20px"}}>Technology options (advanced)</h3>
        <p>
          You can give a participant <strong>alternative technologies</strong> — for example, a
          coal plant could switch to renewables. Each technology has its own emissions, free
          allocation ratio, abatement model, and a <strong>fixed adoption cost</strong> (one-time
          investment). The <strong>adoption share cap</strong> limits how fast they can switch
          (e.g. 50% of capacity per year maximum).
        </p>
        <p>
          Use the <strong>Technology Transition Wizard</strong> (in the participant editor) to
          auto-generate realistic technology options for Steel, Coal, and Cement sectors.
        </p>
      </div>
    ),
  },
  {
    id: "validation",
    number: "06",
    title: "Validation — check before you run",
    content: () => (
      <div className="guide-body">
        <p className="guide-lead">
          The <strong>Validation tab</strong> checks your scenario configuration for
          problems before you run the simulation.
        </p>
        <div className="guide-concept-grid guide-concept-grid-3">
          <div className="guide-concept-card guide-error-card">
            <h4>🔴 Errors</h4>
            <p>Must be fixed. The simulation may produce nonsense results or fail entirely if errors are present.</p>
            <p className="guide-example">Example: Price ceiling is lower than the price floor. Auction offered exceeds total cap.</p>
          </div>
          <div className="guide-concept-card guide-warning-card">
            <h4>🟡 Warnings</h4>
            <p>Worth reviewing. The simulation will run, but results may be unrealistic or hard to interpret.</p>
            <p className="guide-example">Example: All participants have zero abatement capacity.</p>
          </div>
          <div className="guide-concept-card guide-note-card">
            <h4>🔵 Notes</h4>
            <p>Informational only. Just reminders about settings that are unusual but valid.</p>
            <p className="guide-example">Example: Banking is disabled, so unused allowances expire at year-end.</p>
          </div>
        </div>
        <p>
          <strong>Click any issue</strong> to jump directly to the field that needs fixing.
          The app will open the right tab and scroll to the problem.
        </p>
        <div className="guide-tip">
          <strong>Tip:</strong> Run validation before every simulation run, especially after
          making changes to market rules or adding participants.
        </div>
      </div>
    ),
  },
  {
    id: "run",
    number: "07",
    title: "Running the simulation",
    content: () => (
      <div className="guide-body">
        <p className="guide-lead">
          Once your scenario is configured, click one of the <strong>Run</strong> buttons
          in the header toolbar to solve the market equilibrium.
        </p>
        <div className="guide-field-table">
          <div className="guide-field-row guide-field-header">
            <span>Button</span><span>What it does</span>
          </div>
          <div className="guide-field-row">
            <span className="guide-field-name">Run loaded scenario</span>
            <span>Runs the last saved or template-loaded version. Ignores any unsaved edits you've made.</span>
          </div>
          <div className="guide-field-row">
            <span className="guide-field-name">Run edited</span>
            <span>Runs whatever is currently in the editor — including unsaved changes. Use this to test a quick edit.</span>
          </div>
          <div className="guide-field-row">
            <span className="guide-field-name">Run all scenarios</span>
            <span>Runs every loaded scenario at once. Required before comparing scenarios in the Scenario tab.</span>
          </div>
        </div>
        <div className="guide-callout">
          <strong>What happens when you run:</strong> The simulator solves for the equilibrium
          carbon price in each year — the price where total demand for allowances equals total
          supply (auctioned + free). It uses a numerical root-finding algorithm that tries prices
          until supply and demand balance.
        </div>
        <p>
          The status bar in the header shows <em>Running…</em> while the model is computing.
          When it shows <em>Complete</em>, switch to the <strong>Analysis tab</strong> to see
          results.
        </p>
        <div className="guide-tip">
          <strong>Tip:</strong> If results look unexpected, check the Validation tab for
          warnings, then review your market rules and participant abatement costs.
        </div>
      </div>
    ),
  },
  {
    id: "analysis",
    number: "08",
    title: "Reading the Analysis tab",
    content: () => (
      <div className="guide-body">
        <p className="guide-lead">
          The <strong>Analysis tab</strong> shows the simulation results as interactive
          charts. Use the year buttons at the top to switch between years.
        </p>
        <div className="guide-steps-vertical">
          <div className="guide-editor-step">
            <div className="guide-editor-step-num">Fig 1</div>
            <div className="guide-editor-step-body">
              <h4>Market clearing chart</h4>
              <p>The core output. Shows <strong>total demand</strong> for allowances (sloping downward — as price rises, companies abate more and buy fewer allowances) vs. <strong>supply</strong> (horizontal line = fixed auction volume). The intersection is the <strong>equilibrium carbon price</strong>.</p>
              <p>You can <strong>drag the supply line</strong> up or down to see how changing the auction volume shifts the price.</p>
            </div>
          </div>
          <div className="guide-editor-step">
            <div className="guide-editor-step-num">Fig 2</div>
            <div className="guide-editor-step-body">
              <h4>Price trajectory</h4>
              <p>How the equilibrium carbon price evolves across years, for all loaded scenarios on one chart. Compare whether your cap pathway produces a steadily rising price or price spikes.</p>
            </div>
          </div>
          <div className="guide-editor-step">
            <div className="guide-editor-step-num">Fig 3</div>
            <div className="guide-editor-step-body">
              <h4>Participant breakdown</h4>
              <p>A horizontal bar chart showing each participant's net position. <strong>Buyers</strong> (right, green) must purchase allowances because their residual emissions exceed their free allocation. <strong>Sellers</strong> (left, red) have abated so heavily they have surplus allowances to sell.</p>
              <p>Click a participant bar to select them and update Figure 4.</p>
            </div>
          </div>
          <div className="guide-editor-step">
            <div className="guide-editor-step-num">Fig 4</div>
            <div className="guide-editor-step-body">
              <h4>Marginal abatement cost curve</h4>
              <p>The selected participant's abatement cost schedule. Each step is a block of abatement at a given cost. A vertical line marks the equilibrium price — everything to the left of it (cheaper than the carbon price) gets abated; everything to the right gets bought as allowances instead.</p>
            </div>
          </div>
          <div className="guide-editor-step">
            <div className="guide-editor-step-num">Fig 5</div>
            <div className="guide-editor-step-body">
              <h4>Annual market pathway</h4>
              <p>Tracks the <strong>carbon price</strong>, total <strong>abatement</strong>, and <strong>auction revenue</strong> across all years. Shows whether the market is tightening over time.</p>
            </div>
          </div>
          <div className="guide-editor-step">
            <div className="guide-editor-step-num">Fig 6</div>
            <div className="guide-editor-step-body">
              <h4>Annual emissions pathway</h4>
              <p>Stacked area chart of <strong>residual emissions</strong> by participant across years. This is what actually gets emitted after abatement — compare this to the cap to check whether the system is working.</p>
            </div>
          </div>
        </div>
        <div className="guide-tip">
          <strong>Auction diagnostics</strong> (below the charts): Shows whether the auction
          cleared, how much of the offered volume was bid on, and what happened to unsold
          allowances.
        </div>
      </div>
    ),
  },
  {
    id: "compare",
    number: "09",
    title: "Comparing scenarios",
    content: () => (
      <div className="guide-body">
        <p className="guide-lead">
          The <strong>Scenario tab</strong> lets you compare all loaded scenarios side by
          side. You must run all scenarios first (use <em>Run all scenarios</em> button).
        </p>
        <div className="guide-concept-grid guide-concept-grid-2">
          <div className="guide-concept-card">
            <h4>Benchmark cards</h4>
            <p>Highlights the best outcome across all scenarios: lowest carbon price, lowest total emissions, and highest auction revenue. Useful for quickly identifying which policy design performs best.</p>
          </div>
          <div className="guide-concept-card">
            <h4>Comparison matrix</h4>
            <p>A table with one column per scenario and rows for key metrics: equilibrium price, total residual emissions, abatement, auction revenue, and total compliance cost.</p>
          </div>
          <div className="guide-concept-card">
            <h4>Trajectory charts</h4>
            <p>Line charts showing carbon price and emissions across years for all scenarios on the same axes. Makes it easy to spot divergence: which scenario decarbonises faster?</p>
          </div>
          <div className="guide-concept-card">
            <h4>Scenario cards</h4>
            <p>Individual cards per scenario with a mini supply-demand chart, key statistics, and a colour-coded summary. Good for a quick one-page snapshot of each policy option.</p>
          </div>
        </div>
        <div className="guide-tip">
          <strong>How to create a comparison:</strong>
          <ol style={{margin: "8px 0 0 16px", paddingLeft: 0}}>
            <li>Load or build your baseline scenario.</li>
            <li>Click <strong>Duplicate scenario</strong> in the header.</li>
            <li>Edit one variable in the copy (e.g. tighten the cap by 10%).</li>
            <li>Click <strong>Run all scenarios</strong>.</li>
            <li>Switch to the <strong>Scenario tab</strong> to compare.</li>
          </ol>
        </div>
      </div>
    ),
  },
  {
    id: "learn",
    number: "10",
    title: "Tutorials & reference docs",
    content: () => (
      <div className="guide-body">
        <p className="guide-lead">
          Go deeper with the full tutorial suite and the reference documentation. These open in a new tab.
        </p>
        <div className="guide-concept-grid guide-concept-grid-2">
          <div className="guide-concept-card">
            <h4>📘 Build Your First Scenario</h4>
            <p>A hands-on walkthrough that climbs the "closure ladder": base market → MSR → Carbon Cap Rule → price-elastic baseline → model coupling.</p>
            <p><a href="/docs/tutorials/build-your-first-scenario.html" target="_blank" rel="noopener">Open the walkthrough →</a></p>
          </div>
          <div className="guide-concept-card">
            <h4>📒 Scenario Cookbook</h4>
            <p>~20 ready-to-run recipes grouped by theme — market foundations, allocation &amp; trade, price formation, supply-side policy, feedback, and real-world cases.</p>
            <p><a href="/docs/tutorials/scenario-cookbook.html" target="_blank" rel="noopener">Open the cookbook →</a></p>
          </div>
          <div className="guide-concept-card">
            <h4>🎓 Practitioner Training</h4>
            <p>A role-based course built around real decisions — compliance, policy design, trading, transition strategy, scenario analysis, and calibration. Six modules with exercises.</p>
            <p><a href="/docs/tutorials/practitioner-training.html" target="_blank" rel="noopener">Open the training course →</a></p>
          </div>
          <div className="guide-concept-card">
            <h4>🗂️ Tutorials home</h4>
            <p>The landing page that links all three tutorials in one place.</p>
            <p><a href="/docs/tutorials/index.html" target="_blank" rel="noopener">Open tutorials home →</a></p>
          </div>
        </div>
        <div className="guide-tip">
          <strong>Reference documentation</strong>
          <p style={{margin: "6px 0 8px"}}>Field-by-field and algorithm detail (Markdown):</p>
          <ul style={{margin: "0 0 0 16px", paddingLeft: 0, columns: 2}}>
            {[
              ["Algorithm overview", "algorithm-overview.md"],
              ["Data model (every field)", "data-model.md"],
              ["MAC / abatement models", "mac-abatement.md"],
              ["Market equilibrium", "market-equilibrium.md"],
              ["Multi-year simulation & MSR", "multi-year-simulation.md"],
              ["Carbon Cap Rule (CCR)", "carbon-cap-rule.md"],
              ["Feedback A — price-elastic baseline", "feedback-price-elastic-baseline.md"],
              ["Feedback B — model coupling", "feedback-coupling.md"],
              ["Output-based allocation", "oba-allocation.md"],
              ["Sector configuration", "sector-config.md"],
              ["Technology transition", "technology-transition.md"],
              ["Analysis tools (calibrate, batch)", "analysis-tools.md"],
            ].map(([label, file]) => (
              <li key={file}>
                <a href={"/docs/" + file} target="_blank" rel="noopener">{label}</a>
              </li>
            ))}
          </ul>
        </div>
      </div>
    ),
  },
  {
    id: "glossary",
    number: "11",
    title: "Glossary",
    content: () => (
      <div className="guide-body">
        <div className="guide-glossary">
          {[
            ["Allowance", "A permit to emit one tonne of CO₂ equivalent. Companies must surrender one per tonne emitted."],
            ["Abatement", "Reducing emissions below the baseline. E.g. switching fuels, improving efficiency, capturing CO₂."],
            ["Auction", "The government sells allowances to the highest bidders. The clearing price sets the carbon price floor for that round."],
            ["Banking", "Saving unused allowances to use in a future year. Allowed only if the scenario has banking enabled."],
            ["Borrowing", "Using next year's allowances to cover this year's emissions. Requires borrowing to be enabled and a borrowing limit set."],
            ["Cap", "The hard annual limit on total covered emissions. Tightening the cap over time is what drives decarbonisation."],
            ["Carbon price", "The equilibrium price at which supply and demand for allowances balance. Expressed in $/tonne CO₂e."],
            ["Equilibrium", "The carbon price where total demand for allowances equals total supply. The simulator solves for this numerically."],
            ["Free allocation", "Allowances given to companies at no cost — often to protect industries at risk of moving overseas (carbon leakage)."],
            ["MAC curve", "Marginal Abatement Cost curve. Shows the cost of each additional tonne of abatement. The steeper the curve, the more expensive deep abatement becomes."],
            ["Mt CO₂e", "Megatonnes of CO₂ equivalent. One Mt = one million tonnes. A typical large power plant emits 5–15 Mt/year."],
            ["Penalty price", "The fine per tonne for not surrendering enough allowances at year-end. Acts as the compliance ceiling — no one pays more than this for an allowance."],
            ["Reserve price", "Minimum price at auction. Allowances that receive bids below this go unsold."],
            ["Residual emissions", "Emissions remaining after abatement. Residual = initial emissions − abatement taken."],
            ["Supply", "Total allowances available to the market = auctioned + free allocation (minus reserved and cancelled)."],
            ["Technology option", "An alternative technology a participant can adopt (e.g. hydrogen DRI for steel). Has its own emissions, cost, and adoption limits."],
          ].map(([term, def]) => (
            <div className="guide-glossary-row" key={term}>
              <dt>{term}</dt>
              <dd>{def}</dd>
            </div>
          ))}
        </div>
      </div>
    ),
  },
];

export function GuideView() {
  const [activeStep, setActiveStep] = useState("what");
  const step = STEPS.find((s) => s.id === activeStep) || STEPS[0];
  const Content = step.content;

  return (
    <div className="guide-view">
      <aside className="guide-sidebar">
        <div className="guide-sidebar-title">User Guide</div>
        {STEPS.map((s) => (
          <button
            key={s.id}
            className={"guide-nav-item " + (s.id === activeStep ? "on" : "")}
            onClick={() => setActiveStep(s.id)}
          >
            <span className="guide-nav-num">{s.number}</span>
            <span className="guide-nav-label">{s.title}</span>
          </button>
        ))}
      </aside>
      <main className="guide-main">
        <div className="guide-header">
          <span className="guide-step-badge">{step.number}</span>
          <h2>{step.title}</h2>
        </div>
        <Content />
        <div className="guide-pagination">
          {STEPS.findIndex((s) => s.id === activeStep) > 0 && (
            <button
              className="ghost-btn"
              onClick={() => setActiveStep(STEPS[STEPS.findIndex((s) => s.id === activeStep) - 1].id)}
            >
              ← Previous
            </button>
          )}
          {STEPS.findIndex((s) => s.id === activeStep) < STEPS.length - 1 && (
            <button
              className="ghost-btn"
              onClick={() => setActiveStep(STEPS[STEPS.findIndex((s) => s.id === activeStep) + 1].id)}
            >
              Next →
            </button>
          )}
        </div>
      </main>
    </div>
  );
}
