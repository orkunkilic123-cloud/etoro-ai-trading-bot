# Phase 14: evidence-gated intraday ORB replay

Independent research interface: `etoro_demo_bot.backtest.intraday.IntradayBacktest`.
It reuses the Phase 13 ORB proposal facade, unchanged Risk Manager, simulation-owned
risk handoff, `Simulation` cost settings, `Result` schema and existing metric helper.
Hourly Dataset/Backtest, strategies, Alpaca ingestion, execution and the original
Monte Carlo Pool interface retain their existing behavior. No upstream code or data
is copied and no dependency or network path is added.

The sole external Trader Skill reference remains
[day-trader-skill](https://github.com/Jakeschincariol/day-trader-skill/tree/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd).
Its trader-timemachine specification was re-inspected at this pinned commit. Root
MIT software licensing does not confer market-data rights. We independently
implement conservative gaps/costs and whole-session outcome resampling; we do not
adopt its idealized -1R gap stops, unofficial downloader or profitability examples.

## Evidence gate

`Dataset` contains the unchanged `ResearchSeries`, an instrument, an ordered tuple
of existing `Tick` quote/evidence/liquidity observations, a `Review`, and optional
Phase 13 `VolumeEvidence`. `Plan` contains existing `Simulation`, existing safety
`Rules` and frozen `OrbRules`.

Before any risk database is created:

- Require exact `FIVE_MINUTE_RESEARCH`, native raw five-minute bars, valid snapshot
  hashes/provider identity, matching symbol and immutable source metadata. Accept
  only original `synthetic` or `historical_observation` source classifications.
- Revalidate every bar's interval/completion/first-known/session contract. Require
  all 78 normal-session or 42 early-close intervals, in order, exactly once. Require
  every NYSE trading session between the first and last declared date. No trimming,
  missing-session selection, interpolation, duplicate overwrite or price fabrication.
- Reject unsupported calendar years, future calendar reviews, stale/future quotes,
  stale FX/evidence, missing quantity-step verification, out-of-session ticks and
  missing initial/final boundary valuations. Bound inputs to 20,000 bars and 200,000
  events. Holidays, DST and early closes use the existing reviewed 2026 calendar.
- Genuine observations additionally need nonempty review references for coverage,
  original availability/revisions, applicable usage rights and corporate actions,
  bound to the exact snapshot. Existing replay blockers remain blockers.
- Historical quotes, spreads, FX, eligibility, costs, liquidity and earnings each
  require a `Review.evidence` pair `(field, review_reference)` or an explicit name
  in `Review.assumed_fields`. Missing fields block, rather than silently acquiring
  a default assumption. Describe each assumption in `Review.assumptions` too.
  Assumed eligibility cannot grant fractional capacity: supply whole-share inputs
  or independently reviewed fractional evidence. Existing minimum order, maximum
  units, underlying/unleveraged and earnings gates still apply.

Review references are external reviewer declarations, not cryptographic evidence of
truth or automatic legal authorization. A checksum establishes input integrity, not
original publication, vendor entitlement, completeness or eToro eligibility. Keep
licensed inputs and resulting detailed reports private; reports include input prices.

**Ordinary later Alpaca downloads remain blocked.** They assign first-known times to
retrieval, not candle close; their source retrieval is later than replay start and
original-availability blockers remain. This adapter does not backdate those times,
change the parser, clear historical blockers or activate the disabled five-minute
network path. An owner-reviewed capture/archive with truthful original availability,
rights, actions and coverage is still required. No genuine dataset was used to
validate this phase. Tests that change a classification deliberately exercise only
negative evidence gates; they do not turn synthetic prices into historical results.

Invalid structure or absent critical evidence yields `status=blocked`, explicit
blockers, empty metrics and no simulated trades. Successful synthetic runs are
`synthetic`; historical-input research is always `conditional`, even with all input
reviews, because execution is modelled. No label means verified eToro profitability.

## Event timing and fills

The engine advances at each supplied observation time, not at an assumed executable
bar close. Completed bars enter the available stream only at their first-known time.
ORB sees the completed point-in-time prefix, and the first three candles and later
confirming close retain the Phase 13 rules. Future bar prices cannot affect earlier
signals. Full-dataset hashes in the report identify inputs, not decision features.

A signal first passes journaled ORB review and the actual Risk Manager. It becomes
pending, not filled. A later quote must be observed strictly after that decision,
after the configured delay (default one second), before the original maximum
60-second signal expiry, and inside both the entry and regular-session window.
No signal life is refreshed by a new price or a second breakout.

Entry price = next eligible ask plus configured adverse slippage, rounded up to
six decimals. Recheck current product, eligibility, FX/costs, earnings, cash, spread,
maximum units, minimum notional, step and no-chase limits. Filled quantity is the
minimum of requested quantity times `fill_fraction`, supplied available units and
requested quantity, rounded down to the step. Cancel the unfilled entry remainder;
never fill a second tranche without a new admission. The actual fill's price, size
and conservative round-trip cost buffer go through unchanged risk checks again.
The fill buffer cannot be smaller than its prorated original proposal buffer.

For an open position:

1. Newly available whole bars entirely after entry can reveal a stop/target touch.
   Entry-bar extremes are ignored because their pre/post-fill ordering is unknown;
   observed quotes can still trigger an exit. This limitation can miss an entry-bar
   touch; it is not a guarantee of conservative worst-case P&L at every resolution.
2. Model OHLC-to-bid using the event's observed relative half-spread. This is an
   explicit constant-within-bar assumption, not historical executable bid evidence.
   Opening through a stop uses the lower opening bid. Target gaps get no favorable
   improvement beyond the target. If both levels touch, choose the stop first.
3. A bar touch is detected when its data becomes available at an observation event;
   it cannot produce a retroactive fill at the bar's high/low timestamp. Quote stops,
   capped targets, risk halts and session exit deadlines also create exit requests.
4. Fill only at a later eligible fresh quote after the configured delay. Long exit
   price is the worse of that bid and the trigger's analytical price ceiling, minus
   slippage, rounded down. A recovery during the delay cannot improve the model's
   trigger ceiling. Stop orders do not guarantee their requested price.
5. Available units and fill fraction also limit exits. Residual inventory retains
   its exit request. Fees apply to every partial fill. A small residual can remain
   unfillable after step rounding; it is not silently discarded.

No simulated fill is allowed outside regular sessions. A missed deadline or absent
liquidity leaves inventory marked at the final observed bid and explicitly unresolved.
If a later session is present, the overdue exit may fill at its next eligible quote,
including an adverse overnight gap. Deadline breach and overnight fills are recorded.
A session deadline is not a guaranteed liquidation. Halts, queue priority, hidden
liquidity and actual intrabar ordering are unknown; zero liquidity/disabled closing
can be supplied as explicit research stress observations.

## Costs, currency and risk

`Simulation` supports EUR 500 and EUR 1,000, fixed/per-notional per-fill commission,
adverse per-side slippage, initial funding FX charge, partial-fill fraction, delay
and an isolated research kill-switch setting. Defaults are model assumptions,
not broker schedules. Spread is embedded in supplied bid/ask. Implicit spread,
slippage and trigger-ceiling shortfall are attributed as costs and are not deducted
a second time. Commission and funding FX are actual cash deductions.

Initial EUR is converted at the first event's supplied USD/EUR rate, charging the FX
fraction once on all funding. USD cash/positions are marked and translated to EUR
at each event's independently timestamped rate. There is no automatic conversion-back
charge or future FX forecast. Strategy sizing conservatively uses the larger of
supplied and simulated cost assumptions, including pro-rata FX in the risk buffer;
this reserves risk, not an extra cash FX debit. Actual exposure and cash feed the
Risk Manager after every observation and fill.

The existing 1% maximum estimated trade risk, sticky 3% daily-loss halt, 20% position,
25% instrument, 80% exposure and five-position defaults remain in force. Gaps can
exceed planned risk. Each UTC daily baseline uses the previous observed equity;
NYSE regular sessions do not cross UTC midnight. The independent adapter currently
holds at most one instrument/position, and still calls the full risk engine; it does
not replace portfolio/concurrency rules with its own permissive shortcut.

All journals and safety stores are created exclusively below a **new** run directory,
using the existing `SimulationRisk` account `backtest-demo`. Its initial kill switch
is cleared only for this newly created simulation when explicitly configured not
killed. Existing safety state is never opened/reset. Reservations become simulated
inventory only through the existing simulation-owned handoff and durable tombstones.
No trading process, broker ticket, Demo order approval or live execution path exists.
A rerun must use fresh isolated state; this is deterministic replay, not in-place
crash-resume or a way to reset trading losses. Existing directories are refused.

## Metrics and reports

`write_report(result, new_directory)` writes reproducible JSON, metrics/events/equity/
trades/decisions CSV, Markdown and SHA-256 checksums. CSV has fixed LF endings and
escapes spreadsheet formula prefixes. Reports preserve full inputs, timestamps,
source/review references, timeframe, rules, risk/cost policy and input digests.
Retain the Git SHA and Python version with research outputs. Canonical inputs use
UTC instants; `original_bar_timestamps` and `original_source_retrieved_at` additionally
preserve original offset strings. Source archive bytes are not rewritten.

- `total_return` and `net_return`: final marked EUR equity / starting EUR minus one.
- `gross_return`: net marked outcome with attributed USD costs added back at final
  FX. It is an accounting attribution, not a separately rerun cost-free strategy.
- Win rate, average win/loss USD, profit factor and trade count use completely closed
  positions, aggregating partial exit P&L and commissions. They exclude unrealized
  P&L, portfolio funding FX and EUR translation. Undefined ratios remain null.
- Maximum drawdown uses observed EUR equity, including funding costs. It is not an
  unobserved intrabar worst drawdown. Costs are attributed USD, including funding FX.
- Reports include rejected/missed entries, ambiguous stop-first exits, deadline
  breaches, source/session/bar coverage, open inventory and evidence limitations.

Cash EUR (unconverted, zero interest) and funded USD cash are explicit accounting
benchmarks. Hourly momentum/trend/reversion and buy-and-hold comparisons remain
blocked until separate timeframe, common-window, cost/FX and passive overnight
eligibility evidence is reviewed. We do not aggregate 5Min bars into hourly inputs,
pretend the old midnight-bound hourly datasets match this window, or compare
incompatible percentage returns. No such independent comparison dataset exists here.

## Chronological evaluation and Monte Carlo

`evaluation.evaluate_split(data, plan, existing_Split, new_directory)` evaluates
complete, non-overlapping train/validation/test sessions under one predeclared plan.
Boundaries start at session opens; the exclusive end must follow the final close.
There is no automatic parameter search or validation/test selection. `walk_forward`
allows expanding/rolling past training but requires disjoint chronological test
windows. Each window starts a separate EUR-funded portfolio: returns are not silently
stitched into one continuously funded portfolio. Warmup from a prior day is not needed
for this same-session 15-minute range.

`monte_carlo.intraday.compare(training_results, held_out_result, as_of=..., seed=19)`
is a separate interface; the original synthetic-only Monte Carlo Pool is unchanged.
Require 20–10,000 complete, chronologically ordered, disjoint **single-session** runs,
all ended/known by `as_of`, strictly before held-out session start. Block mixed
synthetic/historical labels, changed policy, instrument/assumption incompatibility,
open inventory or multi-session horizons. Digests recheck normalized input manifests.

Exactly 10,000 seeded draws sample whole session outcomes uniformly with replacement.
Each retains the original same-capital risk-admitted size, costs, fills and intraday
dependence. These are independent single-session **outcome bootstrap stress draws**,
not new market paths, 10,000 independent observations or a compounded portfolio.
They cannot rerun dynamic risk admissions under a different evolving equity, discover
unseen tails or establish predictive probabilities. Pool size does not improve genuine
coverage. The held-out result is compared after the training-only pool is frozen; it
is never sampled into training. Reports include percentile returns, loss frequency,
95% return VaR/expected shortfall, costs and the held-out empirical rank.

## Offline commands and performance

No keys, environment setup or external requests are required:

```bash
python -m pytest tests/test_intraday_replay.py tests/test_intraday_evaluation.py -q
python -m etoro_demo_bot.backtest.intraday --output .historical-data/orb-synthetic-500 --eur 500 --seed 19
python -m etoro_demo_bot.backtest.intraday --output .historical-data/orb-synthetic-1000 --eur 1000 --seed 19
python -m etoro_demo_bot.backtest.intraday.benchmark
```

Each demo creates 20 prior synthetic sessions and one held-out synthetic session,
individual reports/state and a 10,000-row comparison. It never loads genuine bars or
credentials. Keep output directories new; do not delete real safety state to rerun.
See [Windows instructions](WINDOWS_SETUP.md) for explicit interpreter paths.

The benchmark times 21 full 78-bar synthetic sessions including local SQLite risk/
journal work, then the separate 10,000-draw bootstrap. It uses `perf_counter` outside
the reproducible financial reports. CI runs it on Ubuntu and Windows and checks
qualification/trial count, not a flaky hardware-specific timing threshold. Bars are
consumed once in availability order; input size and simulation trials are bounded.
No LLM call, I/O service, scheduler or trading-decision callback is involved.

Local measurement on 2026-10-28, CPython 3.12.14 in the development container:
21 synthetic sessions, 78 bars each, with one eligible ORB decision per session.
Replay median **0.1593 s**, nearest-rank P95 **0.1735 s** (including risk/journal SQLite
work); 10,000-draw bootstrap **0.0628 s** including input-integrity checks, excluding
report serialization. These are one environment's compute measurements, not network,
publication-to-decision or execution latency guarantees. CI emits its own timings.

## Remaining blockers and next phase

No genuine replay or profitability result is supplied. Resolve legal usage, original
capture/revisions, full native IEX coverage, corporate actions and historical calendar
reviews before a genuine point-in-time dataset can pass. Supply separate quote/depth,
FX, costs, earnings, eligibility/minimum/step evidence or explicitly reviewed conditional
research assumptions. A review string alone cannot prove those facts. In particular,
ordinary Alpaca downloads currently cannot substantiate earlier decision availability.

Next phase: audit an owner-provided, legally obtained capture bundle read-only;
produce a blocked/conditional qualification report before running any metrics. Then
validate measured fills/costs against observations and define independently compatible
hourly/passive comparison datasets. More detailed intrabar/halts/queue modelling and
restart checkpoints need separate reviewed contracts. No trading activation, leverage
research or production risk changes are included.
