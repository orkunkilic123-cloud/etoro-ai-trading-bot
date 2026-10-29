# Active intraday migration plan

Date: 2026-10-29. **Active offline implementation plan; no execution authorization.**
External Trader Skill reference: **Jakeschincariol/day-trader-skill only**.
All existing bot modules are retained. Nothing is restarted, deleted, merged, connected to
a broker or enabled by this plan. The current owner-approved offline scope is recorded below.

## Current execution checkpoints (supersedes historical approval/status notes below)

The owner has authorized implementation, offline tests, commits and dependent PRs for the
Windows application. No broker credential use, authenticated requests, actual orders, merging,
deployment, paid services or trading activation is authorized. No leveraged research is included.
The older phase proposals below are retained as design provenance, not a current completion claim.

Verified baseline: main `f8f3d6d`; PR #25 remains open at `aa65a21d124e34ab6d75085cc57fa98c8906a267`.
Only PR #25 was open at inspection. Its offline P&L scope is preserved. New work starts on
`feature/demo-broker-diagnostics` directly from that commit; PRs are stacked, never cherry-picked
or treated as merged. Baseline local validation was 902 passing tests; current validation is
recorded at each checkpoint below. Windows and hosted CI are separate evidence gaps.

| Milestone / observable behavior | Existing modules extended or reused | Dependency / acceptance | Status and evidence |
| --- | --- | --- | --- |
| A: Saved P&L and aggregate totals plus local safety journal produces sanitized cash/position/reservation diagnostic and actual RiskEngine rejection where evidence is incomplete | demo_cash, broker_evidence_gate, risk, execution journals | PR25; mocked response→normalization→reconciliation→risk tests; no writes to owner state | Implemented/tested: 36 diagnostic tests, 960 full-suite tests; full broker admission externally blocked |
| B: Contradictory broker execution outcomes stay unknown through restart, with exact ticket authorization retained | execution/reconcile, client, engine, tests | Same core PR as A; operation-level public v3 audit, partial/terminal/restart regressions | Implemented/tested: 22 new lifecycle tests, same 960-test run; authenticated compatibility externally blocked |
| C: One Windows command produces SHADOW results, daily/weekly diagnostics and local dashboard from hourly or 5Min ORB replay; durable scheduled slot claims suppress duplicate runs | backtest, intraday, scanner/strategy/risk and report journals | Dependent application PR; EUR500/1000 CLI demonstrations, schedule/restart/report tests | Pending application checkpoint; real-time provider wiring deferred |
| D: Offline SEC feed ingestion preserves publication/observation/revisions and exposes incomplete earnings coverage | existing earnings/strategy interfaces, new bounded source adapter | Separate dependent PR; XML safety, as-of/dedup/coverage tests | Pending news checkpoint; network source acquisition and qualified future calendar externally blocked |

Core checkpoint (Linux / Python 3.12, 29 October 2026): `python -m pytest -q` **960 passed**;
`python -m ruff check .`, `python -m ruff format --check .`, strict `python -m mypy`
(118 files), `python -m pip check`, editable installation without build isolation, Hatchling
wheel/sdist builds and wheel build from the sdist passed. Synthetic intraday CLI runs for
EUR500/1000 passed. The existing `backtest.intraday.benchmark` passed (21 sessions,
78 bars/session, 10,000 draws; replay p50 0.097s/p95 0.107s, model simulation 0.091s). See [broker diagnostics](BROKER_DIAGNOSTICS.md) and
[execution contract review](EXECUTION_CONTRACT_REVIEW.md) for supported behavior and blockers.
No credentials, authenticated broker calls or orders were used. Windows was not run; hosted CI
is unavailable under the owner's reported Actions allowance and is not replaced by local results.

External blockers remain visible in each module's documentation. No `complete=True` broker
snapshot will be manufactured from local assertions. Report-only shadow state is never imported
as real broker evidence. Future bounded autonomous Demo execution would require an explicitly
approved policy change defining eligible accounts/instruments, spend and risk bounds, monitoring,
revocation and recovery, plus separate security review of authorization. This task does not make
that change or expose an approval bypass. A powered-off PC does not execute scheduled tasks.

## 1. Direction and recommended decision

Focus research and future development on active, long-only intraday opportunities, with
explicit entry windows, preplanned exits and session-aware exposure control. Reuse the
existing eToro Demo-only architecture. Do not transplant the external pack wholesale or
create eleven competing LLM agents.

