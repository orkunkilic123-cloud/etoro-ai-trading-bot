# Phase 11 — Monte Carlo Simulation Agent

An **offline advisory research tool**, not an execution agent. It produces 10,000 conditional
outcomes for one existing Strategy Engine candidate after one unchanged Risk Manager review.
No credentials, market-data download, broker client, tickets or execution callback are used.
No production strategy, risk limit, kill switch or execution setting is modified.

## Reference review

Reviewed on 2026-10-28 (Europe/Amsterdam), upstream commit
`3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd`:

- [Repository](https://github.com/Jakeschincariol/day-trader-skill)
- [trader-timemachine specification](https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/trader-timemachine/SKILL.md)
- [Implementation](https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/trader-timemachine/timemachine.py)
- [MIT license](https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/LICENSE),
  copyright 2026 Jake Schincariol. Redistribution of substantial upstream code requires
  retaining the copyright and permission notice.

Its documented implementation samples 5-minute OHLC ratios from at least 20 full prior sessions,
using time-of-day neighborhoods, default seed 19 and 10,000 replays. It reports stop/target/close
frequencies, percentiles, average R, historical setup replay and a heuristic verdict. It supports
offline input and an unofficial Yahoo 60-day/5-minute downloader. Those upstream availability
claims were not independently authenticated or adopted as licensed market-data access.

Important differences: upstream counts gap-through-stop outcomes as -1R, omits transaction costs,
and its historical rule is an opening-range breakout, not this project's three strategies.
This implementation was written independently; no upstream code or market-data fixture was copied,
no upstream script was executed and no Yahoo downloader was added. Upstream permissions for
live trading/leverage are not project permissions. We do not adopt its heuristic verdict or claim
that a resampled frequency is a predictive probability.

## Architecture and workflow

- `models.py`: immutable bounded OHLC-ratio blocks, point-in-time pool and seed settings.
- `engine.py`: candidate generation, normal strategy/risk review, whole-block sampling,
  conservative stop/target processing, P&L/cost attribution and tail metrics.
- `fixtures.py`: explicitly synthetic prices, gaps, eligibility, FX, earnings and sessions.
- `report.py`: deterministic JSON manifest/all trials, CSV, Markdown and byte checksums.
- `__main__.py`: offline synthetic demo for EUR 500/1,000 in an exclusively new directory.

Compose `MonteCarloAgent().run(context, pool, strategy, risk, now=..., settings=Settings(seed=19))`.
Supply the existing StrategyEngine and RiskEngine, not an execution client. The agent validates
the pool before proposing, then calls `StrategyEngine.propose` and `StrategyEngine.review`.
The latter checks the immutable strategy journal and invokes the actual RiskEngine.

A successful review reserves capacity **once**, not 10,000 times. The reservation remains and
duplicate claims persist. Re-running against the same state is blocked; it is not a way to
release capacity or reset daily losses. Reproducibility tests use separately initialized synthetic
state with identical inputs. Production safety stores must never be reset for a research rerun.
If simulation/reporting fails after review, the existing reservation remains; no automatic retry
or release is performed. Pool/preflight failures produce no risk reservation, although strategy
generation can already have journalled a proposal claim.

Kill switch, daily 3% loss halt, maximum 1% planned risk, cash, exposure, leverage=1, stale evidence,
eligibility/minimum/step requirements and duplicate protection stay in the original engines.
The extra simulated-entry check includes entry slippage/fees and the available EUR-funded budget.
A simulated distribution is not fresh fill approval: a future execution coordinator would still
need current risk checks and exact authorization. There is no such handoff here.

## Sampling and point-in-time contract

Exactly 10,000 trials, seed an explicit unsigned 64-bit integer. A private
`random.Random(seed)` chooses one complete empirical horizon block uniformly with replacement
for each trial. OHLC ratios within that block retain ordering and dependence. Blocks are not
spliced bar by bar, and no Gaussian tails, prices or interpolated missing candles are invented.

Require at least 20 and at most 10,000 non-overlapping, chronologically ordered blocks. Each has
1–128 valid positive bounded OHLC-ratio steps, an aware start/end/known-at timestamp and the same
explicit horizon of at most seven days. Every block must have ended and been known by the decision.
A canonical SHA-256 of all normalized block contents guards integrity; it is not a raw-provider
checksum or a proof of authenticity. Timestamp checks cannot establish truthful provenance.

The current release deliberately accepts **synthetic pools only**. A historical classification
fails closed. No trustworthy full historical block archive has been qualified, and downloading
bars alone would not establish original revisions, corporate actions, executable prices,
session timing or free reuse rights. A future historical adapter must preserve raw provenance,
validate raw/as-traded ratios around actions, missing bars, original publication/revisions,
exchange/session/DST alignment, selection bias and symbol eligibility before enabling that label.

Each block represents a specified research horizon, not an actual forecast session. The synthetic
demo uses six hourly steps. Intraday horizons cannot extend beyond the candidate's existing exit
deadline; all horizons must fit its reviewed swing planning window. Original session and earnings
entry gates still run. The simulator does **not** implement dynamic earnings, trailing-stop,
technical-exit or future closure replay; use the independent event-driven Backtesting Engine for
that separate question. These are static stop/optional-target stress outcomes conditional on
entry, not a reproduction of full strategy returns.

## Fill and cost assumptions

All trades are long, unleveraged USD underlying proposals already sized by StrategyEngine.
Use the supplied decision quote's relative half-spread, held constant across a scenario.
Entry is candidate ask with half the declared round-trip slippage. Mid-price paths compound the
sampled OHLC ratios; exits use bid minus half the round-trip slippage.

For each step:

1. An opening bid through the stop exits at that opening bid, not the stop level.
2. An opening bid through an optional target exits at the target, with no favorable gap improvement.
3. Otherwise, intrabar stop precedes target if both are touched (unknown ordering is pessimistic).
4. If neither hits, continue. At the final horizon, calculate a hypothetical bid liquidation.

Targets are optional, taken unchanged from the candidate. There is no new profit cap or automatic
target optimization. Default strategy targets remain unset; the CLI demo explicitly chooses 2R
only for exercising target mechanics. Stop/target prices are analytical levels, not broker orders.
Full fills and immediate stop liquidity are assumptions; halts, partial fills, latency and queue
priority are not modeled. Gaps can exceed the 1% planned loss; reporting that stress loss does not
relax the admission limit or promise that a stop can cap losses.

Commission = fixed round-trip fee + half the proportional round-trip fee on each fill's notional.
Spread/slippage are embedded in execution prices and attributed as costs, never deducted twice.
The FX conversion charge applies once to the entire starting EUR portfolio. Expected trade P&L
and tail metrics are USD, excluding account funding FX. Portfolio P&L in EUR includes that funding
charge and translates at the same fixed supplied USD/EUR rate. There is no future FX forecasting,
conversion-back spread or interest. Untouched cash has zero return. All rates, minimums and
fractional eligibility in bundled demos are synthetic assumptions, not verified broker facts.

## Metrics, reports and reproducibility

Reports contain all 10,000 draws, sampled block indexes, exit steps/reasons/prices, trade P&L,
costs and EUR portfolio P&L. Summary reports include outcome counts, conditional loss frequency,
expected P&L, expected final EUR equity, funding/total costs, worst loss, nearest-rank P05/P50/P95,
95%/99% value-at-risk and expected shortfall. VaR is max(0, negative lower P&L quantile);
expected shortfall is max(0, negative mean of the worst 500/100 outcomes). These are empirical
conditional loss measures, not guarantees or out-of-sample confidence bounds. We also report
the fraction of paths losing more than the original planned risk.

JSON archives the normalized pool, context, candidate, rules, risk policy/decision, seed and
model version. The input digest covers those inputs and the state-dependent decision. Retain the
Git commit and Python version alongside reports; reproducibility is tested on the supported
Python 3.12 runtime. Decimal precision is isolated at 60 digits; no global RNG or wall clock
enters calculations. The same inputs, source version, seed and initial state produce identical
report bytes; LF CSV/JSON bytes and SHA-256 are preserved across platforms.

The demo creates an isolated new synthetic risk database and explicitly clears only its initial
synthetic kill switch. It refuses an existing output directory. It never opens ordinary risk
state, reads environment credentials, connects to a service, or enables execution.

## Limitations and next phase

The 10,000 paths are resamples of a small scenario pool, **not 10,000 independent historical
observations or sequential portfolio trades**. They cannot reveal unobserved tail events.
There is no volatility/regime calibration, parameter optimization, daily trade quota or learning
update. Scenario profitability is not evidence of a profitable strategy. A daily halt is checked
at candidate admission; this is not a multi-trade portfolio survival simulation.

Next: qualify licensed point-in-time historical blocks and historical execution costs, validate
against held-out event-driven backtests, test regime/volume/session stratification and liquidity/
partial-fill stress, and independently assess calibration. Any future learned changes require
human review and must not modify risk ceilings or execution permissions.

## Phase 14: separate intraday outcome comparisons

The original Agent/Pool interfaces above remain unchanged and synthetic-only.
`monte_carlo.intraday.compare` separately bootstraps 10,000 prior single-session ORB
replay outcomes with frozen cost/risk assumptions, chronological separation, explicit
evidence classification and no open inventory. This resamples completed outcomes,
not new price paths or evolving-equity portfolio risk admissions. See
[INTRADAY_REPLAY.md](INTRADAY_REPLAY.md) for the precise gate, tail metrics, limitations
and offline synthetic commands. No genuine dataset was used in Phase 14.
