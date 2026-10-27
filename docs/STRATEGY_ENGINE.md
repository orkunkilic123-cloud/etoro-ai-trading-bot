# Phase 5: deterministic proposal engine

The `strategy` package consumes scanner opportunities and independently timestamped evidence. It produces **risk proposals and exit advice, never orders**. It imports no execution client, credential loader or network library, offers no execution callback and adds no broker endpoints. Network scanning and autonomous execution remain disabled by default. No credentials or authenticated API requests were used in development. No strategy profitability is claimed; independent point-in-time backtesting and out-of-sample validation remain necessary.

## Architecture and composition

| Module | Responsibility |
| --- | --- |
| `models` | Frozen rules, point-in-time bars/evidence, candidates, earnings coverage, position observations and outcomes |
| `rules` | Pure long-only breakout, trend-following and mean-reversion conditions and regime classification |
| `engine` | Evidence validation, deterministic selection, Decimal sizing, expiry and explicit risk handoff |
| `exits` | Position monitoring: hold, propose-close or blocked advice, with optional ratcheted stop suggestion |
| `journal` | Separate SQLite decision events, immutable proposal claims, replay protection and review status |

Compose `StrategyEngine(Journal(...), Rules(...))`, then call `propose(Context(...), now=aware_time)`. Context contains the scanner Opportunity, its timestamped source bars, fresh account snapshot and explicit Evidence. Generation never calls RiskEngine or reserves funds. A returned candidate is **unreviewed** and cannot authorize execution.

A trusted coordinator may explicitly call `engine.review(candidate, account, RiskEngine(store), now=...)`. This checks journal identity and expiry, calls the **existing** RiskEngine unchanged, and records the decision. A risk PASS reserves local capacity and still has `execution_authorized=False`. It does not construct an execution Ticket. The 1% maximum risk, 3% daily halt, emergency switch, leverage=1, balance/exposure/position limits, stale-input checks and risk duplicate protections all remain mandatory. Final broker eligibility, identity, prices, risk and exact human authorization still need revalidation in any future separately approved execution integration.

`ExitMonitor.evaluate(position, quote, bars, evidence, now=...)` is independent of an expired entry signal. Positions require fresh externally verified position and risk-monitoring observations. A `propose_close` result has no broker payload, execution permission or reservation release. The existing RiskEngine lacks a dedicated reduce-only close policy; integrating these recommendations with closing approval/risk remains future work. Never treat advisory stops or targets as broker-installed orders.

## Point-in-time contract and look-ahead prevention

All decision times and evidence times must be timezone-aware. The implementation normalizes decision times to UTC and accepts no implicit current clock. Each ObservedBar supplies both its hourly candle start and **availability time**, including publication/revision latency. A completed bar cannot have been available before its end. Only bars completed and available by the scanner opportunity's creation time may reproduce entry features. Later bars/revisions are excluded. Features are recomputed using the scanner's exact indicator implementation and must equal the scanner features; disagreement is rejected. No future bar high, close or volume is used for an entry or trailing stop.

The scanner signal itself must have existed at decision time and remain unexpired. Quotes cannot postdate the signal. Freshness/identity checks cover account, eligibility, product, session, FX, cost-evidence snapshot and liquidity. Optional fundamentals cannot postdate the signal or be expired. Supplied evidence has an explicit `available_at`; sources must report when facts were actually knowable, not merely the period to which they refer. A backtest must retain historical revisions and historical universe/eligibility, rather than using today's adjusted data or surviving instruments. Timestamp validation cannot prove a provider supplied truthful provenance.

The scanner's coverage review remains a prerequisite: unexplained gaps, inconsistent adjustments and incomparable volume cannot be attested complete. The strategy reuses the documented hourly history contract; intraday here means hourly decisions with session exits, not minute-level trading. No new historical/earnings capability is inferred from eToro's API.

## Entry selection, regimes and conflicts

Rules are frozen and versioned; their full canonical content receives a SHA-256 digest and accompanies each candidate. Default gates require scanner score ≥15, per-bar volatility ≤0.05, spread/ask ≤0.5%, verified daily dollar volume ≥USD 1 million, and estimated total costs ≤2% of notional. These are configurable research defaults, not evidence of optimal parameters. Scores remain rankings, not probabilities.

Regime classification uses only validated features: EMA20 > SMA20 with positive momentum is an uptrend; EMA20 < SMA20 with momentum below −5% is a downtrend; otherwise range. The current regime classifier is a fixed, version-controlled heuristic. It is not a predictive market model.

