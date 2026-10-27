# Phase 2: risk management foundation

This offline module evaluates normalized proposals. It never reads credentials, fetches account data, builds broker orders, or invokes the API client. A PASS means only that risk checks passed and local capacity was reserved. `execution_authorized` remains false. Existing broker routing still allows only the two GET endpoints; execution and autonomous trading remain disabled.

## Modules and contract

- `risk.models`: immutable policy, account snapshot, per-instrument exposures, proposal and decision types.
- `risk.engine`: deterministic validation, calculations, reason codes and atomic capacity reservation.
- `risk.state`: SQLite emergency switch, immutable daily baselines, latched daily halts, clock watermark and reservation ledger.

All money, prices and quantities must be finite `Decimal` values, never binary floats. Inputs are bounded to 24 significant digits and scale/exponent ±12; unsupported calculated precision fails closed. Calculations use an isolated 60-digit Decimal context, unaffected by application-global precision. Currency is USD only. Callers supply an explicit timezone-aware `now`; timestamps are compared in UTC. No current-time lookup, randomness or network call occurs in risk evaluation.

Account inputs must explicitly attest Demo identity, completeness and reconciled external cash flows; their defaults are false. These flags are assertions by the future trusted normalization adapter, not verification performed by this module. Every exposure is a positive USD market value and positive position count, grouped once per instrument, including all open positions and broker-pending openings. Complete fresh portfolio valuations are required; missing or unpriced holdings must never be silently omitted. Available balance must already exclude broker-reserved cash. Incomplete/partial API results cannot be treated as complete snapshots. Quote type must be `realtime`; delayed, future-dated, missing or older-than-policy data is rejected. Default maximum age is 60 seconds for both quote and account; exactly 60 is accepted.

## Rules and formulas

For a long proposal with units U, entry price P, stop S and conservative total fee/slippage buffer C:

- Require P > 0, U > 0 and 0 < S < P; C >= 0 must be explicitly supplied.
- Estimated stop-loss risk = U × (P − S) + C.
- Reject risk > current account equity × 0.01. Exactly 1% is permitted. This hard ceiling cannot be relaxed by configuration.
- Notional = U × P; cash/capacity reservation = notional + C.
- Require leverage exactly 1, side `buy`, verified unleveraged underlying asset and settlement `real`. As documented by eToro, `real` here means underlying-asset settlement within Demo, not real-money routing. Derivatives and shorts are forbidden.
- Position allocation (including C), total gross exposure, per-instrument exposure, cash and position counts must all remain within limits after adding the candidate and every prior local reservation.

Defaults: maximum new-position allocation 20% of equity, aggregate exposure 80%, per-instrument exposure 25%, at most five concurrent positions. Fractions can be configured in (0, 1]; count and freshness limits are validated positive integers. Reservations each count as one prospective position. Equality with a capacity limit is permitted; exceeding it is rejected.

The 1% figure is an estimated stop-based loss, not a guaranteed realized loss: market gaps and fills can exceed a stop. The caller must provide a conservative cost buffer. No leverage or broker order is enabled by this calculation.

## Daily drawdown

A trusted UTC start-of-day opening equity must be explicitly recorded with `establish_day(date, equity)` before evaluation. Never initialize the baseline from the first midday observation: that could erase earlier losses. Missing baseline blocks proposals. Baselines cannot be overwritten or backdated. Daily loss includes realized and unrealized equity movement relative to this fixed baseline, not the intraday peak.

Current equity <= opening equity × 0.97 latches a persisted halt for that UTC date, including zero or negative equity. Recovery later that day, restart, or clearing the emergency switch cannot reset the daily halt. A new UTC day needs a new verified opening baseline. The emergency switch persists independently across days. External deposits/withdrawals require a correctly reconciled baseline/current-equity basis; unresolved flows must set `cash_flows_reconciled=False` and block evaluation. This phase does not implement a cash-flow accounting adapter.

The engine can only detect losses in snapshots it receives. There is no background equity monitor yet. A future monitor must feed every valid equity update; an unobserved dip cannot be inferred. The persisted clock watermark rejects evaluations earlier than the last accepted observation time, including after restart.

## Persistence, duplicates and emergency control

Use one persistent database per Demo account, shared by every risk evaluator for that account. Store it outside the checkout or in ignored `.risk-state/`; protect file and parent-directory access with OS permissions. Treat it as safety-critical local data. `RiskStore.initialize` explicitly creates a new file exclusively and starts the kill switch **active**. It refuses to overwrite existing state. Ordinary evaluation opens an existing DB with SQLite `mode=rw`, never recreating a missing file.