The current bot already defaults to `Style.INTRADAY`, has momentum/trend/reversion rules,
ATR-based sizing/stops, session deadlines, deterministic risk checks and journals. Its main
mismatch with the reference is **timeframe and data qualification**: many components assume
one-hour bars, whereas the reference's entry/scenario pipeline uses 1/5-minute bars.
A five-minute scanner schedule does not mean the strategy consumes five-minute candles.
Changing a download parameter alone would make data, signal completion and replay disagree.

Recommended first implementation phase, **after approval**: an offline, explicitly versioned
intraday timeframe/session contract and five-minute research-data qualification path. Keep
the existing hourly behavior as the unchanged baseline. Then evaluate one long-only
15-minute opening-range-breakout (ORB) experiment on completed five-minute bars. News and
earnings evidence follow through shared typed adapters; neither can bypass mandatory gates.
No claim is made that this strategy or a faster timeframe improves returns.

Simulation-only leverage research is permitted by the project direction, but is not enabled
here. Execution remains unleveraged. Start with unleveraged simulations so comparisons with
the current bot are meaningful; any leveraged scenario must be separately labelled and
model financing, margin/liquidation and gaps rather than merely multiply returns.

## 2. Evidence, versions and limits

| Source | Pinned commit | Scope inspected |
| --- | --- | --- |
| Current bot `orkunkilic123-cloud/etoro-ai-trading-bot` | `a2f74dbbac5410be5edd97af549442f1e0bcdb29` | Latest main, including merged PR #13; AGENTS.md; scanner, strategy, risk/state, execution, Alpaca/history, replay/backtests, Monte Carlo, journals/reports and tests |
| Sole external reference `Jakeschincariol/day-trader-skill` | `3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd` | Complete tree; all eleven SKILL.md files and implementation scripts; README, plugin manifest, LICENSE and Python test sources |

See [the evidence index](DAY_TRADER_EVIDENCE.md) for pinned file links, hashes, functions,
imports and local anchors. **Verified** below means source behavior or instructions inspected.
**Assessment** means static comparison/model concern. **Proposed** means future work only.
Upstream tools/tests were not executed, installed or imported. Live service access, installed
skill-copy fingerprints, promotional examples and profitability were not verified. Public
endpoint operation or data rights cannot be inferred from the existence of a URL in code.

A skill combines assistant instructions with a Python helper. Instructions to read a story,
interpret a release or call a broker are not necessarily implemented by the helper. The
skills are not eleven always-running services and do not constitute eleven independent
trading signals.

## 3. Exact Day Trader Skill inventory

This is the actual eleven-name inventory of the selected repository. `trader-timemachine`
is included. No other pack is used for inventory, capabilities, code reuse or recommendations.
All eleven are covered by this repository's root MIT license, copyright 2026 Jake Schincariol.
All bundled Python implementation imports are standard library; external prerequisites are
listed separately.