- **Momentum breakout:** uptrend, close above prior 20-bar high, 10-bar momentum ≥2%, relative volume ≥1.2.
- **Trend following:** uptrend, close > EMA20 > SMA20, MACD > signal, relative volume ≥1.2.
- **Mean reversion:** range, RSI ≤30, close below SMA20 − ATR. A strong downtrend is excluded.

Thresholds and enabled strategies are configurable. Missing relative volume blocks breakout/trend entry. Compatible breakout and trend signals consolidate into one breakout proposal. Mean-reversion contributions conflicting with breakout/trend contributions cause rejection. Duplicate score contributors or a score inconsistent with its contributions are rejected. No matching strategy is journalled as a missed opportunity. There is no daily trade quota or obligation to produce a candidate.

## Intraday, short swing and exit rules

The same strategies can use either style:

- **Intraday:** requires a trusted session close known at decision time. New entries stop at session close minus the configurable buffer (15 minutes default). That deadline becomes an exit-review trigger; no exchange timezone, holiday or DST schedule is guessed.
- **Short swing:** requires earnings coverage across the configurable forward planning horizon (three days by default). The horizon is **not** a forced liquidation deadline. Coverage and risk must be renewed while a position runs. There is no default maximum profit or time-held cap.

Entry stop = ask − configurable ATR multiple (default 2). Stop precision is conservatively rounded down within the existing risk calculation's Decimal scale limit. This is a proposed analytical stop, not a claim about broker tick/stop constraints. Default trailing advice is max(existing stop, max(prior verified peak bid, current bid) − 3×ATR). It never suggests loosening the existing stop. The peak must have an observation time no later than the decision and no earlier than the position opening. A changed advisory stop is never installed automatically; a trusted position manager must retain acknowledged stop/peak state.

Exit priority is: existing stop breach; fresh risk monitor reports invalid risk; intraday deadline; earnings blackout; trailing stop; optional configured take-profit target; mean-reversion completion (bid ≥ SMA); trend invalidation (bid < EMA). Trend-loss and mean-completion exits can be disabled explicitly in Rules; risk/stop safety checks cannot. Unknown/stale data, closed markets or insufficient earnings coverage return `blocked`, requiring operator attention rather than silently declaring a safe hold. Safety-triggered advice can be emitted without waiting for optional technical data. Gaps or closures can prevent timely exits; no realized-loss guarantee is implied.

`take_profit_r=None` is the default. A configured positive R multiple produces a target based on initial stop distance; it is an explicit strategy choice, not an arbitrary global profit cap. No take-profit API support is implemented or assumed. Exit advice never grants permission to close, cancel or modify a position.

## Earnings-event awareness

`EarningsCalendar.window(instrument_id, as_of=...)` is the future provider interface. `EarningsWindow` records when the calendar was known, source, instrument, covered interval, announcement timestamps and explicit completeness. Empty announcements are safe only with verified complete coverage; missing/unknown coverage fails closed. The evidence must cover the contemplated holding horizon plus the default 24-hour buffer. Events in the interval from now minus the buffer through horizon plus the buffer block entry or trigger exit advice. This intentionally conservative policy also avoids entering immediately after an announcement.

The implementation does not fetch earnings, predict outcomes or invent event endpoints. ETFs need an appropriate reviewed event policy and source; an empty tuple without verified coverage is not a bypass. Schedules can change: refresh coverage before every decision, and monitor positions outside scanner entry evaluation.

## EUR 500 and EUR 1,000 sizing

Both scenarios are tested with synthetic verified USD minimums and fractional/whole-unit eligibility. Monetary arithmetic uses an isolated 60-digit Decimal context. Usable budget is EUR equity × fresh USD-per-EUR × (1 − conversion costs); sizing uses the lower of that budget and current account equity.

Default proposed risk is 0.5% of that conservative equity, configurable only up to the existing hard 1%. Allocation defaults to 20% and is also bounded by available cash. Per-unit cost includes spread, explicit round-trip proportional fees/slippage and a conservative pro-rata FX cost; fixed round-trip fees are also included. Units are bounded by risk cash / (stop distance + unit costs), allocation cash / (ask + unit costs), and broker maximum units. Units round down to an **explicitly verified** quantity step, with whole-unit instruments requiring step 1. Costs round up; risk is rechecked after rounding. Minimum notional must meet the verified broker minimum and unsupported precision fails closed at risk review.