`set_kill_switch(True)` activates the emergency switch; clearing requires `set_kill_switch(False, acknowledged=True)` as an explicit administrative act. Neither action authorizes trades. Administrative errors propagate; the caller must not report success on error. Evaluation converts missing, corrupt, locked, unsupported-schema or inaccessible state into a rejection. SQLite `BEGIN IMMEDIATE` serializes checks and reservations across processes; commit failure returns rejection, never PASS. Full synchronous writes and transactional commits preserve state on restart. An evaluation committed just before a kill-switch transaction may have returned PASS; that still carries no execution authority. A future executor must recheck the switch and risk state immediately before submission.

Duplicate protection checks both the caller's stable proposal ID and an economic-intent SHA-256 (instrument, units, price, stop and buffer). Decimal representations such as 10.0 and 10.00 canonicalize identically. Changing the ID does not bypass an identical intent; reusing an ID for changed terms is also rejected. Account identity is fixed by the store. Quote timestamps are excluded from the fingerprint.

A PASS atomically stores a reservation; a rejection stores none, although clock observations and daily-loss latches can persist. Repeated evaluation of a passed proposal returns DUPLICATE_PROPOSAL. Identical inputs and initial persistent state yield identical decisions; state transitions intentionally affect subsequent results.

Reservations do not expire automatically, survive day rollover and restart, and have no release API in this phase. They conservatively continue consuming cash, exposure and slots. If future broker snapshots also include the same intent, it may be double-counted rather than undercounted. Before future execution, implement explicit reconciliation/release tied to confirmed broker outcomes while retaining duplicate tombstones. Do not delete/reinitialize the database to regain capacity. Missing state is a recovery incident; neither automatic recovery nor protection against an administrator deliberately tampering with a valid database is implemented. Use trusted local storage, not an unreliable shared network filesystem.

## Minimal offline example

This is synthetic local state, not an eToro connection or authorization:

```python
from datetime import UTC, datetime
from decimal import Decimal as D
from pathlib import Path
from etoro_demo_bot.risk import AccountSnapshot, Proposal, RiskEngine, RiskStore

now = datetime(2026, 10, 27, 12, tzinfo=UTC)
# Use a new path for a new synthetic account only; never replace existing safety state.
state = RiskStore.initialize(Path("synthetic-risk.sqlite"), "synthetic-demo")
state.establish_day(now.date(), D("10000"))  # trusted start-of-day equity
state.set_kill_switch(False, acknowledged=True)
account = AccountSnapshot(
    "synthetic-demo", D("10000"), D("10000"), (), now,
    demo=True, complete=True, cash_flows_reconciled=True,
)
proposal = Proposal(
    "idea-1", 1, D("9"), D("100"), D("90"), now, D("10"),
    underlying_verified=True,
)
result = RiskEngine(state).evaluate(proposal, account, now=now)
assert result.passed and result.risk_amount == D("100")
assert result.execution_authorized is False
```

## Reasons and validation

Decisions carry stable reason codes: INVALID_INPUT/TIME/ACCOUNT/BALANCE/EXPOSURE/PROPOSAL/PRICE/STOP_LOSS/CALCULATION, STALE_ACCOUNT/MARKET_DATA, STATE_UNAVAILABLE, MISSING_DAILY_BASELINE, CLOCK_ROLLBACK, KILL_SWITCH_ACTIVE, DAILY_LOSS_LIMIT, LEVERAGE_FORBIDDEN, INSTRUMENT_FORBIDDEN, DUPLICATE_PROPOSAL, TRADE_RISK_LIMIT, POSITION_SIZE_LIMIT, TOTAL_EXPOSURE_LIMIT, INSTRUMENT_EXPOSURE_LIMIT, CONCURRENT_POSITION_LIMIT and INSUFFICIENT_BALANCE. Successful evaluation reports RISK_PASS_EXECUTION_DISABLED. Validation returns early on unusable inputs; applicable numeric capacity failures are returned together in fixed order.

Tests cover exact 1%/3% boundaries, buffers, invalid Decimal values, stale/future timestamps, incomplete accounts, exposure/cash/slot limits, numeric canonicalization, cross-restart duplicate/kill/daily state, UTC rollover, clock rollback, corruption, missing/locked state, transactional concurrency and unchanged order-route rejection tests. Future broker integration, cash-flow reconciliation and actual instrument eligibility remain separate, unimplemented prerequisites.