| # | Skill / bundled tool | Verified purpose and inputs | Dependencies and limitations |
| --- | --- | --- | --- |
| 1 | `trader-scanner` / `scan.py` | Nasdaq Trader symbol directories; Yahoo spark/chart requests; completed daily setups and five-minute ORB candidate/confirmation scan | Python, public endpoints and local universe/watchlist JSON. Listings are not eToro eligibility; no real-time or latency guarantee. [D-scanner-code] |
| 2 | `trader-news` / `news.py` | Poll Yahoo RSS and SEC Atom filings; keyword topic/ticker tagging, dedupe, seen-state, plus Yahoo price moves versus previous close | Python; SEC identification User-Agent for filings, else SEC can be skipped; local watchlist/plan/portfolio state. No stream, sentiment model or causal market-impact model. [D-news-code] |
| 3 | `trader-entry` / `entry.py` | Long-only ORB or explicit-level trigger on completed 1/5-minute Yahoo bars; optional volume test; check/watch/watchlist and offline clock | Python, local config/entry JSON and Yahoo or saved chart data. Bar polling is not tick execution; stale observed triggers are not fresh fills. [D-entry-code] |
| 4 | `trader-exit` / `exit.py` | Long-only OR midpoint/low, explicit-price, percent or ATR stop; target R/price; cent rounding and flat-by plan | Python; local entry/config/plan; Yahoo or offline bars for ATR. The fixed minimum stop distance is a heuristic, not measured spread. [D-exit-code] |
| 5 | `trader-timemachine` / `timemachine.py` | Seeded time-of-day Monte Carlo from requested 60-day five-minute Yahoo history, ORB historical replay, bands/sample paths/histogram and verdict | Python, local plan, public Yahoo or saved chart JSON/gzip. Recent sample, model and coverage limitations; not a portfolio or execution backtest. [D-timemachine-code] |
| 6 | `trader-risk` / `check.py` | Local order checks including stop, planned loss, reward/risk, entry windows, cash/position/order limits, trade counts and optional PDT check | Python; config, prices/times, portfolio and broker logs. No independently verified account identity, our kill switch or transactional reservations. Configurable live/risky-asset modes conflict with our rules. [D-risk-code] |
| 7 | `trader-budget` / `size.py` | Stop-distance sizing with cash/cap/minimum constraints and bracket proposals; retains target-weight allocation mode | Python; local plan/config/prices/portfolio; no network. USD/float/default whole-share assumptions and Alpaca payloads need redesign, not direct use. [D-budget-code] |
| 8 | `trader-broker` / `ticket.py` | Show bracket/exit tickets, check fingerprints and supplied approval text, log results/fills, prepare flatten tickets and broker arguments | Python helper has no network order transport. SKILL instructs assistant to call Alpaca MCP/IBKR, requiring separate connector, credentials and approval UI. Entire execution path is excluded. [D-broker-code] |
| 9 | `trader-alerts` / `alerts.py` | Above/below/stop/target, percent move, time and opening-bell rules; dated plan alerts and early-close flat-by adjustment; Yahoo/Stooq prices | Python, local rule/seen-state/prices; external scheduler needed for repetition; manual DST and bounded calendar tables. An alert does not place a stop or close a position. [D-alerts-code] |
| 10 | `trader-analyst` / `facts.py` | SEC XBRL reported quarterly results, margins, YoY/TTM and derived Q4; latest filing/earnings-release exhibit links | Python, legitimate SEC identification; optional metrics JSON. Release interpretation is an assistant step. No consensus forecast series or complete future earnings calendar. [D-analyst-code] |
| 11 | `trader-pelosi` / `ptr.py` | House Clerk ZIP/XML filing index, unseen PTR detection, PDF retrieval and extracted transaction rows with amount ranges | Python; optional Poppler `pdftotext`; local PDF/seen-state. Senate access is a manual agreement/workflow. Delayed disclosures are not intraday order signals. [D-pelosi-code] |

## 4. Retain, improve, replace or add

Classifications describe capabilities, not claims of operational data readiness. No module
is removed. “Replace” means a proposed path or adapter inside a future approved change,
with the prior behavior retained for baseline comparisons.

