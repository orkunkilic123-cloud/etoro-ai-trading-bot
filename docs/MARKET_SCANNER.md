# Phase 4: market scanner

The scanner discovers stocks/ETFs, observes market data and produces expiring, explainable rankings. It never constructs broker orders, grants approval, reserves risk capacity or calls the execution engine. Network access defaults off; there is no scanner credential-loading CLI or autonomous execution switch. Existing 1% trade risk, 3% daily halt, leverage restrictions and exact-order authorization remain unchanged.

## Verified capabilities and evidence

Source: https://api-portal.etoro.com/api-reference/openapi.json. The official schema retrieved during Phase 3 on 2026-10-27 remains available in the environment; SHA-256 `6fef7174f485d4bce880b85e7c0f5f0a71637f4dd9ced8258b94d2d4ce87a491`. Phase 4 re-inspected that schema. A fresh retrieval returned HTTP 403 from the portal, so this phase does **not** claim a fresh successful remote verification. No authenticated API requests were made. See API_FINDINGS.md for provenance and quota discrepancies.

The scanner pins `https://public-api.etoro.com`, disables redirects and permits only:

| Method and path | Request | Normalized fields |
| --- | --- | --- |
| GET `/api/v2/market-data/instruments` | `type=Stocks` or `ETF`, `pageSize=100`, optional opaque `pageToken` | `results[].instrumentId`, `symbol`, `type`, `exchangeId`; `pagination.hasNext/nextPageToken` |
| GET `/api/v2/market-data/rates` | `instrumentIds`, batches of at most 1000 | `results[].instrumentId/bid/ask/date/quoteType`; 206 means missing instruments, never complete data |
| GET `/api/v1/market-data/instruments/{instrumentId}/history/candles/asc/OneHour/100` | Exact positive integer ID, no query | `interval=OneHour`, `candles[].instrumentId`, nested `candles[].instrumentID/fromDate/open/high/low/close/volume` |
| POST `/api/v2/trading/info/demo/eligibility` | `{"instrumentIds":[...],"currency":"USD"}`, at most 100 IDs | `currency`, `eligibilities[]`, `notFoundInstrumentIds`; this is a non-executing inquiry |

The candle route, ordering, interval and count are documented; no historical endpoint is invented. Schema `fromDate` is the candle start. The adapter uses only hourly history (100 requested, at least 35 completed bars required). Every HTTP request carries `x-api-key`, `x-user-key` and a new UUID `x-request-id`. No order routes, Real account routes, arbitrary origins or live fallback are allowed. Errors discard upstream bodies and transport exception context. The scanner itself emits no credential/account logs.

Discovery metadata is a catalogue, **not** proof of tradability. Demo eligibility must affirm opening permission, a non-potential underlying (`settlementType=real`) long configuration containing integer leverage 1, units sizing, whole/fractional status, minimum USD exposure/margin and maximum units. Ambiguous/missing permissions fail closed. Positive additional broker buffer requirements remain unsupported, matching the conservative execution preflight.

## Trusted evidence and limitations

`EvidenceProvider` must supply independently verified product and session evidence, and attest history coverage. No default provider invents these facts:

- Product currency must be USD, and the product itself must be unleveraged and underlying. A Stocks/ETF label or leverage=1 does not prove a fund is unleveraged. Leveraged/inverse/derivative products must be excluded by the trusted review. The implemented v2 metadata schema does not provide enough information to automate that review.
- Session evidence supplies the instrument ID, open status, source, observation time and validity deadline. Recheck it near ranking. Closed/unknown sessions produce no opportunity, even where the broker allows queued entry orders. The provider must use verified exchange hours, holidays and daylight-saving rules; the scanner does not assume US hours or derive market-open status from a fresh quote.
- History coverage attestation must establish that gaps correspond to known closed sessions, bars use consistent units/adjustments and volume is comparable. Missing sessions, split adjustments, partial session bars and unexplained gaps cannot be silently filled. The scanner validates positive finite OHLC, ordering, no overlap and completed bars. It does not synthesize missing candles or infer exchange calendars. The default maximum completed-history age is four days to permit weekends; that age alone never proves completeness.
- EUR budget conversion needs fresh **USD per EUR**, a source and explicit conversion costs. No unverified FX instrument ID or conversion field is guessed. Non-USD securities are currently excluded; conversion of their historical prices/exposure remains future adapter work.
- Fee, commission, spread/slippage and free-access evidence are account/region dependent. No fees are assumed to be zero. `network_enabled=True` and `free_access_confirmed=True`, plus explicit Demo credentials, are required for future network use. These are trusted caller attestations, not remote entitlement verification. No paid provider or new dependency was added.

