# Phase 13: 15-minute ORB research

This is a proposal-only, long-only research strategy (`orb-15m-v1`). It does not
place orders, create broker tickets, arm the kill switch or enable execution.
Hourly strategies and their data contracts remain unchanged. Synthetic fixtures
validate behavior, not profitability or historical coverage.

## Rules and timestamps

- Use the exact versioned `FIVE_MINUTE_RESEARCH` contract and the reviewed XNYS
  regular session, including DST, holidays and early closes. The current reviewed
  calendar is limited to 2026; unsupported dates fail closed.
- The first three completed, known five-minute candles define the opening high
  and low. A later completed close must be strictly above that high. A wick or
  an equal close is insufficient. There must be a contiguous, ordered prefix
  from the session open through the latest completed interval: no gaps, duplicates,
  overlaps, misalignment, forward filling or hourly-to-five-minute conversion.
- Only bars completed and first known by the decision time are visible. The latest
  completed interval must be present and fresh. Source retrieval and calendar
  evidence cannot come from the future. Later-retrieved historical data cannot
  generate an earlier point-in-time signal. Future candle prices do not enter the
  signal or its input digest. The Phase 1 full-session archive qualifier is unchanged.
- With volume confirmation disabled (default), missing volume is not invented.
  When enabled, require explicit complete, same-snapshot IEX volume evidence and
  nonnegative native volumes. Compare the confirming volume with the mean of the
  first three candles times the configured ratio (1–10). This is IEX-local volume,
  not consolidated market volume. Evidence is a caller-reviewed assertion, not
  independent proof of source completeness. A thin crossing may be followed by
  a later volume-qualified close.
- Use the first eligible confirmation. Its completion time starts a maximum
  60-second entry lifetime (configurable downward). Retrieval, a new quote or a
  second breakout cannot refresh that lifetime. Entry also expires by 90 minutes
  after the open by default (configurable 20–180), and before the exit deadline.
- Require a fresh real-time bid/ask. Bid at or below the opening high invalidates
  entry. Planned entry is the current ask, bounded by both 0.2% above the confirming
  close and 1% above the opening high by default. Reject opening ranges wider than
  5% of their high. These research parameters are assumptions, not optimized results.
- Stop is the opening-range midpoint by default, optionally its low, rounded down
  consistently with quantity precision. Target defaults to 2R of price risk; it is
  not a guaranteed fill or net return. Exit deadline defaults to 15 minutes before
  the actual session close. A smaller ORB buffer cannot weaken the existing safety
  rules' close buffer. A deadline is proposal metadata, not an automated exit order.

Sizing uses the existing budget, FX, broker minimum/step, liquidity, spread,
round-trip cost, earnings blackout, instrument eligibility and conservative account
checks. Existing risk limits remain independently enforced by `RiskEngine`.
EUR 500 or EUR 1,000 may yield no eligible proposal after minimums and costs.

## Interfaces and safety

`strategy.orb` exposes `OrbRules`, `OrbContext`, `VolumeEvidence`, `OrbProposal`,
`OrbOutcome`, pure `make_proposal`, and journaled `OrbResearchEngine`.
`StrategyEngine.propose_orb(context, now=..., rules=...)` is the separate facade;
`review_orb(candidate, context, risk, now=...)` explicitly hands a revalidated
proposal to the unchanged Risk Manager. Existing hourly `propose` stays hourly.

The context supplies a qualified research series and existing typed instrument,
quote, evidence and account snapshots. It must carry an intraday `Rules` policy.
The result explains the range, confirmation, stop, target, invalidation, entry and
exit deadlines, evidence timestamps, source snapshot, input/policy digests and
replay blockers. `execution_authorized` is always false. `OrbProposal` is separate
from the executable strategy `Candidate`; no executable journal claim is created.

Use a dedicated research journal and RiskStore, isolated from any trading process.
The journal atomically permits one proposal per account/instrument/session,
regardless of rule changes. Review requires the exact journaled proposal and
unchanged normalized evidence, checks expiry, and can run only once. A risk pass
reserves local research capacity; it does not authorize an order. The research
engine never clears a kill switch. An initialized, killed RiskStore rejects review.
Changes of evidence require a new decision; they cannot silently modify a claimed
proposal. There is no network client, credential loading, CLI execution mode,
broker adapter or automated exit loop in this module.

## Evidence and limitations

The sole external Trader Skill reference is
[day-trader-skill trader-entry](https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/trader-entry/entry.py).
Its first-15-minute range and subsequent-close concept informed this independent
implementation. No upstream code was copied. The reference root MIT license was
reviewed; this module adds this repository's stricter session, provenance,
point-in-time, sizing and proposal-only boundaries. See
[the migration evidence](DAY_TRADER_EVIDENCE.md) and
[five-minute contracts](FIVE_MINUTE_CONTRACTS.md).

No credentials or authenticated market-data requests were used. Actual symbol/date
coverage, original publication latency, completeness and native IEX volume remain
unverified. A typed snapshot or fixture cannot establish historical first-known
availability. Ordinary downloads made after a session cannot substantiate an
in-session decision under this contract; original capture evidence or an explicitly
reviewed replay availability model is needed before genuine replay comparisons.
The current contract does not infer missing no-trade candles or consolidated volume.

There is no fill simulator, stop/target intrabar ordering assumption, halt handling,
slippage calibration, auction model or overnight carry implementation here. A
five-minute close gives no evidence that the planned ask could actually be filled.
Historical eToro eligibility, spreads, fees, FX, fractional availability, market
sessions and corporate actions still require point-in-time evidence. Execution
leverage remains disabled. Existing backtesting and Monte Carlo hourly interfaces
are preserved; this phase does not feed five-minute observations into them or
claim genuine-data returns. Structured proposals and provenance are the handoff
for a future explicitly qualified intraday replay adapter and scenario comparisons.

## Offline validation and next phase

Run `python -m pytest tests/test_orb.py -q` on Ubuntu or Windows with the repository's
locked development environment. These deterministic tests block socket connections
and credential loading. They cover strict crossings, gaps, malformed prefixes,
volume gating, expiry, quote chase, session transitions, DST/early closes, evidence
freshness, tampering, duplicate claims, future-price noninterference and actual
kill-switch, position-limit and daily-loss risk rejection.

Next: implement a research-only intraday event replay adapter with explicit
availability evidence and conservative next-observation fills, costs, session-end
liquidation and ambiguous intrabar stop/target handling. Compare ORB variants and
no-trade baselines with the existing risk rules, then add seeded Monte Carlo
comparisons of qualified replay outcomes. Obtain genuine data only through a
separately user-activated read-only workflow; do not relax provenance to make a
historical backtest pass. No trading activation is included in this phase.