| Priority / area | Existing implementation | Reference contribution | Migration decision |
| --- | --- | --- | --- |
| P0 — data/time | Alpaca fixed `1Hour`, parser and quality/replay support `1h`; checksummed archives, manifest audit, request budget; reviewed 2026 calendar | Five-minute chart parsing and complete-session selection | **Retain** archives/guards/hourly path. **Add** versioned timeframe and session-grid contracts plus a licensed five-minute research provider path. **Replace** hard-coded one-hour assumptions only through explicit contracts after approval. |
| P1 — market scanning | Bounded async preparation, cached features, batched later quote fetch, eligibility/product/session checks, ranking contributions | Daily setup prefilter plus five-minute ORB confirmation; wide US universe | **Retain** scanner and eToro universe/eligibility authority. **Improve** session-aware filtering/observation metrics. **Add** one intraday ORB plugin; do not import thousands of unaffordable/unverified listings. |
| P1 — entry timing | `StrategyEngine`, completed-hour evidence, TTL, momentum breakout/trend/reversion and journal | First completed-bar close above OR high/level, optional volume confirmation and entry windows | **Retain** existing strategies as baseline. **Add** five-minute ORB/level research and explicit close/available/decision timestamps. **Improve** stale-trigger/no-late-chase behavior; no forming-bar trigger. |
| P1 — exit timing | ATR initial/trailing stops, optional R target, trend/mean exit, session deadline, earnings/risk checks; advice only | OR stops and flat-by plan | **Retain** ExitMonitor and no-widening rule. **Add** optional OR stop variants and new-timeframe tests. Keep current close buffer until research justifies a reviewed change; no direct broker bracket import. |
| P1 — risk/sizing | Demo-only account/product evidence; 1% hard trade risk, 3% daily equity halt, 20% proposal/25% instrument/80% total defaults, five-position cap, reservations; default strategy risk 0.5% | Stop-risk size, time limits, trade counts and reward/risk checks | **Retain unchanged** as sole risk authority. **Improve** reporting and test missing intraday constraints before considering them. **Reject replacement** by upstream JSON risk/budget or their defaults. |
| P2 — news | No feed/event module | RSS/8-K events, keyword tags, dedupe and price-move context | **Add** offline-first typed event pipeline, coverage/lag status, revisions and research report. **Replace** any proposed ad hoc LLM scraping with bounded provider adapters. No direct signal weighting at first. |
| P2 — earnings | `CachedEarnings` and `FundamentalAnalysis`; required `EarningsWindow` blackout/coverage checks | Reported XBRL results and exhibit discovery | **Retain** cache/interfaces and blackout fail-closed behavior. **Add** as-of SEC facts/events. Future dates and consensus require independently qualified sources; do not fabricate them from filing absence. |
| P3 — Monte Carlo | Conditional 10,000-trial whole-block bootstrap, costs/spread/FX assumptions and tail metrics; synthetic-only pool | Empirical time-of-day sampling, visual uncertainty summaries and recent ORB record | **Retain** engine/model safeguards. **Add** a separately approved historical intraday pool/research interface after data qualification. **Reject wholesale replacement** by Time Machine or relaxing synthetic-only validation. |
| P3 — backtesting | Chronological Strategy/Risk replay, quotes/FX/costs, cash/buy-and-hold, splits and walk-forward; genuine-data gates remain | Narrow ORB history replay with idealized price outcomes | **Retain and extend**, not restart. **Add** explicit timeframe compatibility, session/partial-bar policies and genuine bid/ask/cost evidence. No fabricated profitability. |
| P4 — alerts/journal | SQLite strategy/exit/execution events; backtest/MC reports; no notification delivery subsystem | Dated one-shot/rearm/time alerts, JSON state and fill logs | **Retain** journals as truth. **Add** idempotent informational notifications and post-trade diagnostic reports, not a parallel mutable portfolio or execution path. |
| Deferred — Congress | No congressional-data importer | House disclosure research | **Retain existing project scope; do not add now.** Low demonstrated intraday timing relevance, delayed/range-based evidence and PDF/legal complexity. |

### Concrete timeframe migration surface

Source inspection shows one-hour completion is embedded in `scanner/engine.py`,
`strategy/engine.py`, `strategy/exits.py` and `backtest/engine.py`, not just the downloader.
`alpaca/contracts.py` both generates and validates `1Hour`; `history/alpaca.py` assigns
one-hour ends; `history/providers.py`, `history/quality.py`, `history/hourly.py` and
`history/replay.py` restrict resolutions/grids. `scanner.indicators.calculate` has an interval
argument, but its callers' evidence semantics still need end-to-end migration. [B-time]

Proposed contract: explicit duration, source bar start/end, exchange timezone, session ID,
regular/extended/boundary classification, completion time, first known availability, retrieval
and revision identity. Five-minute and hourly inputs cannot be silently mixed. Preserve
native timestamps; never relabel bars to fit a grid or synthesize missing observations.
Keep extended-hours research separate from the initial regular-session scope. A session
must use the reviewed holiday/early-close/DST schedule for its date; unsupported years fail.

For the first intraday experiment, use five-minute completed bars and a 15-minute opening
range as a **research proposal**, not an already selected winning strategy. One-minute
and tick-based logic are deferred. Quote age and signal TTL stay within current strict
limits; the reference's delayed bars do not qualify as executable eToro quotes.

## 5. Detailed capability and model findings

### Scanning, momentum and trend

`find_setups` in the reference detects close-based 20-day breakouts, a run/consolidation
bull-flag heuristic, MA20 reclaim and oversold/bounce conditions. `scan_orb` applies
five-minute opening-range candidate/confirmation logic and reports unusable/unconfirmed
symbols. This is real code, but not machine-learned pattern recognition or proof of market
coverage. [D-scanner-code]

Our scanner already calculates SMA/EMA, Wilder RSI/ATR, MACD, relative volume, volatility,
momentum and prior high, and scores breakout/trend/reversion. Different timeframe and
high-versus-close definitions are different strategies, not interchangeable confirmations.
Keep transparent contributions and bounded concurrency; a wider universe or extra votes
may increase correlation, data costs and latency without improving selection. [B-scan]

### News, sentiment and earnings

