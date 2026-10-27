# Phase 8: hourly evidence qualification — acquisition remains blocked

Reviewed 2026-10-27 on verified main `df3b443` (Ubuntu/Windows main workflow successful).
**No source has been verified to supply the required 6–12 months of underlying US stock/ETF
hourly OHLCV with both acceptable access rights and no private credentials.** This is a result
of the provider review, not a claim that no such free service can exist. No market-data requests,
credentials, paid subscriptions, scraping workarounds or broker orders were used in this phase.

The delivered implementation is an offline hourly qualification/import path and backtest gate.
It does **not** pretend to be a verified remote hourly downloader. No real performance study ran.

## Provider comparison and access decisions

| Provider | Published hourly capability / retention | Access, terms and reliability | Decision |
|---|---|---|---|
| Yahoo / yfinance | The third-party library's current source includes `1h`/`60m` and a 730-day lookback. Its generic docstring also says intraday cannot extend beyond 60 days. These are library behaviors, not an official Yahoo retention SLA or observed coverage. `auto_adjust=True` defaults require special care. | yfinance explicitly says it is not affiliated/endorsed/vetted by Yahoo and refers users to Yahoo terms. Yahoo US terms prohibit automated collection without express prior permission. The library's software license is not a data license. No documented permission or official public hourly export was verified for this task. | No installation, chart endpoint calls, cookie/crumb collection, impersonation or scraping. No actual hourly coverage verified. |
| Alpha Vantage | Official TIME_SERIES_INTRADAY supports `60min`, raw or split/dividend-adjusted prices, month selection and advertises 25+ years. It is explicitly **Premium**. | Standard API quota is 25 requests/day; that does not make premium intraday data free. Personal-use terms and demo examples do not establish a six-month free hourly entitlement. | No paid endpoint or private key used. No qualifying free sample downloaded. |
| Stooq | Hourly depth, equity/ETF coverage and update frequency could not be verified. | Both official homepage and historical-download page returned 404 in this environment. This does not prove worldwide unavailability. Applicable terms, download rights and retention remain unresolved. | No guessed CSV endpoint, bypass or redistribution. |
| Alpaca Basic | Official docs show free US stocks/ETFs history since 2016, historical calls 200/minute and recent-15-minute restriction. Stock bars API documents hourly aggregation, pagination and raw/split/dividend/spin-off adjustment modes. | Basic realtime coverage is IEX, not consolidated US volume. Historical feed entitlement must be separately checked; do not assume all historical feeds are IEX-only or free SIP access. Account API authentication and applicable exchange agreements are required. Published capability is not observed symbol coverage or point-in-time correction history. | Strongest next candidate, but no private credentials requested or used. No account/feed license/access verification, so no downloader or real sample claim. |
| Dukascopy | Official historical-export page exists; its description focuses on Forex. Underlying US stock/ETF OHLCV, volume semantics and six-month coverage were not verified. CFD quotes must not be relabeled underlying exchange trades. | Linked terms permit some personal non-commercial downloads with notices, but prohibit automated access/acquisition without prior express written consent. No consent was established. No data accuracy/delivery guarantee. | No data-feed URL reverse engineering, automated download or raw sample redistribution. |

Official/provider-maintained references:

- Yahoo terms: https://legal.yahoo.com/us/en/yahoo/terms/otos/index.html
- Yahoo Finance additional terms: https://legal.yahoo.com/us/en/yahoo/terms/product-atos/finance/index.html
- yfinance disclaimer: https://ranaroussi.github.io/yfinance/
- yfinance history reference: https://ranaroussi.github.io/yfinance/reference/api/yfinance.Ticker.history.html
- Reviewed library implementation (not official Yahoo API documentation): https://raw.githubusercontent.com/ranaroussi/yfinance/main/yfinance/scrapers/history.py
- Alpha Vantage API: https://www.alphavantage.co/documentation/ and quota: https://www.alphavantage.co/premium/
- Stooq pages attempted: https://stooq.com/ and https://stooq.com/db/h/
- Alpaca plans: https://docs.alpaca.markets/docs/about-market-data-api
- Alpaca stock bars: https://docs.alpaca.markets/reference/stockbars
- Alpaca agreements: https://alpaca.markets/disclosures
- Dukascopy public export: https://www.dukascopy.com/swiss/english/marketwatch/historical/
- Dukascopy actual linked terms: https://www.dukascopy.com/swiss/english/legal-pages/terms-of-use/
- Dukascopy disclaimer: https://www.dukascopy.com/swiss/english/legal-pages/important-disclaimer/

[Review metadata](INTRADAY_SOURCE_REVIEW.json) records fetched page URLs, redirects, retrieval
timestamps, statuses and raw SHA-256 digests. These are **documentation** digests, not market data.
An initially guessed Dukascopy disclaimer URL returned 404; the actual footer link was followed
and returned 200. Regional terms can differ; no region's permission is inferred from another.
No hourly market-data update schedule, delivery SLA or correction vintage was independently
verified. Claims about retention above are published descriptions, not tested availability.
The existing eToro saved-schema evidence and current access limitations remain in
[HISTORICAL_DATA.md](HISTORICAL_DATA.md); no authenticated eToro requests were made.

## Actual sample coverage and results

| Requested type | Candidates for a future predeclared study | Verified hourly observations in this phase |
|---|---|---|
| Three US stocks | AAPL, MSFT, IBM | None |
| Two US ETFs | SPY, QQQ | None |

These candidates are a fixed, survivorship-biased research list, not a reconstructed historical
universe or a claim of eToro eligibility. Phase 7's 100 IBM **daily** observations and ECB
**reference FX** sample remain distinct; neither was substituted for hourly equity data.

