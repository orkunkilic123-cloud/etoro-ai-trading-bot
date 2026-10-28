# Alpaca read-only historical market data

Implemented against official documentation reviewed on 2026-10-27 (Europe/Amsterdam).
**No actual credentials were read and no authenticated requests were made.** Tests use invented
keys and deterministic mocked data. Historical availability, account entitlement and symbol
coverage remain unverified until a separately authorized authenticated request succeeds.

## Official contract and free-tier limits

- [Market-data plans and authentication](https://docs.alpaca.markets/docs/about-market-data-api)
  document Basic as free, US stocks/ETFs, realtime IEX coverage, history since 2016,
  a recent-15-minute historical restriction and 200 historical requests/minute.
  These are service-level statements, not coverage guarantees for each IEX symbol.
  The FAQ specifically restricts recent SIP access without a subscription; Basic realtime IEX
  is distinct. This client conservatively requests only hours completed at least 15 minutes ago
  and never attempts SIP, even for older periods.
- [Historical bars](https://docs.alpaca.markets/reference/stockbars) document
  `GET https://data.alpaca.markets/v2/stocks/bars`. Authentication headers are
  `APCA-API-KEY-ID` and `APCA-API-SECRET-KEY`. The integration does not use broker-partner
  OAuth, account endpoints or trading endpoints.
- Required query fields: comma-separated `symbols`, `timeframe`. This client uses `1Hour`,
  explicit RFC3339-aware `start` and `end` (both inclusive **bar-start** bounds), `sort=asc`,
  `limit=10000`, `currency=USD`, `feed=iex`, `adjustment=raw|split`, and `asof=-`.
- Provider default feed is SIP, so **IEX is always explicitly sent**. SIP, OTC, overnight,
  crypto, options and paid-tier feed selection are unavailable in this client. No subscription
  endpoint, upgrade, fallback or chargeable-service integration exists.
- `asof=-` disables implicit current-day symbol mapping. It does not reconstruct a historical
  investable universe or eliminate survivorship bias. Delistings/name changes need independent
  review. Current symbol identity must not be assumed to establish historical eligibility.
- Results are sorted by symbol then timestamp. One page can contain only the first symbol.
  `limit` is across symbols, not per symbol. Follow **every** `next_page_token` until null;
  a short/empty page does not establish completion when a token remains.
- Raw page fields consumed are `bars: {symbol: [{t,o,h,l,c,v,...}]}` and `next_page_token`.
  The raw archive also preserves trade count `n`, VWAP `vw` and other provider fields without
  substituting them for volume or prices. Timestamp `t` is the interval's left edge.
- [Market-data FAQ](https://docs.alpaca.markets/docs/market-data-faq) explains IEX versus SIP,
  aggregation and missing bars. Hour bars aggregate minute bars in the given hour. Bars may be
  absent when no qualifying trades produce valid prices; absence is not a zero-volume candle.
  IEX is a single exchange, not consolidated US volume or a universal liquidity measure.
- The API schema documents `X-RateLimit-Limit`, `X-RateLimit-Remaining`, and
  `X-RateLimit-Reset` as a **UNIX epoch**, not a delay. The client also honors `Retry-After`.

[Review metadata](ALPACA_SOURCE_REVIEW.json) preserves source URLs, statuses, retrieval timestamps
and raw document SHA-256 digests. A guessed stock-pricing explanatory URL returned 404; bar
aggregation was instead verified in the official FAQ. No behavior was inferred from the 404 page.

[Alpaca disclosures](https://alpaca.markets/disclosures) link account and exchange data agreements.
A free plan is not permission to redistribute raw observations. The user must review applicable
terms and confirm Basic IEX access locally. No raw Alpaca fixtures are redistributed in this
repository. The local confirmation flag records a user assertion, not verified account access.

## Safety and architecture

- `alpaca.config.Credentials.from_environment()` reads only `ALPACA_DATA_API_KEY`,
  `ALPACA_DATA_API_SECRET` and `ALPACA_DATA_FREE_ACCESS_CONFIRMED`. Importing modules and
  running offline parsers/help do not read keys. Credentials are excluded from object reprs.
- `alpaca.client.MarketDataClient` has one exact allowed method/path and one fixed HTTPS host.
  No base-URL/header/feed override, generic SDK client, account discovery or order method is
  exposed. `enabled=False` by default. Redirects are never followed; TLS verification stays on.
  Codex Cloud uses its policy-approved explicit HTTPS proxy and supplied CA trust; see
  [cloud setup](CODEX_CLOUD_ALPACA.md). Generic proxy/netrc inheritance remains disabled,
  so NO_PROXY cannot bypass this route. Local mode uses verified system/configured CA trust.
  Never disable TLS verification to make a connection work.
- `request()` rejects all other methods, full URLs, alternate paths and encoded traversal before
  any transport call. Only query-generated parameters can reach the transport. API keys can have
  broader powers at Alpaca; this application boundary does not make the underlying key read-only.
  Python private members are not an adversarial-code sandbox.
- Rate state uses the existing SQLite `ScanStore` in the same local archive: one request/second,
  including retries and concurrent clients/processes sharing that file. Use the same archive
  for all this application's clients. Other applications/different files can consume additional
  account quota; provider throttling remains authoritative.
- GET retries are bounded to three attempts for transport failures, 429 and 500/502/503/504.
  Authentication/permission errors and redirects are not retried. Server cooldowns persist across
  clients/restarts; clock rollback fails closed. Automatic sleeps are capped at 60 seconds;
  longer cooldowns block until a later invocation, without shortening the server's delay.
- Pages are limited to 4 MiB and downloads to 100 pages, with 1–20 validated symbols. Pagination
  cycles, duplicate/unordered per-symbol timestamps and incomplete chains fail closed. Failure
  may leave raw page snapshots but no successful download result; these are not complete datasets.
- Error bodies are discarded, errors do not retain HTTP request/response objects or upstream
  exception contexts, and raw/JSON-escaped credential echoes are rejected before caching.
  No headers, credentials, account information or HTTP payloads are logged. Do not enable
  external HTTP wire debugging with real credentials.

## Provenance and offline integration

`Archive` stores each original decoded HTTP entity body as bytes before JSON parsing or
reserialization, with exact SHA-256, actual request URL/parameters and retrieval time. HTTP
content-encoding decompression is distinct from changing JSON bytes/newlines. Credentials are
headers only, never URL parameters. Raw bytes are not normalized across Windows/Linux.

A completed download stores a second immutable manifest containing the ordered page snapshot
IDs, full query, feed, alignment and timezone policy. `load_download()` revalidates all page
checksums, source/query equality, cursor chain, terminal page and cross-page ordering before
combining a symbol. The manifest links every source page and retrieval timestamp. Its checksum
is a chain identifier, not a replacement for the raw page checksums. The provider protocol's
`AlpacaBars.parse()` handles a single page; prefer `load_download()` for a whole request.

Example offline integration after an authorized future download:

```python
from pathlib import Path
from etoro_demo_bot.history.archive import Archive
from etoro_demo_bot.history.alpaca import load_download

archive = Archive(Path('.historical-data/alpaca.sqlite'))
history = load_download(archive, '<completed-manifest-id>', 'IBM', exchange='XNYS')
```

Exchange mapping is caller-reviewed, not inferred from an Alpaca symbol. Stock/ETF service
coverage does not prove an instrument is an unleveraged underlying asset or eligible on eToro.
Account/asset lookup endpoints are intentionally blocked. Existing backtests still require that
independent eligibility, minimum order, fractional-step and product evidence.

The returned `History` integrates with `audit_hourly`, `readiness_manifest`,
`run_hourly_study` and the existing Backtesting Engine. It retains USD prices, raw versus
split-adjusted basis, UTC-normalized native timestamps and exact original offsets in raw pages.
The known-at time is the page's retrieval time. No original publication/correction vintage,
complete corporate-action ledger or historical earnings knowledge is invented.

`split` adjusts price and volume according to the provider request. It does not become raw data
or point-in-time-safe merely because the request succeeds. Dividend/spin-off/all adjustments
are deliberately unsupported. `actions_complete` and `point_in_time_verified` remain false.
Existing split/jump/coverage diagnostics and replay gates remain mandatory.

`session_counts()` classifies full regular-session, boundary-overlap and outside-session bars
using the injected reviewed calendar and America/New_York DST. It does not filter, stretch or
shift candles. The current reviewed calendar is NYSE 2026 only; older years and other exchange
mappings require further review. Native clock-hour bars can straddle the 09:30 open; classification also respects a 13:00
half-day close. They do not match the existing strategy's 09:30-anchored grid. That mismatch is
reported and rejected by the hourly study gate, not silently resampled. Missing IEX bars are
never interpolated to make coverage or an opportunity pass.

## Remaining limits and portfolio scenarios

EUR 500 and EUR 1,000 scenarios continue through the existing unchanged Backtesting Engine.
This integration does not manufacture FX observations, spreads, slippage, minimum sizes,
fractional permission, synchronous quotes, session vintages or earnings events. Their absence
blocks a real-data replay. The 30-second proposal lifetime and required later quote inside it
remain incompatible with OHLCV alone; see [INTRADAY_DATA.md](INTRADAY_DATA.md).

No real portfolio backtest was run. Actual symbol coverage, authenticated Basic access, native
bar alignment in returned data and feed suitability remain unverified. Next steps are a separately
authorized small IEX read, source/calendar/volume/action review, and a separately specified
hourly-bar simulation contract. No eToro or Alpaca execution permissions were changed; Demo,
Real and autonomous order execution remain disabled in this workflow.