The news script has topic regexes and SEC 8-K item labels, not calibrated sentiment or a
news-to-price causal model. Showing a move alongside a headline does not explain the move.
It polls sources when invoked; there is no guaranteed real-time stream. Story verification
and paywall handling in SKILL.md require assistant work beyond the script. [D-news-code]

`select` filters old items but does not explicitly reject future items; missing timestamps
can remain. A new adapter must reject/quarantine missing, naive or future availability,
track publication separately from retrieval, retain corrections and expose incomplete feed
coverage. Untrusted article text cannot issue instructions, choose URLs or modify strategy.

`facts.py.periods` deliberately chooses the latest-filed values, including restatements.
That is useful for current research but would leak future information into historical
features without as-of acceptance filtering and a revision archive. Fiscal labels are not
availability timestamps. Derived Q4/EPS, units and absent margins need explicit handling.
It locates release links; narrative guidance extraction is not automatically verified by
that function. No complete upcoming calendar or earnings-consensus dataset was found.
Do not infer an earnings beat/miss without contemporaneous expectations. [D-analyst-code]

Unknown or incomplete earnings coverage must remain unknown: a feed with no new 8-K does
not satisfy `EarningsWindow.complete`. Keep blackout checks through the planned holding
horizon and close buffer. An incomplete provider cannot permit a new entry. [B-strategy]

### Risk, budget and broker compatibility

The reference's defaults include a USD 50 planned loss/trade, USD 150 daily loss and 75%
position cap. Its risk helper can assume all supplied prices fresh when `price_times=None`,
and warns rather than rejects `paper=false`. Its daily-loss calculation accumulates logged
entry max-loss values; it is not our marked-to-market equity halt. Config can allow risky
assets. These are verified differences, not compatible policy defaults. [D-risk-code]

Our risk model has durable, account-bound state, fail-closed validation, atomic reservations,
a sticky daily halt and initial active kill switch. Default strategy sizing is tighter than
the hard risk ceiling. The reference's weight-allocation mode is unnecessary for the active
intraday core. Its bracket/notional payloads and manual fill JSON cannot become our order
contracts or account snapshots. [B-risk], [B-strategy]

`ticket.py` itself renders/logs rather than sending HTTP orders; its SKILL directs the
assistant to external broker tools. A supplied approval string is not authenticated human
consent, and local risk JSON is not our immediately revalidated approval. Keep our exact
Demo approval/expiry/reconciliation model. No Alpaca or IBKR trading connector is proposed;
Alpaca remains market data only. [D-broker-code], [B-execution]

### Time Machine: useful comparison, not a replacement

Verified in `parse_bars`, `full_sessions`, `build_pool`, `simulate`, `history_replay` and
`time_machine`: [D-timemachine-code]

- The request is Yahoo `range=60d&interval=5m` or offline data; current availability and
  completeness were not tested. It requires at least 20 full prior sessions, each with 78
  five-minute bars, excluding gapped/short sessions. This selects a restricted sample.
- It samples each future slot's historical OHLC ratios independently from the same/nearby
  time slots (default window two). It is not whole-session or whole-block resampling, so
  cross-bar dependence is not retained as in our block bootstrap.
- Default 10,000 trials and seed 19 produce conditional empirical scenarios, not every
  possible outcome or calibrated forward probabilities; trial count can be changed.
- Same-bar ambiguity counts stop before target. The sampled opening ratio is not used to
  model a worse gap-stop execution price; stop outcomes are idealized minus one R.
- Its historical replay supports ORB, with entries at trigger closes and ideal stop/target
  outcomes; other setups skip that replay. It lacks portfolio FX, commissions/spread,
  latency/depth/partial fills and train/validation/test selection in these calculations.
- Simulation and displayed ORB history use the same eligible session pool, not independent
  out-of-sample confirmation. Duplicate timestamps overwrite dictionary entries instead of
  creating an immutable revision history.

Retain our gap-aware whole-block logic, explicit cost assumptions, tail reports and unchanged
risk handoff. Current `Pool.validate` intentionally accepts synthetic pools only; an actual
historical path needs a new reviewed provenance contract, not relabelling real bars as
synthetic. Current genuine replay blockers still include native-bar alignment, availability,
corporate actions, quotes/FX/costs and historical product eligibility. Neither upstream
examples nor our synthetic results prove profitability. [B-mc], [B-history], [B-backtest]

### Journaling and learning from mistakes