The reviewed eToro eligibility schema establishes minimum exposure/margin, whole versus fractional permission and maximum units; it does not establish a universal fractional increment. `quantity_step_verified` therefore needs trusted supporting evidence. No default step is invented for broker use. Unknown FX, fees, product currency, step or minimum blocks proposals. Only USD underlying stocks/ETFs are supported. A EUR 500 portfolio can fail whole-share affordability where EUR 1,000 succeeds. Scanner minimum-allocation cost screening is retained and may conservatively exclude an instrument viable only at a larger size.

Available balance and actual exposures are ultimately checked by RiskEngine. Generated candidates do not claim capacity is available until that explicit review. Broker stop bounds/tick sizes, fill prices and account-specific trading rights remain later preflight requirements.

## Journal, duplicates and failure recovery

Use a separate local file under ignored `.strategy-state/`; never reuse/delete the risk database. `Journal.initialize(path)` exclusively creates a new journal. Ordinary Journal opens use SQLite `mode=rw`; missing/corrupt/locked state blocks proposals. Keep local filesystem permissions restrictive. Events store timestamps, status, hashed signal ID, reasons, rule digests/configuration, and successful proposal/feature details for future reporting. This is local private analysis data, not telemetry; no secrets, HTTP data or credential fields are accepted. `events()` returns structured records in durable sequence order for daily/weekly reporting. No report or Learning Agent runs automatically.

One claim per account/instrument/completed bar persists across restart, even if callers change the signal timestamp, rule version or intraday/swing style. SQLite `BEGIN IMMEDIATE` serializes concurrent claims. Identical economic intent across later bars is independently checked by RiskEngine. There is no automatic claim deletion, expiry reset or daily proposal quota. Rejected/missed observations do not claim capacity.

Risk review verifies the candidate exactly matches its immutable journalled payload, consumes its review opportunity and commits `reviewing` before calling RiskEngine. It then records pass/rejection. The risk and strategy journals are separate transactions: a crash or journal failure after a risk reservation can leave a `reviewing` record. That condition blocks automatic retry and requires reconciliation; it never means no reservation exists. Risk reservations are not automatically released. Replay of a changed, expired, unjournalled or already-reviewed candidate cannot invoke risk again through this interface. No broker submission is possible on either side of this transaction gap.

The journal records valid-time strategy rejections, misses, successful proposals, risk decisions and exit advice. An invalid decision clock or unavailable storage may prevent recording; the returned blocked outcome must be surfaced by the future operator/reporting layer. Clock rollback cannot erase previously recorded decisions. This release exposes structured events, not a report generator or automatic proposal-restoration service.

## Learning Agent boundary

A future Learning Agent may read sanitized historical events and propose a **new immutable rules version**, with rationale and validation evidence. It must not write active strategy configuration, production code, approval records, risk limits, kill state or broker state. There is no live configuration mutation endpoint, plugin loader or automatic promotion path in this implementation.

Promotion requires a human-reviewed change: point-in-time replay with historical universe/revisions, costs and missing-data policy; chronological train/validation/test separation; independent out-of-sample and walk-forward checks; sensitivity/overfitting analysis; regression/security tests; and explicit approval before deployment. Record both accepted and rejected/missed opportunities to avoid selecting only winners. Keep an immutable version/digest and rollback plan. Learning recommendations cannot increase the 1% hard risk cap, remove the 3% halt, enable leverage, authorize orders or enable autonomous execution.

Python typing/frozen objects and import tests enforce application architecture, not an adversarial-code sandbox. Run any future untrusted model/agent separately without filesystem write access to production configuration, safety databases or credentials. The trusted application owns evidence, policy selection and human authorization.

## Validation and remaining gates

The offline suite covers all three strategies, both styles, EUR scenarios, whole/fractional sizing, reference chronology and delayed revisions, invalid/stale/future inputs, conflicts, costs, earnings coverage/blackouts, session closure, duplicate concurrency/restart, journal corruption, risk acceptance/rejection, uncertain risk-review commit, exit behavior and architecture import restrictions. Existing scanner, risk and execution tests also remain required. Windows commands are in WINDOWS_SETUP.md.

No backtest/performance estimate, earnings provider, point-in-time data archive, live calendar/FX/cost/product adapter, position-risk monitor, human approval UI or execution wiring is added. A production adapter must validate each evidence assertion; fixtures are synthetic and prove software behavior only. Independent strategy validation and all earlier execution deployment gates remain outstanding.