The data client accepts credentials as an explicit object; it never reads the environment itself. Demo declaration retains the existing read-only foundation's trust model and is not independent cryptographic verification of opaque keys. Account-specific access remains untested. Do not enable HTTP wire logging or exception tools that dump frame locals.

## Small-portfolio affordability

`Budget` uses isolated 60-digit Decimal arithmetic. It accepts EUR 500–1,000 (and other positive amounts), explicit fresh FX and explicit cost estimates. It computes:

- Usable USD budget = EUR equity × USD per EUR × (1 − conversion cost fraction).
- Minimum units = broker minimum USD notional / ask, rounded **up to whole units** if fractional trading is unavailable. This is an analytical feasibility bound; it is not an executable quantity or an assertion about the broker's fractional step size.
- Minimum notional must satisfy both the minimum exposure and underlying configuration minimum margin; units cannot exceed the documented maximum.
- Cash required = minimum notional + explicit round-trip fixed fees + proportional fees/slippage + units × (ask − bid).
- Default allocation screen: cash required ≤ 20% of usable budget. Default cost-efficiency screen: total estimated costs including pro-rata FX cost ≤ 2% of minimum notional. Both are configurable scanner screens, not amendments to risk limits. Screening the minimum allocation conservatively can exclude instruments that would be cost-efficient at a larger allocation.

This checks affordability only. It does not know available account cash, existing positions, daily loss, reservations or the correct stop-loss. A Strategy Agent must choose size/stop and a fresh complete account snapshot; the existing Risk Manager must then apply **all** of its rules. Scores and affordability never authorize execution or promise profitability. Actual spreads, commissions, FX and slippage can differ from estimates.

## Indicators and ranking

Completed hourly bars only; forming candles are excluded. At least 35 valid completed bars are required for MACD signal warm-up. Calculations use floats for analysis, Decimal for money:

| Feature | Definition |
| --- | --- |
| SMA / EMA | 20 bars; EMA starts with 20-bar SMA and alpha 2/21 |
| RSI | 14 changes, Wilder smoothing; flat=50, no losses=100, no gains=0 |
| MACD | SMA-seeded EMA12 − EMA26, signal EMA9 over aligned MACD series |
| ATR | 14 true ranges from consecutive bars, Wilder smoothing |
| Relative volume | Last completed bar volume / mean of **previous** 20 bars; missing/zero baseline disables volume scoring |
| Volatility | Population standard deviation of last 20 log returns, per observed bar, not annualized |
| Momentum | Close / close 10 bars earlier − 1 |
| Breakout reference | Highest high of prior 20 bars, excluding signal bar |

Default contributions sum to at most 100. Rules are version-controlled, deterministic and configurable:

- Momentum breakout: close > previous high and momentum ≥ 2%: 35 points.
- Trend continuation: close > EMA20 > SMA20, MACD > signal, momentum > 0: 30 points.
- Unusual volume: relative volume ≥ 2: 20 points.
- Potential mean reversion: RSI ≤ 30 and close < SMA20 − ATR: 15 points.

Default minimum score is 15; per-bar volatility over 0.1 blocks ranking. Multiple matched rules contribute independently. Missing volume disables its contribution; price-only setups can still qualify. Mean reversion is a potential setup, not a prediction or instruction to buy. Scores are rankings **not profit probabilities**. Ties sort by instrument ID. Features and each contribution accompany the result.

## Scheduling, quotas and caching

`Scanner.run_due()` is caller-driven, serialized and defaults to a five-minute schedule. Calling it early returns `None`; a due scan can return an empty result. There is no daily trade quota, forced trade or autonomous execution loop. A failed scan still advances the schedule, avoiding a tight retry loop. Clock rollback and naive timestamps fail closed; all comparisons use aware timestamps and UTC-normalized broker dates.

