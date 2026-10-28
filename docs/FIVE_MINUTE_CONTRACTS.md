# Phase 1: versioned five-minute research contracts

Implemented against main `25cd5a37446a0946e9b11ef1dec4afd0af9fc8ec` (merged PR #14).
This phase adds offline data qualification, not a strategy, data subscription or execution mode.
No API credentials or authenticated market-data requests were used. No upstream code was copied.
The sole external Trader Skill reference remains the MIT-licensed Day Trader Skill inspected
in DAY_TRADER_EVIDENCE.md; its timing ideas are not imported as a trading implementation.

## Contracts and compatibility

`timeframes.py` defines immutable `BarContract`, version `bar-contract-v1`, with exact
`Timeframe.HOUR` (`1Hour`, `1h`, 3600 seconds) and `Timeframe.FIVE_MINUTES`
(`5Min`, `5m`, 300 seconds). Unknown versions, raw string enum substitutes, exchanges,
timezones and alignment policies are rejected. The supported exchange is XNYS, timezone
America/New_York. Five-minute contracts must be research-only.

`HOURLY_BASELINE` retains provider-native alignment and all existing hourly completion,
indicators, sizing and replay rules. It does not newly assert that native hourly bars fit
a regular-session grid. Request parameters and existing hourly archive/manifest schema are
unchanged. Candle/Opportunity, strategy Context and replay Dataset now carry explicit
contract metadata, so their serialized representations include this new metadata; this
changes input digests, not the hourly strategy rules or calculations.

`FIVE_MINUTE_RESEARCH` specifies `regular-session-full-bars-v1`. Candle consumers reject
five-minute or changed session contracts: scanner initialization/history, indicators,
strategy proposal context/opportunity/history, exits and Dataset validation. This is an
explicit rejection boundary, not activation of five-minute Strategy/Backtest support.
The hourly research readiness and verified replay gates remain unchanged. No five-minute
bar is converted to an hourly candle, or vice versa.

## Alpaca archive extension

`BarsQuery`, version `alpaca-bars-v1`, supports the two exact timeframe enum values.
The default remains 1Hour. The existing bars GET route, IEX feed, USD, sort, limits and
provenance query checks remain pinned. Five-minute page provenance uses provider
`alpaca-iex-5min-v1`; a 5Min query cannot masquerade as `alpaca-iex-hourly`.

`decode_page` assigns five-minute interval ends, normalizes instants to UTC, retains raw
archive bytes/offsets, and rejects incomplete intervals, off-grid starts, duplicates,
ordering/overlap and invalid OHLCV. Native pre/postmarket observations may be archived,
but they fail the regular-session qualification below; they are never silently trimmed.
Hourly parser behavior is preserved, including its native timestamp treatment.

`archive_research_pages(archive, page_ids, symbol)` is a network-free helper for **already
archived** pages. It validates the whole query/cursor/page chain before saving the new
`alpaca-iex-download-5min-v1` manifest. It rejects incomplete pagination, repeated IDs,
unrequested symbols and mixed hourly/five-minute queries. Existing hourly v1 manifests
still load. Every use through `load_download` rechecks archive hashes and page provenance.
A synthetic test manifest remains classified synthetic; a label does not prove market data.

Five-minute authenticated download is intentionally disabled in both the CLI (before key
loading) and `MarketDataClient.request` (before transport). The one-hour opt-in workflow
is unchanged. A five-minute query can be previewed offline:

```bash
python -m etoro_demo_bot.alpaca --dry-run --timeframe 5Min --symbols IBM --start 2026-03-09T00:00:00Z --end 2026-03-10T00:00:00Z
```

Adding `--enable-network` to a five-minute request fails. It is not a way to enable trading
or to enable an authenticated data test. No key setup is required for any new workflow.

## Structural research qualification

`history.intraday.qualify_download` reads an immutable complete manifest and returns a
`ResearchSeries` only when all required regular-session bars are present. It uses the
existing bounded NYSE2026 calendar, now independently reviewed against the official NYSE
schedule on 2026-10-28. Unsupported years/exchanges fail; no historical schedule is guessed.
Its verification timestamp is a caller review declaration, not original publication proof.

- Regular open is 09:30 New York; close 16:00, or 13:00 on reviewed early-close dates.
  ZoneInfo plus pinned tzdata handles the March/November DST transitions.
- Each requested date range is inclusive, at most 366 days, within supported calendar dates.
  The requested trading sessions must be fully closed by `audit_at`. A holiday-only window
  or an unfinished session fails. This is full-session historical qualification, not a
  live partial-session feed.
- Every expected full interval must occur exactly once: 78 five-minute bars on a normal
  session and 42 on a 13:00 close. Missing, extra, pre/postmarket, partial, off-grid,
  overlapping, duplicated or misordered bars fail. No imputation or resampling occurs.
- Raw USD prices are required. Split-adjusted pages remain parseable but cannot qualify.
  Source snapshots must not be from the future and must have been retrieved within the
  configured audit freshness bound (24 hours by default, maximum seven days).
- Snapshot freshness is separate from historical price freshness: old historical dates can
  be structurally inspected after a recent retrieval. They do not become fresh quotes.
- `SessionWindow`, version `XNYS-regular-2026-v1`, records exchange, timezone, date,
  UTC open/close and calendar source/review time. Its boundaries must match that calendar.
- Each `ResearchBar` records the original Bar, interval `completed_at`, `first_known_at`,
  reviewed session and source-manifest snapshot ID. Completion is economic interval end,
  **not** a claim of vendor finality/publication. First known remains backed by retrieval
  as in the existing parser; it is never backdated to the close.
- `visible_at(decision_at, max_age_seconds=300)` returns only completed observations whose
  first-known availability is no later than the decision. No visible or stale latest bar
  fails. A historical download obtained later will not be visible to an earlier decision.
  The immutable series/session contract is the future research interface; no ORB rules,
  signal, position sizing or execution adapter is supplied.

The report states structural qualification only and retains the existing replay blockers,
including original availability, corporate-action completeness and the hourly replay gate.
It grants no licensing, product eligibility, point-in-time readiness or profitability status.
There are no performance metrics. Research `execution_authorized` is always false.

## Offline qualification command

An owner or a later explicitly approved importer must first provide legally obtained native
five-minute pages with independently reviewed `Source` metadata. Use the existing `Archive.put`
for the raw pages, then `archive_research_pages` to assemble the complete download. Those
operations require no credentials, but a valid-looking Source does not certify licensing or
truth. Do not relabel hourly pages, backdate availability or manufacture missing candles.
This PR does not download or bundle genuine five-minute data.

For an existing five-minute manifest in a private cache:

```bash
python -m etoro_demo_bot.history.intraday_cli --cache .historical-data/research.sqlite --manifest MANIFEST_ID --symbol IBM --start 2026-03-09 --end 2026-03-09 --audit-at AUDIT_TIMESTAMP --calendar-verified-at REVIEW_TIMESTAMP --output .historical-data/intraday-audit.json
```

Replace the two timestamp tokens with actual aware ISO timestamps and the ID with the saved
manifest ID. The cache is opened read-only; a missing cache is not created. Output creation
is exclusive. Errors are sanitized and fail before a qualification report is written.
Exit 0 means structure qualified and report written, never replay/execution authorization.
Keep licensed raw data/caches private; do not commit them or expose them in logs/chat.

## Official capabilities checked on 2026-10-28

- The official bars reference supports 1–59 minute aggregation, including `5Min`, and an
  explicit `feed=iex`; it defines inclusive bounds, pagination and the 10,000 total-bar page
  limit. Authentication is required for stock data.
  https://docs.alpaca.markets/us/reference/stockbars
- The current Basic table lists free access, US equities/ETFs, IEX real-time equity coverage,
  history since 2016, 200 historical calls/min and the latest-15-minute restriction. This is
  a documented offering, not tested entitlement or continuous per-symbol five-minute coverage.
  https://docs.alpaca.markets/us/docs/about-market-data-api
- NYSE publishes 09:30–16:00 core sessions and the 2026 holiday/13:00 early-close schedule.
  The implementation remains bounded to the previously supported 2026 year.
  https://www.nyse.com/markets/hours-calendars

IEX is a single venue, not eToro executable pricing or consolidated-market coverage. Sparse
or missing IEX intervals can fail our completeness gate; we do not weaken it to make a
provider pass. Current data rights/account access and any redistribution restrictions still
need owner review. No paid service, subscription, new endpoint family or dependency is added.

## Tests, boundaries and next phase

Deterministic synthetic fixtures cover normal sessions, both DST boundaries, holidays,
weekends, both 2026 early closes, malformed/partial/missing/stale/future observations,
original UTC offsets, pagination/cursor/hash integrity, query/provider mismatches, version
rejection, source freshness, visibility without look-ahead, consumer incompatibility,
credential/network guards and read-only CLI behavior. Existing hourly tests remain intact.

Remaining blockers: authorized genuine data acquisition/coverage, source publication/revision
evidence, corporate actions, executable quotes/liquidity, historical FX/costs, earnings and
eToro instrument eligibility; fine-timeframe strategy/replay and historical MC adapters are
not implemented. Monte Carlo remains synthetic-only. No risk, kill-switch, Demo approval,
leverage or execution-policy code is changed. No ORB strategy or performance result exists.

Recommended next phase: a separately reviewed completed-bar 15-minute ORB **research**
consumer over qualified five-minute contracts, with explicit information-availability tests
and unchanged risk handoff. Genuine performance evaluation must wait for the evidence above.
