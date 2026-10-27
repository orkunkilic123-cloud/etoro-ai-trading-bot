# Phase 7: historical evidence ingestion and replay readiness

Implemented daily-data ingestion first. **Real-data strategy performance validation remains
blocked.** Genuine downloaded observations are not automatically a point-in-time archive,
verified eToro eligibility, or an executable quote history. All execution gates remain unchanged.
No historical module loads credentials or performs network requests.

## Provider research (2026-10-27)

| Source | Official capabilities and free access | Limitations / terms / implementation |
|---|---|---|
| [Alpha Vantage documentation](https://www.alphavantage.co/documentation/#daily) | TIME_SERIES_DAILY raw/as-traded daily OHLCV; compact latest 100 observations free; stocks and ETFs supported by the service. The documentation supplies an IBM demo CSV URL. | Full history and intraday are premium in the reviewed docs; not used. [Standard limit](https://www.alphavantage.co/premium/) is 25 requests/day, not a guarantee of demo availability. Daily observations are not real-time quotes; no guaranteed publication latency or revision archive verified. Daily CSV parser implemented; no authenticated downloader. |
| [Alpha Vantage terms](https://www.alphavantage.co/terms_of_service/) | Personal, non-commercial research/testing by a private individual on their controlled computer. | Corporate/entity use, financial-industry affiliation and supplying information to others can fall outside that grant. No redistribution grant verified: IBM payload stays local, excluded from Git. Data supplied as-is; no reliability guarantee. User must check applicability before downloading. |
| [Alpaca market data](https://docs.alpaca.markets/docs/about-market-data-api) | Basic free tier documents US stocks/ETFs, history since 2016, 200 requests/minute, recent 15-minute restriction and IEX-only realtime coverage. | Requires account/feed entitlement; free IEX is not consolidated market coverage. [Disclosures](https://alpaca.markets/disclosures) reviewed but applicable market-data agreement not verified (attempted PDF returned 403). No credentials requested, download, adapter or reliability claim. Candidate for future licensed intraday integration. |
| [ECB reference rates](https://www.ecb.europa.eu/stats/policy_and_exchange_rates/euro_reference_exchange_rates/html/index.en.html) | EUR base, including USD; working-day updates around 16:00 CET except TARGET closing days; 90-day XML available. | Information-only reference rates; ECB discourages transaction use. Not executable FX, commissions or spread evidence. Parser implemented, not substituted for the Risk Manager's fresh FX evidence. |
| [ECB reuse conditions](https://www.ecb.europa.eu/services/disclaimer/html/index.en.html) | Free use with accurate reproduction and source attribution; modifications must be identified. | Unmodified recorded XML included with attribution and checksum in `tests/fixtures/history`; it is real reference FX data, not stock performance evidence. |
| Provider-neutral licensed CSV | Daily and hourly OHLCV exports with explicit timestamps and price basis. | Source, license, checksum and symbol mandatory. No presumption of rights, coverage, completeness or original availability. No vendor URL invented. |

Stooq was considered, but the attempted official terms URL returned 404; no permission or
coverage claim, downloader or dataset added. No paid service or premium endpoint is used.
A broad liquid-stock/ETF universe, delisted constituents and survivorship-free history have
**not** been obtained. IBM is the only observed stock sample; no actual ETF sample was validated.

## eToro documentation

Fresh requests to [API portal OpenAPI](https://api-portal.etoro.com/api-reference/openapi.json)
and [Builders](https://builders.etoro.com) returned HTTP 403. A previously retained official
OpenAPI snapshot was inspected locally (SHA256
`6fef7174f485d4bce880b85e7c0f5f0a71637f4dd9ced8258b94d2d4ce87a491`). This is evidence of the
saved documentation, **not** fresh endpoint availability or account entitlement verification.

That snapshot documents:

- `GET /api/v1/data/instruments/{instrumentId}/candles`: required `interval` in
  `1m,5m,10m,15m,30m,1h,4h,1d,1w`; optional ISO timezone-aware `from` inclusive, `to` exclusive;
  `limit` 1–2000 (default 100), `side=bid|ask|both` (default bid),
  `format=verbose|compact`, opaque pagination `cursor`. At most 10,080 periods per slice;
  follow `pagination.nextCursor`. Example verbose records contain `time,open,high,low,close,volume`.
- `GET /api/v1/data/instruments/{instrumentId}/candles/coverage`: interval-specific
  `firstCandle,lastCandle,candles,loadedAt`; description says history *can* exceed 15 years.
  Empty coverage/results are valid; this is not a coverage promise for any instrument.
- These two routes share **120 requests per 60 seconds**; account-independent data does not
  mean unauthenticated access. Snapshot security includes API-key/user-key or OAuth scopes;
  UUID `x-request-id` is required. No credentials or eToro API calls were used here.
- Legacy `/api/v1/market-data/instruments/{instrumentId}/history/candles/{direction}/{interval}/{candlesCount}`
  and `/api/v1/market-data/instruments/history/closing-price` also appear in the snapshot.

Corporate-action adjustment methodology, original publication/revision timestamps, complete
volume coverage, earnings history and historical fractional/minimum-order eligibility remain
unverified. Candle sides alone are not synchronous executable quotes. No new eToro routes were
added to any allowlist. A future adapter requires fresh schema/terms verification and a reviewed
session-boundary mapping: the documented daily timestamps cannot simply be assumed NYSE opens.

## Architecture and contracts

`history.models` defines immutable Source, History, Bar and Action records plus provider/calendar
protocols. `providers` contains Alpha Vantage raw daily CSV, neutral CSV and ECB parsers; the
registry supports multiple providers without changing the backtester. CSV dates map only through
a reviewed calendar, never UTC-midnight assumptions. Unknown price basis remains blocked.

`calendar.NYSE2026` implements the reviewed [NYSE schedule](https://www.nyse.com/markets/hours-calendars):
09:30–16:00 America/New_York, holidays, November 27 / December 24 13:00 closes and DST. Other years
fail closed; an injected calendar must cover them. The schedule is current knowledge, not a
historical publication archive. Unexpected halts and corrections require further evidence.
Pinned Apache-2.0 `tzdata` supports Windows where system IANA data may be absent.

`quality.inspect` checks missing/duplicate/unordered candles, finite OHLC ranges, volume,
session boundaries, stale last sessions (when requested), future/incomplete candles,
implausible availability, mixed/unsupported adjustments and configurable opening jumps (25%
default). It never fills gaps. Known splits may explain jumps, not certify data quality.
Hourly regular sessions contain six full hours plus an excluded final 30 minutes; this adapter
cannot certify that missing partial interval as hourly coverage. Diagnostics are not a substitute
for independent vendor/corporate-action reconciliation.

`split_adjust_as_of` applies only splits both effective and known by the decision timestamp to
raw, already available bars, scaling price and volume reciprocally. Future announcements and
late-known events cannot leak backward. Duplicate actions are rejected. A caller must attest
complete action coverage. Cash-dividend actions can be represented but total-return adjustment
and portfolio corporate-action accounting are **not** implemented; such replay is blocked.

`Archive` stores immutable raw payloads and source metadata in local SQLite, with retrieval time,
license classification and SHA256 identity. Reads check integrity. A new retrieval produces a new
snapshot; previous observations are not overwritten. Integrity establishes byte identity, not
truth or licensing. The CLI is deliberately offline: obtain a permitted file once, then reuse it
without consuming API quota. No scheduled downloads or implicit retries exist.

`replay.run_verified` is an integration gate to the existing Phase 6 Backtest/Strategy/Risk
interfaces. It requires reviewed raw hourly history, complete action coverage, original
availability, matching symbol/currency, calendar-consistent sessions and independently supplied
quote, FX, product, fractional/minimum-order, quantity-step and earnings evidence. It preserves
actual `known_at` timestamps and binds candle provenance to the replay manifest. No risk checks,
minimum orders or freshness checks are relaxed. Review flags are explicit attestations, not an
automatic verification oracle. Complete supporting evidence still needs independent review.

Daily candles **cannot** satisfy the current hourly strategies and 30-second proposal/60-second
quote and FX contracts. Converting one daily close into invented intraday ticks or stale FX would
invalidate the experiment. Rather than invent that information, `write_readiness` emits reproducible
Markdown/JSON/CSV comparisons with blocked status and null performance for Momentum, Trend and
Mean Reversion, buy-and-hold and cash, for EUR 500 and EUR 1,000. These are readiness reports,
not executed backtests. Existing synthetic Phase 6 backtests remain separately labeled.

## Observed coverage and reproducibility

Public IBM raw daily CSV retrieved **2026-10-27 16:45:40 UTC**:

- 100 observations, **2026-06-04 through 2026-10-26**; reviewed regular-session dates complete.
- SHA256 `56b2cdce40220ea0e998aad03b8ba91e0dc6b2a63ca90be68844033c01ed6f54`.
- No blocking structural findings; corporate-action completeness unknown. This is not proof of
  independent price accuracy or point-in-time availability. Earliest demonstrable availability
  is retrieval time, not the historical closing timestamp.
- Local snapshot `165f41463267ccd68e6cd631ff0e518e5e84d81b75077df1cc2444b66b3105c5`.
  Offline replay of the audit produced byte-identical reports. Snapshot is local, not bundled.

ECB recorded XML has **64 USD reference observations, 2026-07-30 through 2026-10-27**.
Full payload checksum/retrieval metadata and attribution are in `tests/fixtures/history/ecb-source.json`.
No statement about strategy profitability can be made from either sample.

For real performance comparisons the next dependencies are licensed sufficient-length history,
reviewed historical quote/session/FX and eligibility events, earnings calendar vintages, corporate
accounting, and independent data checks. Alternatively, a separately specified daily strategy/fill
contract is needed; it must not silently change the existing strategies. Short recent samples
cannot support meaningful train/validation/final-test or walk-forward conclusions.

## Phase 8 follow-up

See [INTRADAY_DATA.md](INTRADAY_DATA.md) for the current provider/terms comparison, observed
lack of qualifying hourly samples, configurable coverage and chronological warm-up checks,
and remaining simulation-contract limitations. The Phase 7 daily and ECB reference samples
are not hourly equity evidence. No trading permissions or source-integrity checks changed.

## Optional Alpaca adapter

[ALPACA_MARKET_DATA.md](ALPACA_MARKET_DATA.md) documents the new explicitly opt-in market-data
client and offline page/manifest provider. Raw byte checksums, native timestamps and feed/price
basis remain intact. No actual Alpaca access or dataset coverage has been verified; this does
not resolve point-in-time, calendar-alignment, corporate-action or execution-evidence gaps.
