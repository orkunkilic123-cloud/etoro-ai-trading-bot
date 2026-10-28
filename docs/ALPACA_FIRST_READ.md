# First Alpaca read and historical-backtest readiness

Reviewed 2026-10-28 against main `9ed6d71f0cfce75cee3567e044f62f69d256a979`,
including merged PR #12. No credentials or authenticated requests were used in this review.
No genuine historical backtest or profitability result has been produced.

## What the official sources establish

| Topic | Verified public documentation | What remains unverified |
| --- | --- | --- |
| Basic plan | Free; US stocks and ETFs; real-time equity coverage is IEX; history advertised since 2016; 200 historical API calls/minute; latest 15 minutes restricted in the plan table [1] | This user's entitlements, symbol-by-symbol first dates, missing bars and actual retention |
| Hourly bars | `GET https://data.alpaca.markets/v2/stocks/bars`, `timeframe=1Hour`, inclusive start/end, OHLCV aggregates; pagination applies across symbols [2] | Completeness and session alignment of any actual download |
| Feed | IEX is one exchange; Alpaca describes it as suitable for initial app testing [3] | Consolidated-market prices, NBBO, eToro spreads, fills or liquidity |
| Authentication | Individual users send `APCA-API-KEY-ID` and `APCA-API-SECRET-KEY` headers to the historical data host [1,4] | Credential validity and account-specific access; broker-partner auth is a different workflow |
| Terms | Terms linked from the current disclosures index describe personal non-commercial use, notice for other uses, additional applicable agreements and no completeness warranty [5,6] | Permission to redistribute raw or derived data, public hosting, commercial usage, or particular exchange permissions |

Use only IEX here; do not switch feeds or upgrade plans to resolve an access error.
The documentation's broad history claim is not a guarantee of continuous hourly IEX data
for every security since 2016. A successful request establishes access only for the exact
query. Empty results establish neither full coverage nor a successful backtest dataset.
The client conservatively requests hours completed at least 15 minutes earlier, regardless
of any broader entitlement. The API reference defaults to SIP: our query explicitly pins IEX.

Sources (reviewed 2026-10-28):

1. https://docs.alpaca.markets/us/docs/about-market-data-api
2. https://docs.alpaca.markets/us/reference/stockbars
3. https://docs.alpaca.markets/us/docs/historical-stock-data-1
4. https://docs.alpaca.markets/us/docs/market-data-faq
5. https://alpaca.markets/disclosures
6. https://files.alpaca.markets/disclosures/library/TermsAndConditions.pdf

## Safest first authenticated test: owner-operated local process

Prefer a terminal on your own trusted machine, outside an AI agent session. Install the
reviewed branch in a dedicated Python 3.12+ virtual environment. Do not run a broker SDK,
MCP broker, execution CLI or account probe. A market-data request does not need an account
endpoint. Review your Basic access and applicable agreements in Alpaca's UI yourself,
without sharing keys. Do not activate a paid trial or subscription.

Before entering any credentials, run:

```bash
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m etoro_demo_bot.alpaca --dry-run --symbols IBM --start 2026-03-09T00:00:00Z --end 2026-03-10T00:00:00Z
```

The preview validates syntax and outputs the fixed route and normalized parameters. It
loads no credentials, makes no HTTP client or cache, and does not verify age, access or
coverage. It cannot be combined with `--enable-network`.

After reviewing the preview, you can personally run the following Bash block in a fresh,
trusted terminal. It prompts invisibly, keeps values out of command history and files,
and confines the exported variables to a subshell. Do not use shell tracing, terminal
recording, HTTP debug logging, `env`, `printenv`, notebook cells or an AI tool for this step.
Never replace the prompts with literal values in a command. Do not create a `.env` file.

