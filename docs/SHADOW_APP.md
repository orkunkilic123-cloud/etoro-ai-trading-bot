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
shows summary cards, run freshness, missing/failed/running states, expandable daily/weekly
tables, full-run synthetic metrics and proposed experiments. Run rows link to JSON, Markdown
and CSV exports. It is not a real-time
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

The runner publishes its `running` state before starting the replay. An interrupted process is
not assumed dead or safe to repeat: the dashboard says **active or interrupted**. The run database
must retain its expected schema and exact unique slot constraint; missing/corrupt schema is an
error, never an invitation to initialize or silently repair state.

These are daily **software run slots**, not a trading-day quota or an exchange calendar. A local
timezone schedule may map to a different UTC date around midnight/DST; pick a daytime trigger
if that distinction matters. No task runs while the PC is off. No remote scheduler or service
is configured by these commands. Task registration itself is an owner action.

## Report semantics and improvement proposals

Each run retains the existing engine's private `state/` and full `report/` files, including source
provenance, model limitations, events, decisions, equity, trades and benchmarks. `summary.json`
adds daily and ISO-week partitions based on **replay UTC timestamps**, not scheduler dates.
The same normalized records generate human-readable `daily.md`, `weekly.md` and `periods.csv`.
Markdown includes currency, observed timestamp bounds, coverage, stage/reason counts and prioritized
experiments. CSV retains exact decimal text, uses UTF-8/LF and neutralizes spreadsheet formulas
in text cells. No repeated replay is needed to read these reports.
Periods show net marked-equity change, drawdown from the period opening/observed peak,
maximum observed exposure in the explicitly labelled valuation currency (USD hourly, EUR ORB),
attributed USD commissions/funding costs, rejected/missed stage observations
and risk halts. Proposal statuses come from hourly strategy events or ORB decision rows, never
both copies of the same journal entry. Later risk/fill rejections and expired/end-of-data entries
are counted separately; unknown statuses/reasons remain explicit. These are stage observations,
not counts of unique economic opportunities. Open inventory remains valued using the engine's
convention.

Realized exit P&L is separately labelled USD and follows the source journal: it includes allocated
entry and exit fees, excludes initial FX funding and is not total account P&L. An exit row may be
a partial fill; exit row counts are not relabelled as closed positions. Net marked-equity change
remains the period-level portfolio measure.

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

## Output integrity and monitoring

Report exports and the dashboard use a closed temporary file followed by replacement in the
same directory. Readers see a complete previous or new file; reports are never served from
temporary files. `shadow-checksums.json` is written last and hashes the exact UTF-8 bytes of all
four exports. Completion is recorded only after the bundle is written. A write failure leaves
the run failed/claimed, never automatically replayed. A process/power interruption can leave a
temporary file or incomplete bundle; checksums and run status must be inspected. Replacement
is not a guarantee against storage-device failure or power loss.

The dashboard bounds file reads, rejects symlinked run/report files, validates report labels and
verifies new-bundle checksums. Missing/corrupt exports show **REPORT UNAVAILABLE**, hide report
links, and leave run claims untouched. These local checks detect accidental file corruption;
they do not authenticate market/broker evidence or protect against an owner who edits files and
their checksums together. Older summaries remain visible inline with **LEGACY — export integrity
unverified** and no unverified export links. Original files remain available locally; they are never
overwritten or silently upgraded.

An optional read-only news summary can display saved filing titles, forms, publication/update/
observation times, revision hashes, source URLs as plain text, and keyword tags. It explicitly
labels source authenticity **UNVERIFIED** and earnings coverage **UNKNOWN**. Current archive facts
are informational only, never passed into historical strategy decisions, sentiment scoring or
execution authorization. Without a supplied summary, news is **UNAVAILABLE**; no remote feed is
contacted by dashboard generation.

## Validation and remaining limits

Focused checks:

```powershell
.\.venv\Scripts\python.exe -m pytest -q tests/test_shadow_app.py
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m mypy
```

Tests prohibit socket connections and cover both engines/budgets, atomic duplicate claims,
restart persistence, failed runs, missed slots, escaped dashboard content and daily/weekly
arithmetic. Regression coverage also checks all export hashes, CSV/Markdown parity, corrupt
report handling, failed atomic replacement, interrupted/failed export states, schema uniqueness,
legacy summaries and escaped news display. Windows remains untested unless separately recorded
in the root milestone evidence.

A connected genuine-data shadow path remains dependent on truthful point-in-time market data,
eligibility/FX/cost/action/earnings evidence and the existing provider/replay gates. Live news
adapters may later supply displayed facts; absent SEC filings cannot satisfy complete earnings
coverage. Broker reconciliation and exact-order approval remain separate blocked integrations.
