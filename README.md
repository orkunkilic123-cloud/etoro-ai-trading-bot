# eToro Demo trading foundations

Python 3.12+ read-only API client, risk engine and opt-in Demo execution coordinator. The read-only client allows only Demo portfolio GET and market rates GET. The original client blocks order routes and Real portfolio routes. A separate, disabled-by-default Demo execution coordinator requires exact manual approval and risk checks; no autonomous trading is implemented.

- [Independent backtesting: replay, evidence, reports and limitations](docs/BACKTESTING.md)
- [Strategy engine: proposals, risk review, exit advice and learning boundary](docs/STRATEGY_ENGINE.md)
- [Market scanner: data contracts, indicators, scores and limitations](docs/MARKET_SCANNER.md)
- [Demo execution: authorization, journal and recovery](docs/DEMO_EXECUTION.md)
- [Risk management: policy, persistence and offline example](docs/RISK_MANAGEMENT.md)
- [Windows setup and read-only connection test](docs/WINDOWS_SETUP.md)
- [Architecture and roadmap](docs/IMPLEMENTATION_PLAN.md)
- [Verified API findings](docs/API_FINDINGS.md)
- [Permanent rules](AGENTS.md)

Linux/macOS development:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m pytest
.venv/bin/python -m ruff check .
.venv/bin/python -m ruff format --check .
.venv/bin/python -m mypy
```

Tests are offline. The explicit `etoro-demo check-demo` command requires locally configured Demo credentials; see the guide. An opaque key's scope cannot be verified locally: Demo declaration plus broker-side enforcement and immutable read-only routing are the safety boundaries. Never enable diagnostic tooling that prints secrets or frame locals.

The offline risk engine limits estimated risk to 1% per trade, latches a daily halt at 3% equity loss, forbids leverage and reserves capacity in SQLite. It rejects invalid/stale inputs and duplicates, and persists an emergency kill switch across restarts. A risk PASS never authorizes execution. See the risk guide for UTC baseline requirements and conservative reservation lifecycle limitations.

Phase 4 adds an analysis-only market scanner with batched official data routes, completed-bar indicators, explainable opportunity scores, EUR budget/cost screening and persistent caches/quota pacing. Network access defaults off; verified product, calendar, FX and cost evidence are required. Scores never approve orders. Run `python -m pytest tests/test_scanner.py` for the offline scanner suite.

Phase 5 adds deterministic momentum breakout, trend-following and mean-reversion proposals for intraday/short-swing analysis. Point-in-time evidence, earnings coverage, conservative sizing and persistent decision journaling are required. Risk review is explicit; strategy code cannot invoke execution. No profitability claim or autonomous trading is enabled.

Phase 6 adds independent chronological backtesting with the existing strategy/risk engines, isolated simulated accounting, conservative later-quote fills, benchmarks and reproducible reports. Included fixtures are explicitly synthetic and provide no profitability evidence. See the backtesting guide before interpreting any metric.

## Historical research data (Phase 7)

Daily CSV ingestion, source provenance, immutable SQLite snapshots, NYSE 2026 calendars,
quality diagnostics and point-in-time split adjustment are available offline. See
[historical data and licensing](docs/HISTORICAL_DATA.md) and
[Windows instructions](docs/WINDOWS_SETUP.md). A public IBM sample was audited locally;
attributed ECB reference FX is recorded in tests. Real strategy comparisons remain blocked
by missing point-in-time quotes, actions and eligibility evidence. Readiness reports contain
null returns, not profitability claims. Execution remains disabled by default.

## Hourly history qualification (Phase 8)

[Intraday provider research and blockers](docs/INTRADAY_DATA.md) found no verified source meeting
free hourly access, acceptable terms and no private credentials together. The new offline hourly
CSV/cache audit checks six-month coverage, session alignment, point-in-time warm-up and declared
train/validation/test partitions before the backtester gate. No hourly stock/ETF samples or real
performance results are claimed. See [Windows setup](docs/WINDOWS_SETUP.md) for the audit command.

## Optional Alpaca market data

A [read-only Alpaca IEX integration](docs/ALPACA_MARKET_DATA.md) supports paginated hourly bars,
exact-byte SQLite provenance, safe retries and shared pacing. Networking defaults off; only the
stock-bars GET endpoint is allowed. No actual credentials or authenticated requests were used
in development. Free-tier entitlement, coverage and real-data backtest readiness remain
unverified. See [Windows setup](docs/WINDOWS_SETUP.md) for local configuration and explicit opt-in.

Codex Cloud Alpaca downloads support destination-scoped Network Secrets through the approved
proxy with verified TLS. See [cloud configuration](docs/CODEX_CLOUD_ALPACA.md); network access
remains opt-in and account access has not been verified.

Phase 11 adds an [offline Monte Carlo Simulation Agent](docs/MONTE_CARLO.md): 10,000 seeded
conditional outcomes per risk-reviewed strategy candidate, with gap/cost modeling and tail-risk
reports for EUR 500/1,000. Only synthetic research pools are currently admitted; no profitability
claim or execution authorization is produced. [Windows demo commands](docs/WINDOWS_SETUP.md).

For the owner-operated first read, direct manifest audit and remaining historical replay blockers,
see [Alpaca first read and readiness](docs/ALPACA_FIRST_READ.md).

Phase 1 intraday research now has explicit versioned `1Hour`/`5Min` contracts and an
[offline five-minute qualification path](docs/FIVE_MINUTE_CONTRACTS.md). Five-minute inputs
remain isolated from strategy/execution; hourly calculations and safety gates are retained.

### 15-minute ORB research (Phase 13)

The separate five-minute research interface now supports long-only opening-range
breakout proposals and explicit Risk Manager review, with no execution authority.
See [ORB rules, evidence requirements and offline validation](docs/ORB_RESEARCH.md).
Hourly strategy behavior remains unchanged; synthetic tests do not establish returns.

### Intraday ORB replay and Monte Carlo (Phase 14)

[Evidence-gated intraday replay](docs/INTRADAY_REPLAY.md) adds delayed conservative
fills, partial/gap exits, costs/FX, unchanged risk checks, chronological evaluation
and a separate 10,000-draw session-outcome bootstrap. Run the offline synthetic demo:

```bash
python -m etoro_demo_bot.backtest.intraday --output .historical-data/orb-synthetic-500 --eur 500 --seed 19
```

Genuine-data metrics remain blocked without original availability, coverage and
usage-rights evidence. Synthetic and conditional research do not establish eToro
profitability or authorize trading. The hourly baseline remains unchanged.

### Phase 15: private Alpaca five-minute evidence intake (partial)

An [offline owner-supplied exact-byte importer](docs/ALPACA_5MIN_IMPORT.md) now validates
native 5Min IEX pages and pagination against the existing immutable SQLite archive.
This is **not** an authenticated download or genuine ORB replay enablement. Historical
availability, usage rights and all real-data replay gates remain blocked pending evidence.

### Phase 16: offline multi-symbol five-minute evidence audit

[Evidence qualification and owner workflow](docs/PHASE16_EVIDENCE.md) generates
private reproducible JSON, CSV and Markdown reports for complete Alpaca IEX 5Min
manifests. Genuine ORB/Monte Carlo and portfolio returns remain blocked without
independently verified original availability, quotes, FX, costs, actions and eligibility.

### Phase 17: Demo read-only preparation (partial)

[Offline readiness gates and owner-operated first-read checklist](docs/PHASE17_DEMO_READINESS.md) provide explicit evidence blockers and a separate future virtual-trade checklist. No authenticated tests or orders were run during implementation. The readiness assessment never grants execution authority; a documented v2/v3 order-endpoint discrepancy remains unresolved. The existing execution coordinator stays disabled by default.

### Phase 21 — untrusted broker observation bridge

[Phase 21 integration status and v2/v3 blockers](docs/PHASE21_INTEGRATION.md). The existing broker-evidence module can validate independently reviewed observations and construct a **risk-incomplete** AccountSnapshot. It does not fetch broker data, attest Demo identity, authorize a trade or enable execution. A complete authenticated broker normalization and current v3 order contract remain blocked; trading stays disabled.

### Phase 22 — offline Demo P&L and reservation normalization

[Phase 22 integration contract and blockers](docs/PHASE22_INTEGRATION.md). The documented Demo P&L cash parser now feeds the existing Phase 21 risk observation bridge without authenticating account identity or treating partial account data as complete. Submission remains disabled; v2/v3 execution compatibility and trusted portfolio/position normalization remain unverified.

### Offline broker diagnostics and lifecycle hardening (dependent on PR #25)

[Saved-response diagnostics](docs/BROKER_DIAGNOSTICS.md) cross-check documented Demo P&L,
aggregate equity/positions and existing local reservations, then exercise the actual Risk Manager.
They produce sanitized summaries and keep incomplete snapshots blocked. The
[execution review](docs/EXECUTION_CONTRACT_REVIEW.md) documents stricter fill consistency and
restart recovery. This is offline software validation; broker compatibility and first-order
readiness remain unverified. Follow the [active migration checkpoints](docs/DAY_TRADER_MIGRATION_PLAN.md).

### Local shadow application

The [shadow application](docs/SHADOW_APP.md) runs the existing hourly or five-minute ORB
simulation with EUR500/EUR1000 budgets, durable run scheduling, a static local dashboard and
daily/weekly reports. It uses synthetic fixtures and has no broker connection or order controls.
Windows startup and Task Scheduler instructions are included; no task runs while the PC is off.

### Saved SEC filing events

The [offline news adapter](docs/NEWS_EVENTS.md) imports owner-saved SEC Atom bytes into a
checksummed local archive with revision history and as-of queries. It separates publication,
update and observation times from simple keyword tags. It never treats missing filings as
complete earnings coverage and never downloads stories or changes strategy decisions.