```bash
(
  set +x
  trap 'unset ALPACA_DATA_API_KEY ALPACA_DATA_API_SECRET' EXIT
  read -r -s -p 'Alpaca data key (hidden): ' ALPACA_DATA_API_KEY; printf '\n'
  read -r -s -p 'Alpaca data secret (hidden): ' ALPACA_DATA_API_SECRET; printf '\n'
  export ALPACA_DATA_API_KEY ALPACA_DATA_API_SECRET
  export ALPACA_DATA_FREE_ACCESS_CONFIRMED=true
  python -m etoro_demo_bot.alpaca --enable-network --request-limit 1 --symbols IBM --start 2026-03-09T00:00:00Z --end 2026-03-10T00:00:00Z --cache .historical-data/alpaca-first.sqlite
)
```

This is activation guidance, not a command executed during this review. Environment values
remain accessible to trusted processes with sufficient local permissions. The CLI reads
only the two named variables after explicit network opt-in and free-access confirmation.
Use the existing managed-proxy instructions in CODEX_CLOUD_ALPACA.md if that platform
applies; never bypass proxy policy or disable TLS to make the test work.

`--request-limit 1` allows at most one GET for the client lifetime, including retries and
pagination. A timeout, retryable status or next-page token can therefore fail without a
complete manifest. Partial cached pages are not a completed download. Stop and investigate
sanitized failures; do not repeatedly retry 401/403, enable debug logs or try trading hosts.
Default bulk downloads remain bounded at 300 GETs, 100 pages and three attempts per page,
with the shared cache quota and server cooldown. Limits across other software or separate
cache files are not coordinated. A one-symbol one-day query minimizes scope but cannot
guarantee a nonempty or single-page response.

Success prints an immutable snapshot ID. Keep the ignored SQLite cache private, retain the
ID locally, and audit it offline. Do not upload raw market data as a GitHub fixture, CI
artifact, chat attachment or public report without confirmed rights. Safe status to share:
exit status, sanitized error category and counts, without headers or raw responses.

### Codespaces alternative and endpoint boundary

Use Codespaces only if its compute/storage/network usage is within your free allowance;
this project does not provision one or guarantee it is free. If you choose it later, use
GitHub's private Codespaces secrets UI, scoped to this repository, for the two exact target
variable names. Never use Actions secrets for an authenticated CI test. Keep AI sessions
and untrusted extensions out of that credential-bearing environment. No secret was created,
read or configured in this change. Local hidden entry avoids persistent repository-scoped
secret configuration and is the preferred initial workflow.

The Alpaca client exposes only the exact bars GET path on a fixed origin, IEX feed and
verified TLS; it does not follow redirects or offer an arbitrary URL/base URL switch.
Account, asset-management, orders, paper-trading and live-trading paths are rejected before
transport. Tests cover those denials and redirected requests. No trading client is added.
This is an application boundary, not OS isolation: arbitrary Python code with credentials
can bypass it. For enforced destination restrictions, use an administrator-controlled
outbound policy allowing only `data.alpaca.markets:443`; method/path restrictions require an
appropriate controlled gateway. Codespaces secrets alone do not impose those restrictions.
Do not claim Alpaca credentials themselves have data-only permissions unless independently
confirmed. Existing eToro modules are not invoked by this workflow, and their risk controls
and explicit approval requirements remain unchanged.

## Offline audit of a genuine downloaded manifest

The hourly audit now reads native Alpaca manifests directly, without CSV conversion or
invented metadata. It opens existing caches read-only, revalidates checksums and pagination,
and reports session counts and all existing coverage/replay blockers. It never loads keys,
constructs a network client, shifts candles, fills gaps or promotes provenance.

Copy `docs/examples/alpaca-study.json` to `.historical-data/study.json`. Replace `audit_at` and
`calendar_verified_at` with actual aware review timestamps, after checking the schedule.
The supplied short window is for diagnostics, deliberately too short for qualification.
After your first download, replace `MANIFEST_ID` below with the printed ID:

```bash
python -m etoro_demo_bot.history.hourly_cli --alpaca-manifest MANIFEST_ID --symbol IBM --cache .historical-data/alpaca-first.sqlite --study .historical-data/study.json --output .historical-data/first-audit.json
```

Use a new output filename on each audit. Exit 0 means a report was written, not that the
data qualified. Inspect `audit.coverage_errors` and `audit.replay_blockers`. The report's
EUR 500 and EUR 1,000 comparisons remain `not_run`, with null performance fields.
Only reviewed XNYS/USD and the actual downloaded price basis are accepted. The built-in
calendar supports 2026 only. Unsupported years/markets require separately reviewed schedules.
NYSE calendar provenance here is a current review, not proof of an originally published schedule.

## Path to realistic EUR 500 and EUR 1,000 studies

| Component | Existing normalization and gate | Remaining evidence or implementation |
| --- | --- | --- |
| Parser/archive | Decimal USD OHLCV, UTC instants, original bytes/offsets in snapshots, per-symbol monotonicity, inclusive query bounds, whole pagination chain | Actual first/last dates, missing/zero-volume hours, symbol changes and revisions; do not manufacture observations |
| Hourly grid | Engine expects full hours from regular-session open; partial closing intervals excluded by current policy | Native Alpaca hour boundaries must be measured. Never relabel :00 as :30. If incompatible, obtain eligible finer bars and implement reviewed session-open aggregation, including partial-hour and missing-minute policies; this PR does not enable that route |
| Availability | Retrieval time is retained as `known_at` | Original publication/revision timing is unverified. Backdating retrieval to bar close would create look-ahead bias; obtain evidence or design a separately labelled observational research engine |
| Strategy | `ObservedBar(Candle(...), known_at)` at the reviewed replay boundary; at least 35 usable warm-up bars | Reviewed opportunity, fundamentals when used, earnings blackout history, session evidence and enough available warm-up observations |
| Replay | `run_hourly_study` and `run_verified` keep coverage and evidence checks | Raw prices, verified original availability, action completeness, matching instrument and review reference; split-adjusted bars cannot bypass raw-price gate |
| Quotes/fills | Dataset requires fresh historical bid/ask events and final valuation; OHLCV is not a quote | Historical spreads, latency, executable depth/quantity, partial fills, slippage and adverse gap handling. IEX volume does not establish eToro liquidity |
| FX | Initial EUR funding and event-time conversion evidence required | Historical EUR/USD bid/ask and conversion charges at funding/valuation; daily ECB reference observations cannot impersonate fresh intraday executable FX |
| Costs | Simulation parameters explicitly model fees, slippage and FX | Date-, jurisdiction-, product- and account-specific eToro fees, minimum charges, FX costs, spread and any applicable taxes; defaults are assumptions, not historical fees |
| Eligibility | No shorts, margin, leveraged or derivative products | Historical eToro instrument ID mapping, underlying/non-CFD status, unleveraged eligibility, minimum notional, fractional quantity step and effective dates. Alpaca symbol availability proves none of these |
| Corporate actions | Incomplete actions and any actions without accounting block replay | Split/dividend/symbol-change history and accounting, including benchmarks; don't mix adjusted signals with unadjusted fills silently |
| Study design | Default 183-day span, 120 sessions, chronological partitions and 20 sessions per partition | Predeclare universe and train/validation/test dates; control survivorship/selection bias; cash and buy-and-hold baselines and out-of-sample evaluation |
| Monte Carlo | Conditional 10,000-trial block bootstrap; `Pool.validate` accepts synthetic pools only | A separately reviewed historical-pool adapter with complete nonoverlapping horizons, OHLC ratios to previous close, genuine gap/session treatment, checksum and availability before decision time. Do not label real history synthetic to pass validation |

A candle-only IEX study could be useful research, but cannot honestly be presented as a
validated historical eToro execution backtest under the current contracts. Monte Carlo
resamples conditional paths; it does not replace chronological backtesting or establish
profitability. This change adds no historical pool, weakens no gate and generates no result.
