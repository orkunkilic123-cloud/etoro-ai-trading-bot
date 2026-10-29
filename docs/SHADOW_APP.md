# Local shadow research application

This milestone connects the existing event-driven backtests into an owner-operated local
application. It adds no broker endpoint, credential input, network client or order authority.
The dashboard always displays **SHADOW / SYNTHETIC**, disabled broker execution, unverified
broker unresolved-order state, and unverified live news/earnings coverage.

## Working paths

- `hourly`: existing synthetic dataset → scanner indicators/ranking → existing StrategyEngine
  → actual RiskEngine and local capacity reservation → later-quote simulated fills and exits
  → simulation reservation accounting → strategy/events/equity/trade journals and reports.
- `orb`: existing full-session five-minute synthetic dataset → ORB proposal facade → actual
  RiskEngine → intraday simulated fills, exit/reconciliation logic → the same result/report shape.

Both run independently with EUR 500 or EUR 1,000 through the existing Simulation settings.
Hourly and ORB strategies, risk limits and execution controls are not changed. The existing
readiness gates still apply inside each engine. No signals, fills, holdings or returns from
these fixtures establish actual market performance or owner-verified broker compatibility.
This is a runnable offline shadow-research application, not a live scanner or persistent
broker portfolio. All four pipeline/budget combinations have end-to-end tests.

The existing pinned Day Trader migration/evidence review remains authoritative. This milestone
reuses this project's simulation/journal implementations. It copies no upstream code and does
not add another Trader Skill pack or notification/execution connector.

## Windows setup and manual operation

Use the existing Python 3.12+ virtual environment and pinned dependencies. No credential
variables are needed. In PowerShell from the repository directory:

```powershell
.\.venv\Scripts\python.exe -m etoro_demo_bot.shadow init --root .backtest-output\shadow
.\.venv\Scripts\python.exe -m etoro_demo_bot.shadow run --root .backtest-output\shadow --pipeline hourly --eur 500
.\.venv\Scripts\python.exe -m etoro_demo_bot.shadow run --root .backtest-output\shadow --pipeline orb --eur 1000
Start-Process .backtest-output\shadow\dashboard.html
```

`init` requires a new directory. Thereafter reuse that exact root; never initialize over existing
state, use an existing production safety database, or delete state to bypass a duplicate claim.
The other budget combinations can run independently with `--eur 1000` / `--eur 500`.
Each unique pipeline/budget/UTC-day combination may run only once in a root. Repeating the
same command that day is blocked, including after restart or failure. An independent research
experiment may use a separately named new synthetic root; it does not replace operational state.

To refresh the static view without replaying anything:

```powershell
.\.venv\Scripts\python.exe -m etoro_demo_bot.shadow dashboard --root .backtest-output\shadow
```

The dashboard has escaped text and no scripts, remote resources or controls for orders. It
shows run freshness, missing/failed/running states and synthetic metrics. It is not a real-time
view: refresh explicitly, and inspect the UTC run date. Never interpret today's run date as
fresh market observations; fixture periods remain unchanged and are reported separately.

## Optional local scheduling

Use Windows Task Scheduler's **Create Task** UI; do not store credentials or secret literals.
For a daily synthetic run while the owner is logged in:

1. Set **Program/script** to the absolute path of `.venv\Scripts\python.exe`.
2. Set **Arguments** to `-m etoro_demo_bot.shadow run --root "C:\absolute\project\.backtest-output\shadow" --pipeline orb --eur 500`.
3. Set **Start in** to the absolute repository directory and choose a daily trigger in your
   Windows local timezone. Use **Do not start a new instance** for overlapping tasks.
4. If **Run task as soon as possible after a scheduled start is missed** is enabled, the command
   claims the current UTC day only. It never backfills skipped days or makes catch-up trades.

Application-level SQLite `BEGIN IMMEDIATE` and a unique pipeline/budget/UTC-date key also stop
concurrent processes from duplicating a run. A completed, failed or still-running slot remains
claimed after restart. A process killed before finishing leaves `running`; inspect its private
reports/state rather than retrying automatically. Ordinary exceptions mark the slot `failed`.
Prior missing UTC days since the previous slot are recorded `missed` at the next run, bounded
at 366 days; longer gaps require operator review. The first-ever run has no assumed past schedule.

These are daily **software run slots**, not a trading-day quota or an exchange calendar. A local
timezone schedule may map to a different UTC date around midnight/DST; pick a daytime trigger
if that distinction matters. No task runs while the PC is off. No remote scheduler or service
is configured by these commands. Task registration itself is an owner action.

## Report semantics and improvement proposals

Each run retains the existing engine's private `state/` and full `report/` files, including source
provenance, model limitations, events, decisions, equity, trades and benchmarks. `summary.json`
adds daily and ISO-week partitions based on **replay UTC timestamps**, not scheduler dates.
Periods show net marked-equity change, drawdown from the period opening/observed peak,
maximum observed exposure in the explicitly labelled valuation currency (USD hourly, EUR ORB),
attributed USD commissions/funding costs, rejected/missed stage observations
and risk halts. Proposal statuses come from hourly strategy events or ORB decision rows, never
both copies of the same journal entry. Later risk/fill rejections and expired/end-of-data entries
are counted separately; unknown statuses/reasons remain explicit. These are stage observations,
not counts of unique economic opportunities. Open inventory remains valued using the engine's
convention.

Full-run trading costs come directly from the existing metric. Some source event ledgers omit
per-exit spread/slippage attribution: multi-period total cost is explicitly null; no invented
allocation is used. Fees/funding are separately summed from entry/funding events and exit trade rows exactly once;
missing charge fields produce null rather than zero. Report
periods expose UTC period boundaries and observed equity-mark start/end timestamps. Coverage is
explicitly partial when marks do not span those boundaries, otherwise unverified; even matching
boundaries cannot prove continuous coverage. Different pipeline runs
are independent portfolios, never summed or presented as a continuous portfolio track record.

Prioritized improvement proposals reference synthetic-only input limitations, observed rejection/
miss events and nonzero modeled costs. Each supplies a hypothesis and a held-out validation
proposal. They never edit strategies, risk settings, deployed code or approvals. This is a small
deterministic report aid, not an autonomous optimizer or a claimed predictive Learning Agent.

## Validation and remaining limits

Focused checks:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_shadow_app.py
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy
```

Tests prohibit socket connections and cover both engines/budgets, atomic duplicate claims,
restart persistence, failed runs, missed slots, escaped dashboard content and daily/weekly
arithmetic. Windows remains untested unless separately recorded in the root milestone evidence.

A connected genuine-data shadow path remains dependent on truthful point-in-time market data,
eligibility/FX/cost/action/earnings evidence and the existing provider/replay gates. Live news
adapters may later supply displayed facts; absent SEC filings cannot satisfy complete earnings
coverage. Broker reconciliation and exact-order approval remain separate blocked integrations.
