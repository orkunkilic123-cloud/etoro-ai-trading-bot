# Phase 6: independent event-driven backtesting

This is an offline simulation engine, independent of broker execution. It reuses the actual StrategyEngine, ExitMonitor, indicator/scoring functions and RiskEngine. It never loads credentials, calls market APIs, creates broker Tickets or enables Demo/Real execution. Existing risk/strategy/execution modules and their safety limits are unchanged. No paid dependencies were added.

**No trustworthy point-in-time historical dataset is bundled or verified.** All included scenarios are explicitly synthetic engineering fixtures, including prices, sessions, earnings coverage, FX, liquidity and minimum-size/step evidence. Their results do not establish profitability. The `historical_verified` provenance label is a trusted dataset-review declaration, not automatic authentication of data quality.

## Architecture and replay contract

| Module | Responsibility |
| --- | --- |
| `models` | Immutable Dataset, Tick, Provenance, Simulation and Plan contracts |
| `engine` | Chronological event replay, cash/positions, later-quote fills, strategy/risk handoff and equity ledger |
| `risk` | Exclusively created simulation risk store, unchanged risk evaluation, simulated reservation accounting and durable duplicate records |
| `benchmark` | Passive buy-and-hold and no-trade USD cash comparators |
| `metrics` | Returns, drawdown, position outcomes, costs and time-weighted exposure |
| `evaluation` | Chronological training selection, frozen validation/test evaluation and walk-forward folds |
| `report` | Deterministic JSON, CSV, Markdown and file checksums |
| `fixtures` / `__main__` | Explicit synthetic software demonstrations; no downloader |

`Backtest(dataset, Plan(rules, simulation)).run(new_directory)` is a single-instrument USD-underlying portfolio simulation. It supports all three existing strategies, intraday/short-swing rules and initial EUR 500 or EUR 1,000. Compare strategies using separate independent portfolios; this release does not implement a multi-instrument portfolio allocator. At most one position or entry intent is active per run. This is a portfolio-model constraint, not a daily trade quota.

Every run directory must be new. The engine archives `inputs.json` with complete input data and configuration, a strategy journal and a separate simulation risk database. Result manifests include data, plan and source-code digests, provenance, limitations and open units. Ordinary replay does not open an existing user safety database. Failures leave diagnostic state rather than silently resetting or overwriting it. Resume-after-crash is not implemented; rerun into a new directory from identical archived inputs.

## Time, data availability and sessions

Dataset start must be UTC midnight, with an explicit fresh initial USD-per-EUR observation. End must have an observed final valuation quote. Ticks are strictly chronological, timestamped deliveries containing bid/ask, source observation time, point-in-time eligibility/product/session/FX/cost/earnings evidence, available liquidity and explicit closing permission. Future/stale quotes or future evidence are rejected. Bars carry separate completion and availability times. Only completed bars published by the current event reach indicators or strategy. Future bars cannot change a decision prefix. Duplicate bar timestamps/revisions are currently rejected: a real revision-aware data adapter must supply the appropriate historical version, not today's corrected history.

Strategies recompute and verify scanner features through the existing StrategyEngine. The replay uses the same scoring rules to create an Opportunity from the currently available completed history; there is no supplied future signal file. Warm-up uses at least 35 already-published hourly bars. Missing/invalid signal data or volatility-screen failures are recorded as missed/rejected events, never filled. Structural dataset or storage failures abort the run rather than produce apparently complete results.

Sessions and closes are supplied as aware, point-in-time evidence. There is no invented NYSE calendar or inferred holiday/DST rule. Offset changes are compared as absolute instants. Intraday deadlines use the existing strategy's close buffer; swing positions use its ongoing risk/exit and earnings rules. Closed sessions prohibit simulated fills. Overnight gaps are valued at observed quotes; the engine does not pretend a stop filled at yesterday's price. Real deployment-quality historical evidence must include holiday/early-close sessions and known-at timestamps for calendar changes.

## Event ordering and conservative simulated fills

At each quote event:

1. Establish any new UTC daily baseline from the simulated ledger's last valuation **before** applying the new day's price movement. Closed/unobserved intervals carry last-known marks; a new opening gap remains part of that day's loss. No midday baseline reset is allowed.
2. Mark portfolio equity at the current bid; call the original RiskEngine to observe/latch the 3% daily loss and emergency switch. Observation uses an intentionally invalid zero-size proposal after the account/day checks, never a reservation or order.
3. Cancel expired entry intent, or consider a later fill only if both event time and quote-observation time are strictly later than the decision, the configured delay has elapsed and the market is open.
4. Recheck current minimum/maximum units, whole/fractional eligibility, product/step evidence, earnings calendar, cash and **all original RiskEngine limits at the simulated fill price and actual partial quantity**. A gap-up fill that exceeds 1% risk is rejected. No automatic increase in approved size is allowed.
5. Process previously scheduled close advice at a later quote, only with explicit `close_allowed=True`. Unknown permission retains inventory; it does not imply a successful close.
6. Refresh valuation/risk, evaluate ongoing exit advice, and only then consider a new entry if the portfolio is flat and no intent is pending. Record the equity/cash/exposure observation even when no signal qualifies.

A candidate's existing short expiry remains binding. The engine never extends it to make an hourly backtest trade. Hourly OHLC alone is therefore insufficient to validate these strategies' fill timing: quotes within the configured expiry/delay are needed. Repeated delivery of an old quote cannot fill an intent. Stop/trailing/target advice schedules a later simulated close; no same-quote fill, invented intrabar path, or optimistic high/low ordering is used. This may be more conservative than broker-attached stops and requires calibration against independently verified historical execution evidence.

Entry fills use ask × (1 + slippage); exits use bid × (1 − slippage), rounded adversely to six decimal places. Six decimals are a declared simulation precision assumption, **not** an eToro tick-size claim. Explicit fixed and proportional commissions apply to each actual fill. Initial EUR-to-USD conversion cost is charged once; strategy sizing also includes conservative FX/cost buffers. A buffer is not a second cash charge. Cash never borrows; positions are long, underlying and leverage 1.

Fill size is limited by the requested quantity, current supplied liquidity and configurable fill fraction, rounded down to the verified quantity step. A positive fraction attempts at least one permissible step when available. Entry partial fills cancel the unfilled remainder (an explicit immediate-or-cancel simulation assumption, not a broker capability claim). Broker minimums apply to the requested size; an accepted partial execution may be smaller. Close partials retain the remainder for later eligible quotes and pay commissions per fill. Availability/liquidity is an input assumption, never inferred from future completed-bar volume.

Unknown minimums, fractional increment or underlying status cannot be fabricated. Current eToro eligibility supports minimum exposure/margin and whole/fractional permission, but not a universally verified fractional increment; historical step evidence remains required. Unsupported precision still fails the existing RiskEngine calculation checks.

## Risk reservation accounting without weakening production controls

Strategy generation does not reserve capacity. The existing explicit strategy-to-risk review does. `SimulationRisk` creates a brand-new `backtest-demo` safety DB and inherits the existing RiskEngine. No existing risk, strategy or execution source code is modified.

A simulated fill/cancellation moves its local reservation into a durable simulation-only duplicate table. Actual filled exposure and cash then enter the next complete AccountSnapshot. Original proposal IDs and economic fingerprints remain blocked across retirement, preserving duplicate protection without double-counting the same simulated position as both pending and held. Fill admission excludes only its own reservation while invoking `evaluate_in_transaction`; every other risk, balance and exposure check remains active. Daily halt, clock watermark and kill state are never reset by this handoff.

This isolated accounting adapter is **not** a production reservation-release API. It relies on the simulator knowing its own outcome; a live broker can have unknown/partial/asynchronous outcomes. Existing production reservations and deployment limitations remain unchanged. Default simulation initialization explicitly clears only its newly created synthetic kill switch; `Simulation(kill_switch=True)` tests the blocking path.

## Portfolio accounting and metrics

Reports use USD after initial EUR conversion. A no-trade comparator holds USD cash after the same conversion cost; it does not assume interest. This is not an EUR cash or FX-hedged comparator. Final open inventory remains marked at bid; there is no forced liquidation that invents a final fill. Unrealized P&L affects equity/returns/drawdown but not completed-position win statistics.