Our strategy/exit/approval journals and replay reports already capture decisions, reasons,
trades and outcomes. Reference state files cover seen alerts/news, tickets and fills;
no automatic model training or systematic mistake-learning mechanism was found. A repeat
alert suppression mechanism is not learning. [B-journal], [D-alerts-code], [D-broker-code]

Add a retrospective diagnostic report later: distinguish valid losing trades from bad data,
stale entries, cost underestimation, event exposure, sizing errors or execution mismatch.
Preserve rejected/counterexample cases. Any proposed rule adjustment becomes a versioned
research hypothesis with held-out tests and a reviewed PR; no self-modification of risk,
no widening stops, no resetting a halt and no clearing the kill switch.

## 6. Licensing and security assessment

The actual sole-reference LICENSE grants MIT reuse, with copyright 2026 Jake Schincariol
and notice retention for copies/substantial portions. SHA-256:
`857c8d5276809c8196b3cd7cb3300324768bfc562b2b6281b06d6865058e186c`.
No special additional license file appeared in its complete tree. This PR copies no upstream
code or data fixture. Any later source reuse needs the MIT copyright/permission notice and
a pinned provenance record; prefer adapting pure ideas under our interfaces. [D-license]

MIT is a software license, not permission to redistribute articles, exchange data, symbol
lists, mapping information or PDFs. Before implementing a provider, verify current terms,
identification/fair-access requirements, free access, storage and redistribution restrictions
at the provider itself. Upstream “free/no API key” wording is not independent verification.
No subscription or paid service is proposed. Regulatory/tax assertions in README are not
adopted as applicable rules without a separate primary-source review.

| Surface | Security/dependency assessment | Future control / decision |
| --- | --- | --- |
| Yahoo charts/spark/RSS | Unofficial public requests, throttling/fallback; no SLA; possible stale or malformed data | Verify rights/access; bound requests, redirects, bytes/retries; separate historical bars from executable quotes; no production adoption yet |
| SEC | Standard-library requests with owner identity; restatements/filing revisions | Shared aggregate rate budget, correct identity outside committed files, original acceptance time and revision history; no identity/keys requested now |
| Nasdaq Trader | Symbol directories used for broad universe | Validate identifiers and date/version; require separate eToro underlying/unleveraged eligibility |
| House/Senate | ZIP/PDF/parser inputs; optional external Poppler executable; Senate manual agreement | Deferred. Verify use restrictions; sandbox extraction and cap compressed/uncompressed sizes; never bypass access agreements |
| Broker helpers | Local mutable config/approval/result files and external MCP instructions | Exclude from bot authority; no broker dependencies/configuration or token/key access |
| Local JSON state | Shared filenames can race/overwrite; some writers use atomic replacement, not transactional safety reservations | Keep our SQLite state/journals; proposed research state must be separate and versioned |
| Floats/DST helpers | Many USD float calculations and repeated hand-coded New York DST logic | Keep finite bounded Decimal money and aware instants; use one reviewed calendar authority; reject unknown dates/years |
| External payloads | Several fetchers read/decompress entire bodies; urllib uses default redirect behavior | Explicit origins/routes, bounded bytes/decompression/time, sanitized errors; no instructions or tool authority from payload text |

Pure functions such as closed-bar eligibility, rule evaluation, topic classification,
uncertainty summaries and one-shot notification state are conceptual reuse candidates.
Network clients, mutable broker state, risk authority, default sizing and actual fixtures
are not direct imports. Poppler is optional outside Python; executing broker workflows also
needs connectors/MCP and credential setup that are outside this migration.

## 7. Migration phases and approval gates

No phase below is started by approval to review this document. Each implementation scope
requires explicit approval; each produces a separate PR. No PR is merged automatically.