Discovery is bounded to 20 pages per category by default (configurable up to 100). Cyclic/missing cursors, duplicate IDs or unfinished pagination cause explicit errors, never a falsely complete universe. Scans default to at most 200 instruments; a larger catalogue requires an explicit `watchlist` or a reviewed higher limit. There is no silent top-N truncation. Unknown watchlist IDs fail closed. Small watchlists are more practical than rescanning an entire catalogue every few minutes.

Rates batch 1000 IDs; eligibility batches 100. Async preparation has bounded concurrency (default four, maximum 16); the HTTP client serializes its requests and caches to avoid in-flight duplication. Quotes are retrieved after slow history work. Session evidence is refreshed before ranking. API errors and 429 produce safe failures; there are no automatic request retries, and callers must wait for both the scan schedule and persisted cooldown.

OpenAPI documents 120 market-data calls/minute shared across routes; the overview says 60 reads/minute. The scanner conservatively spaces all market calls by at least 1.1 seconds (at most 55 starts in a rolling minute), and eligibility by 3.1 seconds (at most 20). SQLite serializes admission across scanner clients/processes **sharing the same ScanStore**. `RateLimit-Limit`, remaining/reset and `Retry-After` can only slow pacing. Cooldowns persist over restart; waits over five minutes abort. Corrupt storage fails closed. Timeout bounds are 5s connect, 15s other operations.

Use **one shared scanner store and one quota owner for each key**. Existing Phase 1/3 clients and unrelated applications do not participate in these scanner quota tables; do not run them concurrently on the same key without a future common quota coordinator. No library can guarantee remaining server quota consumed by unrelated applications. Never delete quota state to evade a cooldown.

Metadata is cached for one hour and candle responses for 60 seconds in SQLite. Quote and account-specific eligibility responses are never cached. The scanner reuses computed features while completed history is unchanged, keeping at most one result per scanned instrument. `CachedEarnings` persists versioned, sourced facts until the provider's explicit expiry and rejects stale/future data; use a separate version namespace per provider/model revision. There is no built-in fundamental/earnings endpoint or invented dataset. A future free verified provider can implement `EarningsProvider` without changing ranking. Missing optional fundamentals are represented as `None`, never neutral or fabricated financial results.

Opportunity expiry is the earliest deadline among the configured TTL (maximum 60 seconds), quote age (maximum 60 seconds), eligibility age, product/session evidence, FX freshness, history age and optional fundamentals. Results are checked again before return; consumers **must** call `valid_at(now)` and refresh all evidence before any downstream use. Expired opportunities are not reused from cache.

## Interfaces, operation and tests

- `MarketSource`: discovery, quotes, hourly history, eligibility; `MarketClient` is the official eToro adapter. Future free providers must preserve the timestamp, completeness and precision contracts.
- `EvidenceProvider`: trusted product/session/coverage review; no implementation supplied that could guess unknown metadata.
- `EarningsProvider` / `CachedEarnings`: optional sourced/versioned facts, independent of technical scoring.
- `StrategyAgent`: consumes an unexpired Opportunity and may produce a risk Proposal; does not approve it.
- `RiskReviewer`: the existing RiskEngine interface. Scanning never calls it, because a risk PASS reserves capacity; speculative rankings must not reserve every candidate.

Composition requires explicit `MarketSource`, `EvidenceProvider`, `Budget`, optional policy/watchlist and earnings provider. Store analysis state in ignored `.scanner-state/` (create the directory explicitly), separate from the safety-critical risk/execution DB. Protect local state with OS permissions. No migrations or changes to existing safety state occur.

Run the offline mocked workflow described in WINDOWS_SETUP.md. Tests cover numerical references, flat/up/down markets, malformed/insufficient history, missing volume, warm-up, affordability, costs, expiry, timezone offsets, closures, metadata uncertainty, batching, partial responses, pagination cycles, shared quota timing/restarts, corrupt cache, timeouts, disabled network and exact endpoint rejection. Existing risk/execution suites must also pass. Actual account access, live market sessions, exchange-specific volume/candle semantics and free data entitlements remain untested. This is an analysis foundation with explicit integration gates, not a claim of trading readiness.