- Total return: final marked equity / gross initial USD-equivalent equity − 1, including conversion costs.
- Annualized return: elapsed-time geometric annualization, only with at least 365.25 days and positive final equity; otherwise null.
- Maximum drawdown: peak-to-trough marked equity at observed events. Unobserved intrabar drawdowns cannot be measured.
- Win rate, profit factor and expectancy: fully closed positions, net of allocated entry/exit commissions. Partial exits accumulate into one position outcome. Profit factor is null when there are no losses, not fabricated infinity. Account-level initial FX cost is included in total return/costs, not attributed to closed-position expectancy.
- Sharpe: zero risk-free rate, arithmetic daily-close returns, sample standard deviation and sqrt(365). Requires at least 30 returns on consecutive calendar days and nonzero variance; missing days or insufficient observations yield null. Trading-day Sharpe is not inferred.
- Exposure: time-weighted marked position value / equity, carrying the preceding event state over each interval.
- Trading costs: actual commissions + initial FX charge + spread-half and slippage estimates on each fill. Spread/slippage are already embedded in prices and are **not** deducted twice from cash. Open inventory's final bid mark is conservative and can include an additional unrealized half-spread relative to mid.

Every funding, baseline, risk halt, rejected/missed decision, risk review, entry/cancel, exit advice/fill and valuation is recorded. `trades.csv` contains exit-fill allocations/P&L; entry fills are in `events.csv`. The strategy journal retains detailed rule/feature/proposal records. A buy-and-hold benchmark uses the first eligible later quote, identical conversion/cost/liquidity/step constraints and passive cash allocation, without strategy stops. It is a reference portfolio, not a risk-approved strategy or a bypass usable for orders.

## Chronological evaluation and sensitivity

`Split(train_start, validation_start, test_start, end)` defines half-open chronological windows. Each funding boundary needs a quote/FX observation at UTC midnight. Training can use only previously published warm-up history. `evaluate_split` runs a predeclared finite plan list on training, selects by training total return with a deterministic digest tie-break, then freezes that plan for validation and final test. Validation/test outcomes never select or tune parameters. All training runs and held-out evaluations receive reports. Changing final-test quotes cannot change selection in the tests.

`walk_forward` repeats this procedure with chronological, disjoint test windows. Later folds may train on information that became available after an earlier fold. Final-test data cannot enter selection for its own fold. Each window starts a new independent portfolio; positions/reservations are not carried across folds. No trades are scored in both windows, and prior-window open positions are only marked at that window's last observation. This measures independent deployment windows, not a stitched continuous portfolio. Proper real-data studies still need predeclared purge/embargo periods appropriate to holding horizons, data revisions and overlapping labels; there is no supervised model/label fitting here.

Sensitivity tests vary commissions, slippage, delays, fill fractions/liquidity and explicitly synthetic volatility/gap scenarios. They check mechanical effects and safety, not robustness of real profitability. No market prices are silently perturbed and relabelled as historical evidence. A researcher can supply alternative immutable Plan/Simulation configurations for separate reports; never use final-test sensitivity results for parameter selection.

## Reports and reproducibility

`write_report(result, new_directory)` writes Markdown, JSON, events/equity/trades/decisions CSV files and checksums. `comparison` writes strategy-comparison Markdown, CSV and JSON. Undefined metrics are explicit nulls/insufficient observations. Provenance and limitations accompany every JSON report and evidence classification appears prominently in Markdown/comparisons. Reports contain no wall-clock run timestamp, random seed dependency or absolute output path; identical inputs/configuration/source produce identical report bytes in the tested environment. Python floating-point indicators/metrics may require tolerance across runtime/platform changes; monetary simulation uses a local 60-digit Decimal context.

No synthetic report is committed as historical evidence. The offline demonstration command creates fresh local outputs for all three strategies and both holding styles. All source/data/plan digests and the complete input archive should be retained with a research result. Human review is required before promoting any learned rule change; this engine never edits production rules, risk limits or approval state.

## Real-data validation still blocked

Before independent real-data conclusions, obtain a free/licensed point-in-time archive with historical universe/delistings; original/revised completed bars and availability times; bid/ask observations inside proposal TTLs; realistic quote-side liquidity and fill assumptions; corporate actions/dividends; historical unleveraged-product eligibility/minimums/fractional steps/close permission; sessions/timezones/holidays; FX/fees; and earnings calendars as they were known. Validate completeness and source lineage externally. The engine has no downloader, historical API invention or corporate-action processor. The current one-instrument model, conservative quote-based stops, initial-cost FX model and synthetic liquidity require explicit disclosure and independent calibration.

Software tests and synthetic comparisons validate implementation behavior only. They do not establish market performance, production execution quality or profitability.