| Phase | Proposed deliverable | Dependencies / measurable acceptance |
| --- | --- | --- |
| 0 — review this plan | Confirm intraday research direction, retain existing modules and safety authority | Documentation only. Select scope before implementation; no credentials or trading enablement. |
| 1 — recommended next phase | Offline five-minute timeframe/session/evidence contracts and qualification audit, alongside current hourly baseline | Verify provider capability/terms before adding a network path. Mock-only tests for incomplete/late/revised/duplicate bars, DST/holidays/early closes, missing minutes, unsupported years and cross-timeframe rejection. Preserve all hourly behavior and gates. |
| 2 — intraday scan/entry/exit research | One long-only 15-minute ORB strategy over completed five-minute data; immutable entry/stop/target/deadline explanation | Use reviewed eligible watchlist and existing sizing/risk. No forming-bar entries, chasing expired triggers, widened stops or fabricated fills. Existing hourly strategies remain available and frozen for comparison. |
| 3 — news and earnings evidence | Offline SEC/RSS parsers then separately approved free-provider ingestion; as-of facts, event revisions, coverage/lag reports | No sentiment weighting initially. No “no events” completeness inference. Legitimate owner identity, access terms and request limits before network; no authenticated data request in this audit. |
| 4 — genuine replay and historical Monte Carlo research | Qualified historical event/quote/FX/cost inputs, fine-timeframe replay and separate historical pool contract | Resolve original availability, actions, cost/eligibility/session coverage and native alignment. Compare chronologically; preserve risk handoff. Never relax existing synthetic-only input checks. |
| 5 — diagnostics and notifications | Read-only mistake attribution and cost/event reports; idempotent stop/target/deadline notifications | Reuse journals; no parallel portfolio truth. Alerts are advice, not execution. Rule-change proposals require held-out evaluation and a new reviewed PR. |
| Optional later — simulation-only leverage | Explicit hypothetical leveraged scenario engine/config isolated from all execution payloads | Separately approved research methodology, financing/margin/liquidation/gap modelling, clear labels and tests that no scenario setting reaches order creation. No execution leverage or margin switch. |

Phases can be narrowed further; adding news explanations does not have to wait for a winning
strategy, but changing a strategy's event weights must wait for point-in-time evaluation.
The historical readiness work in `ALPACA_FIRST_READ.md` remains relevant: faster bars do
not remove missing quotes/FX/costs or broker evidence requirements.

### Initial economics and scope

Do not copy the reference's dollar risk budgets into a EUR 500–1,000 account. To illustrate
existing percentages only (not an FX conversion or promised worst-case loss):

| Existing default | EUR 500 equivalent scale | EUR 1,000 equivalent scale |
| --- | --- | --- |
| Strategy planned risk 0.5% | EUR 2.50 | EUR 5.00 |
| RiskEngine hard planned risk 1%, including cost buffer | EUR 5.00 | EUR 10.00 |
| Trusted opening-equity daily loss halt 3% | EUR 15.00 | EUR 30.00 |
| Default proposal allocation cap 20% | EUR 100 | EUR 200 |

Actual model inputs are USD-normalized and need evidenced FX and conversion costs. Gaps
can exceed stop-based planned loss. Preserve the 25% cumulative-instrument, 80% total-exposure
and five-concurrent-position defaults as well. Fees/spreads/minimums/fractional steps may
make frequent small trades infeasible. Rejection, idle cash and no-trade days are valid;
active intraday focus does not imply a trade quota or relaxed selectivity.

Start with a small reviewed eToro-eligible watchlist, regular sessions and one experimental
setup. Preserve existing daily/historical/fundamental/swing-capable components as supporting
research and baselines; do not delete them or make portfolio allocation the new core.

### Evidence required before claiming an improvement

- **Decision quality:** same point-in-time universe/data/costs, unchanged risk and frozen
  baseline; evaluate one added feature at a time using chronological train/validation/test
  or disjoint walk-forward tests. Include cash and buy-and-hold, turnover, rejected signals,
  drawdown and cost sensitivity, not only win rate. No invented uplift or return target.
- **Latency:** measure publication-to-ingestion and bar-completion-to-signal separately from
  quote age and local compute time; record p50/p95, request counts, throttling and failures.
  Cached research can reduce redundant work, but eleven LLM calls or a broad serial chart
  scan may increase delay. No measured latency advantage is claimed here.
- **News/earnings:** reviewed extraction/tag/revision labels, date/unit correctness, source
  coverage and missing-consensus reporting. A topic tag is not sentiment; an LLM narrative
  must cite evidence and cannot authorize risk/execution.
- **Monte Carlo:** seed/input/model identity, sample exclusions, dependence/cost assumptions,
  sensitivity and chronological separation. More paths do not create more independent
  historical evidence or unseen tail events.
- **Safety regression:** missing/stale/future prices or account/product evidence, active kill
  switch, daily halt, duplicate/concurrent proposals and expired/changed approval still
  block. Simulation leverage cannot change any execution invariant.

## 8. Required invariants and approval boundary