For Momentum Breakout, Trend Following, Mean Reversion, buy-and-hold and cash, both EUR 500 and
EUR 1,000 runs are **not run**. Total return, maximum drawdown, win rate, profit factor, trade
count and costs are **unavailable**, not zero. No synthetic result is presented as real evidence.
Without qualified data, chronological train/validation/test performance comparisons are blocked.

## Offline implementation

`history.hourly` adds:

- `CoveragePolicy`: configurable minimum 183 observed calendar days, 120 complete full-hour
  sessions, 20 full sessions per train/validation/test partition, and at least 35 published
  warm-up bars. Defaults are research acceptance thresholds, not provider guarantees. A
  researcher can increase to 365 days; the current bounded calendar cannot certify 2025.
  Smaller study thresholds are explicit in the manifest. Warm-up cannot drop below 35.
- `StudyWindow`: predeclared aware, increasing train/validation/test/final boundaries inside
  the requested date range. No optimizer chooses these dates or inspects test outcomes.
- `audit_hourly`: reuses Phase 7 structural OHLCV checks, enforces the exact session-open
  hourly grid, rejects missing/duplicate/extra/off-grid/partial/future bars, wrong resolution,
  unsupported market, insufficient calendar/session/partition coverage and unavailable warm-up.
- `cached_hourly`: imports the existing normalized CSV contract from a checksum-verified
  SQLite snapshot. Exchange, currency and price basis must be explicit. No remote vendor API
  or licensing/price-basis inference is implemented. Source metadata remains an external
  assertion requiring review; an intact digest proves bytes, not truthful prices or rights.
- `run_hourly_study`: gates the existing `run_verified` → Backtest → Strategy/Risk path with
  coverage and evidence checks. It does not change any trading permission, risk rule, fill
  logic or backtest cost semantics. Existing train-only selection remains in
  `backtest.evaluation.evaluate_split`; this wrapper executes one predeclared replay.
- `readiness_manifest` and `history.hourly_cli`: deterministic JSON report with source/raw
  checksum/retrieval/snapshot, explicit timezone and alignment, price-basis/import metadata,
  calendar source/review timestamp, thresholds, coverage, partition/warm-up counts, and null
  performance comparisons. Existing output files are never overwritten. No HTTP or credentials.

NYSE 2026 calendar remains bounded to reviewed years, uses America/New_York DST, holidays and
13:00 half-days. A normal 6.5-hour session contains six **full** hourly bars and an explicitly
excluded final 30 minutes; a half-day contains three full hours plus 30 minutes. The report
counts omitted partial minutes. This is not complete intraday coverage. Vendor clock-hour
aggregation or truncated last bars cannot silently be treated as this session-open contract.
No interpolation, forward-filled candles, volume imputation or silent resampling is performed.

All three strategies share the scanner's 35-bar hourly warm-up. Warm-up is checked separately
at train, validation and test boundaries using both completion **and known-at** timestamps.
Future observations cannot satisfy earlier warm-up. A retrospectively retrieved CSV with blank
`known_at` defaults to retrieval time and therefore cannot claim historical point-in-time
availability. A supplied earlier time requires independent publication/revision evidence.

Raw and adjusted prices remain distinct. The existing split-as-of helper requires known/effective
action timing; adjusted values without complete actions fail structural checks. Replay still
requires raw prices, complete action coverage and no unsupported corporate actions. No dividend
portfolio accounting or historical earnings-event adapter is invented. Audit acceptance alone
never sets `point_in_time_verified`, `actions_complete` or execution authorization.

## Why OHLCV alone still cannot complete the existing replay

Existing strategy proposals expire after 30 seconds and require fresh quote/FX/eligibility
observations. Hourly candles cannot supply a later executable quote inside that window. Making
up intrabar prices to trigger fills would violate the current contract. Costs can be modeled
conservatively using existing Simulation parameters, but spread/slippage/FX **assumptions**
cannot certify missing market observations, broker minimum sizes or fractional permission.

Chronological split funding currently requires fresh FX/quote evidence at UTC-midnight starts.
That is an additional existing replay limitation for regular-session-only datasets. Supporting
an honest hourly-bar research simulation needs a separately reviewed simulation contract:
next-observed-bar fills, explicit costs, revised simulation-only proposal lifetime, funding/FX
valuation timing and gap/partial-session handling. Production risk limits must remain intact.
This phase does not silently reinterpret the existing strategies or their expiry rules.

## Next phase recommendation

1. Choose a legitimate data route: user-owned licensed exports (with rights and original
   provenance), or separately authorize a free account-based data integration such as Alpaca
   after reviewing feed and exchange terms. No credentials should be sent in chat. Neither
   option is assumed authorized by this phase's prohibition on private credential access.
2. Obtain and independently cross-check at least six months for the predeclared five symbols,
   raw prices, action vintages, calendar alignment, correction/publication times and volume
   coverage; expand the reviewed calendar before claiming twelve months across years.
3. Specify the offline hourly-bar simulation contract above, then independently validate
   unchanged risk limits, explicit conservative costs, affordability, chronological splits and
   sensitivity. Publish actual metrics only after the evidence and contract gates pass.

Tests are deterministic synthetic hourly fixtures plus the existing permitted recorded ECB
reference sample. No new recorded equity fixture was acquired without verified rights.
Cross-platform tests exercise LF/CRLF, UTF-8 BOM, offset/DST timestamps, exact bytes through
SQLite, and the retained Git checkout/hash regression tests. No new dependencies were added.