Retain eToro Demo-only account/destination verification, long underlying unleveraged eligible
products, exact human order approval, kill switch, daily loss halt, immutable reservations,
quote/product/session freshness and fail-closed data rules. Unknown account modes and real
money remain rejected. Keep ambiguous-submission reconciliation; never blindly retry an
order. Existing `settlement="real"` means underlying asset settlement, not a real-money
account; it does not override mandatory Demo identity.

No API key, service authentication, order, broker call, autonomous execution, new scheduler,
new dependency or production code change occurs in this audit. No existing module is
deleted. Approval of this migration document alone is not approval to implement, merge,
clear safety state or place any Demo order. The next concrete proposal is Phase 1 only,
with a separate code review and test report.


[D-scanner-code]: https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/trader-scanner/scan.py
[D-news-code]: https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/trader-news/news.py
[D-entry-code]: https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/trader-entry/entry.py
[D-exit-code]: https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/trader-exit/exit.py
[D-timemachine-code]: https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/trader-timemachine/timemachine.py
[D-risk-code]: https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/trader-risk/check.py
[D-budget-code]: https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/trader-budget/size.py
[D-broker-code]: https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/trader-broker/ticket.py
[D-alerts-code]: https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/trader-alerts/alerts.py
[D-analyst-code]: https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/trader-analyst/facts.py
[D-pelosi-code]: https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/trader-pelosi/ptr.py
[B-time]: https://github.com/orkunkilic123-cloud/etoro-ai-trading-bot/blob/a2f74dbbac5410be5edd97af549442f1e0bcdb29/src/etoro_demo_bot/alpaca/contracts.py
[B-scan]: https://github.com/orkunkilic123-cloud/etoro-ai-trading-bot/blob/a2f74dbbac5410be5edd97af549442f1e0bcdb29/src/etoro_demo_bot/scanner/engine.py
[B-strategy]: https://github.com/orkunkilic123-cloud/etoro-ai-trading-bot/blob/a2f74dbbac5410be5edd97af549442f1e0bcdb29/src/etoro_demo_bot/strategy/engine.py
[B-risk]: https://github.com/orkunkilic123-cloud/etoro-ai-trading-bot/blob/a2f74dbbac5410be5edd97af549442f1e0bcdb29/src/etoro_demo_bot/risk/engine.py
[B-execution]: https://github.com/orkunkilic123-cloud/etoro-ai-trading-bot/blob/a2f74dbbac5410be5edd97af549442f1e0bcdb29/AGENTS.md
[B-history]: https://github.com/orkunkilic123-cloud/etoro-ai-trading-bot/blob/a2f74dbbac5410be5edd97af549442f1e0bcdb29/src/etoro_demo_bot/history/archive.py
[B-backtest]: https://github.com/orkunkilic123-cloud/etoro-ai-trading-bot/blob/a2f74dbbac5410be5edd97af549442f1e0bcdb29/src/etoro_demo_bot/backtest/engine.py
[B-mc]: https://github.com/orkunkilic123-cloud/etoro-ai-trading-bot/blob/a2f74dbbac5410be5edd97af549442f1e0bcdb29/src/etoro_demo_bot/monte_carlo/models.py
[B-journal]: https://github.com/orkunkilic123-cloud/etoro-ai-trading-bot/blob/a2f74dbbac5410be5edd97af549442f1e0bcdb29/src/etoro_demo_bot/strategy/journal.py
[D-license]: https://github.com/Jakeschincariol/day-trader-skill/blob/3d0f4ef6986f4984b7c6bd46f7ff4f87744c3abd/LICENSE

## Phase 13 implementation status

The [15-minute ORB research contract](ORB_RESEARCH.md) implements the approved first
strategy as separate proposal-only interfaces over completed five-minute bars.
Hourly engines and execution safeguards remain in place. Genuine-data replay,
fill/cost modeling and Monte Carlo comparisons remain subsequent evidence-gated
work; this implementation is not approval to trade.

## Phase 14 implementation status

The [independent intraday replay adapter](INTRADAY_REPLAY.md) adds conservative delayed
fills, gap/partial/deadline handling, explicit costs/FX, unchanged risk handoff, fixed-plan
chronological evaluation and 10,000-draw prior-session outcome comparisons. Synthetic
fixtures validate mechanics only. Genuine replay remains gated on original availability,
coverage, usage rights, actions and execution evidence/declared research assumptions.
Next: audit an owner-provided capture bundle and independent comparator compatibility;
no trading activation, leverage or automatic merge is included.
