# Windows PowerShell setup (Python 3.12+)

Use a free Python installation from python.org and run these commands from the repository root. No paid service is required. The CLI is read-only; the separate execution coordinator remains disabled by default. There is no autonomous trading loop.

## Install and verify offline

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.lock
.\.venv\Scripts\python.exe -m pip install --no-deps --no-build-isolation -e .
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
```

Activation is optional; no PowerShell execution-policy changes are needed. The lock includes Windows-specific dependencies and the build backend. Tests use mocked HTTP only and require no keys.

## Configure a Demo key securely in this local session

First confirm in eToro Settings → Trading → API Key Management that the user key is bound to **Demo** and has **Read** permission. Do not use a Real key. Scope cannot be decoded from the opaque credential locally; the confirmation below is a user declaration, not cryptographic proof. eToro enforces key scope on the Demo portfolio request. Never probe a Real endpoint.

The application reads environment variables only. `.env.example` documents names; `.env` files are not loaded automatically. Do not paste secrets into command lines, chat, scripts, logs or committed files. In your own PowerShell terminal, masked input keeps values out of command history:

```powershell
function Set-SessionSecret([string]$Name) {
    $secureValue = Read-Host "Enter $Name locally" -AsSecureString
    $pointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureValue)
    try {
        [Environment]::SetEnvironmentVariable(
            $Name, [Runtime.InteropServices.Marshal]::PtrToStringBSTR($pointer), 'Process'
        )
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($pointer)
        $secureValue.Dispose()
    }
}
Set-SessionSecret 'ETORO_API_KEY'
Set-SessionSecret 'ETORO_USER_KEY'
$env:ETORO_ENVIRONMENT = 'demo'
# Set only after checking Demo binding in eToro's key-management screen.
$env:ETORO_DEMO_KEY_CONFIRMED = 'true'
```

Environment variables reside in process memory and are inherited by children; they are not encrypted storage. Close the session or clear them when finished. Do not enable HTTP wire logging or traceback tools that dump local variables. TLS verification is enabled; corporate proxies must supply a trusted CA rather than disabling verification.

## Explicit read-only connection test

```powershell
.\.venv\Scripts\etoro-demo.exe check-demo
```

This sends only `GET https://public-api.etoro.com/api/v1/trading/info/demo/portfolio`. Success prints a status message, not portfolio contents or credentials. A 401/403 may mean wrong scope, invalid/expired credentials, missing permission or account restrictions; inspect non-secret key metadata locally. There is no Real fallback. No order authorization is involved because this command cannot place orders.

```powershell
Remove-Item Env:ETORO_API_KEY, Env:ETORO_USER_KEY -ErrorAction SilentlyContinue
Remove-Item Env:ETORO_DEMO_KEY_CONFIRMED -ErrorAction SilentlyContinue
Remove-Item Function:Set-SessionSecret
```

## Limits of this foundation

Only the Demo portfolio and shared market rates GET routes are supported. Rates accept 1–1000 positive instrument IDs and preserve HTTP 206 as `partial=True`; quote delay and missing data must be handled by future analysis. Responses are JSON objects with otherwise unnormalized vendor fields; success does not prove trading readiness.

The client serializes requests and conservatively paces both endpoints together at one request/second, including retries. Use one client/process per key: separate processes or other applications share the server quota but not this local limiter. Server cooldowns are honored; waits over five minutes abort rather than retry early. Safe reads retry at most twice for transport errors, 429, 502, 503 and 504; auth failures and redirects never retry. Account access and Windows installation still require validation on your machine.

## Phase 3 offline execution-engine verification

The separate Demo execution coordinator is disabled by default and is not connected to this CLI. It has no credential-loading or autonomous execution command. Validate it using mocked tests only:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_execution.py
```

See [DEMO_EXECUTION.md](DEMO_EXECUTION.md) for authorization, SQLite migration, risk integration, recovery and deployment limitations. Real account use requires a trusted Demo identity attestation provider and exact human order approval; neither is supplied by an environment-mode flag. Do not initialize or delete production safety state to clear a halt or duplicate reservation. Existing `check-demo` remains a read-only portfolio request.


## Phase 4 offline market-scanner verification

No credentials, paid services or additional dependencies are needed:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_scanner.py
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m hatchling build
```

The tests use synthetic keys, mocked HTTP, simulated time and temporary SQLite files. Do not configure real keys for these tests. No scanner/execution command is added to the CLI. The existing `check-demo` command is unrelated to scanner validation and is unnecessary here.

For future approved read-only integration, compose `Scanner` with the explicit providers described in [MARKET_SCANNER.md](MARKET_SCANNER.md). `MarketClient` defaults to network disabled. Choose a small explicit watchlist, a scan interval (default 300 seconds), verified EUR/USD conversion and conservative fees. Unknown product leverage, currency, session or history coverage blocks ranking. This release supplies no live evidence provider, so do not fabricate those attestations to get a signal.

If initializing a local analysis store later, create `.scanner-state` explicitly and keep its SQLite files separate from `.risk-state`. All scanner instances sharing a key must share the quota store. Do not run the older clients concurrently on that key without common quota coordination, or delete state to bypass cooldowns. Closing a window or restarting does not authorize orders. Automated scoring never changes the disabled execution default.


## Phase 5 offline strategy-engine verification

Use the existing environment and pinned dependencies. No keys or broker connection are needed:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_strategy.py
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m hatchling build
```

Tests initialize only temporary synthetic journals/accounts and run no authenticated API calls. There is no strategy execution command. See [STRATEGY_ENGINE.md](STRATEGY_ENGINE.md) for library composition and required evidence. Create `.strategy-state` explicitly for a future local analysis journal, separately from `.risk-state`; never reset safety state to clear a duplicate or halt. `Journal.initialize` refuses to overwrite existing files.

Proposal generation is offline and reserves no capacity. Explicit RiskEngine review does reserve local capacity; do not use a real safety database for experiments. Exit results and stop/target levels are advice, never broker instructions. A fresh, verified earnings calendar and product/quantity-step/FX/cost evidence are required; do not substitute invented facts. Rules are immutable versions; Learning Agent suggestions require review before any promotion. Autonomous execution remains disabled.


## Phase 6 offline backtesting and synthetic reports

No credentials, market download or new dependencies are needed. These commands run synthetic engineering fixtures only:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_backtest.py
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe -m ruff format --check .
.\.venv\Scripts\python.exe -m mypy
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\python.exe -m hatchling build
.\.venv\Scripts\python.exe -m etoro_demo_bot.backtest --synthetic --eur 500 --output .backtest-output\synthetic-500
.\.venv\Scripts\python.exe -m etoro_demo_bot.backtest --synthetic --eur 1000 --output .backtest-output\synthetic-1000
```

Output directories must be new; reruns deliberately refuse to overwrite evidence or safety state. Open `comparison.md` and each strategy's `report.md` locally. JSON, CSV, checksums, complete input archives and isolated simulation journals are also saved. All results are prominently synthetic; do not present them as historical returns or evidence of profitability. No order execution occurs.

See [BACKTESTING.md](BACKTESTING.md) for library input contracts, chronological splits, metrics and data limitations. Keep replay output separate from `.risk-state` and `.strategy-state`; never point experiments at production state. There is no real-data downloader or credential configuration step. Supply independently reviewed historical evidence through the typed Dataset interface before conducting a real-data study.

## Phase 7: offline historical-data audit

No eToro environment variables are required. Read [provider terms and limitations](HISTORICAL_DATA.md)
first. For eligible personal non-commercial research, the official Alpha Vantage documentation
provides this public demo URL (`demo` is the published sample identifier, not a private key).
Download once; reuse the SQLite snapshot thereafter. Standard free quota is 25 requests/day;
do not loop downloads, retry throttling, or substitute a premium function.

```powershell
python -m pip install -r requirements-dev.lock
python -m pip install --no-deps --no-build-isolation -e .
New-Item -ItemType Directory -Force .historical-data | Out-Null
Invoke-WebRequest -Uri 'https://www.alphavantage.co/query?function=TIME_SERIES_DAILY&symbol=IBM&apikey=demo&datatype=csv' -OutFile '.historical-data/ibm.csv' -TimeoutSec 30
$retrievedAt = [DateTimeOffset]::UtcNow.ToString('o')
python -m etoro_demo_bot.history --csv .historical-data/ibm.csv --symbol IBM --retrieved-at $retrievedAt --output .historical-data/ibm-audit
python -m pytest -q
python -m ruff check .
python -m mypy
```

Use a new output directory for each audit (existing reports are never overwritten). Copy the
printed snapshot identifier to reproduce the audit entirely offline:

```powershell
python -m etoro_demo_bot.history --snapshot '<printed-snapshot-id>' --output .historical-data/ibm-repeat
```

The reviewed calendar covers 2026 only; other years fail closed. Symbol metadata in a cached
snapshot is retained. Download time is not original candle publication time. HTTP error/JSON
bodies fail CSV validation. An existing report directory produces a sanitized failure.
`readiness.json`, `comparisons.csv` and `README.md` describe missing evidence; blocked comparisons
are not backtest returns. Do not commit private/vendor payloads from `.historical-data`.
No network calls, credentials or broker requests occur in the audit command.

## Phase 8: hourly export readiness (offline)

Read [hourly provider rights and blockers](INTRADAY_DATA.md). No approved remote hourly downloader
is available. Only use an export you legitimately obtained with verified usage rights. Do not
substitute daily candles or change their resolution labels.

The normalized CSV header is exactly:

```text
start,end,open,high,low,close,volume,known_at
```

Timestamps need explicit offsets. Preserve the original CSV bytes when hashing, copying and
caching; do not normalize newlines or strip a BOM first. Missing `known_at` is conservatively
retrieval time. Supply a `source.json` matching `history.models.Source`, including actual source
and terms URLs, retrieval timestamp, original SHA-256, symbol, license note and classification
`historical_observation`. This is provenance supplied by you, not automatic verification.
Specify the actual price basis, not an assumed raw/adjusted label.

Prepare a `study.json` with predeclared dates, actual audit/calendar-review timestamps, exchange
`XNYS`, currency `USD`, basis `raw` (only if verified), and `policy`. Example boundary structure
for a prospective **data audit**, not a supplied dataset:

```json
{
  "start": "2026-01-02", "end": "2026-10-26",
  "train_at": "2026-01-12T00:00:00Z",
  "validation_at": "2026-06-01T00:00:00Z",
  "test_at": "2026-08-03T00:00:00Z",
  "finish_at": "2026-10-26T21:00:00Z",
  "audit_at": "2026-10-27T22:00:00Z",
  "calendar_verified_at": "2026-10-27T17:13:37+00:00",
  "exchange": "XNYS", "currency": "USD", "basis": "raw",
  "policy": {"minimum_days": 183, "minimum_sessions": 120,
             "warmup_bars": 35, "minimum_partition_sessions": 20}
}
```

Use your actual review timestamps and predeclared study boundaries. Save the two JSON files and
licensed export locally under ignored `.historical-data`, then run:

```powershell
python -m etoro_demo_bot.history.hourly_cli --csv .historical-data/hourly.csv --source .historical-data/source.json --study .historical-data/study.json --output .historical-data/hourly-audit.json
python -m etoro_demo_bot.history.hourly_cli --snapshot '<snapshot-from-report>' --study .historical-data/study.json --output .historical-data/hourly-repeat.json
python -m pytest -q
python -m ruff check .
python -m mypy
```

The CLI emits coverage findings even when the study is blocked; exit zero means the audit was
written, not that a dataset passed. Schema/integrity errors fail with a sanitized message.
Use new output paths. The report contains null metrics and does not run backtests or orders.
Only reviewed 2026 sessions are supported; earlier years require another reviewed calendar.

## Alpaca historical bars: local configuration and future opt-in

Read [the free-feed restrictions and remaining gates](ALPACA_MARKET_DATA.md) first. Development
uses mocks only. The following configuration/download instructions are for a future separately
authorized local read; they were **not executed with real credentials** during implementation.
No paid plan is needed by the intended Basic IEX route. Verify your account's Basic access and
applicable data agreements yourself; do not send keys in chat. No `.env` file is loaded by Python.

Set environment variables without putting secret literals in shell history (PowerShell 5.1+):

```powershell
$alpacaKeyInput = Read-Host 'Alpaca data API key' -AsSecureString
$alpacaSecretInput = Read-Host 'Alpaca data API secret' -AsSecureString
$env:ALPACA_DATA_API_KEY = [System.Net.NetworkCredential]::new('', $alpacaKeyInput).Password
$env:ALPACA_DATA_API_SECRET = [System.Net.NetworkCredential]::new('', $alpacaSecretInput).Password
# Only after reviewing Basic IEX access and the applicable data-use terms:
$env:ALPACA_DATA_FREE_ACCESS_CONFIRMED = 'true'
```

Never print these variables or dump the environment. Opaque API keys may have brokerage powers;
this client's exact route restriction is separate from the key's scope. A help command is offline:

```powershell
python -m etoro_demo_bot.alpaca --help
python -m pytest -q
python -m ruff check .
python -m mypy
```

For a **separately authorized** small read of completed historical hours, explicit networking opt-in
is required. This example is not a claim of actual coverage or trading eligibility:

```powershell
python -m etoro_demo_bot.alpaca --enable-network --symbols IBM SPY --start '2026-09-01T00:00:00Z' --end '2026-09-02T00:00:00Z'
```

Both bounds are inclusive bar-start timestamps; `end + 1 hour` must be at least 15 minutes before
request time. The fixed endpoint requests IEX, USD, `1Hour`, ascending order, raw prices and no
implicit current-symbol mapping. Optional `--adjustment split` preserves a distinct adjusted
basis and still blocks unverified replay. There is no feed/base URL/account/order option.
Missing `--enable-network` exits before reading keys. Authentication/permission errors do not
trigger a paid feed or host fallback. A successful command prints only the completed manifest ID.
It does not establish coverage completeness, original availability or backtest readiness.

Pages, metadata, shared quota state and the complete manifest live in ignored
`.historical-data/alpaca.sqlite`. Reuse this archive across application processes so pacing is
shared; do not run other data clients against the same account quota without coordination.
Use `history.alpaca.load_download()` for offline loading and the existing hourly audit before
considering simulation. A calendar/offset/alignment failure must not be fixed by shifting prices.
Clear the process-local values when finished:

```powershell
Remove-Item Env:ALPACA_DATA_API_KEY, Env:ALPACA_DATA_API_SECRET, Env:ALPACA_DATA_FREE_ACCESS_CONFIRMED -ErrorAction SilentlyContinue
Remove-Variable alpacaKeyInput, alpacaSecretInput -ErrorAction SilentlyContinue
```

No eToro credentials are needed for this workflow. No Demo or Real orders are enabled.

For Codex Cloud, use [Network Secrets setup](CODEX_CLOUD_ALPACA.md) instead of entering raw
keys in a shell. Leave ALPACA_DATA_CODEX_PROXY_REQUIRED unset/false for local Windows use.
TLS verification uses the system trust store, or explicitly configured SSL_CERT_FILE /
SSL_CERT_DIR. Do not set these to untrusted bundles. Cloud proxy routing is not inherited
on local Windows: an arbitrary HTTPS_PROXY is not an approved Codex proxy.

## Phase 11: offline Monte Carlo demo

No credentials or networking are needed. Choose new output directories; never point these commands
at existing production safety state. Each command runs 10,000 reproducible synthetic outcomes:

```powershell
python -m etoro_demo_bot.monte_carlo --output .backtest-output/mc-500-seed19 --eur 500 --seed 19
python -m etoro_demo_bot.monte_carlo --output .backtest-output/mc-1000-seed19 --eur 1000 --seed 19
python -m pytest -q tests/test_monte_carlo.py
```

Each output contains separate synthetic risk/strategy databases and report/report.md,
report/report.json, report/trials.csv and report/checksums.json. Existing directories are rejected.
These results are software fixtures, not historical performance or investment recommendations.
See [Monte Carlo model, license review and limitations](MONTE_CARLO.md). No order is enabled.

## Phase 1 five-minute research (offline)

Keep the existing Python 3.12+ virtual environment and pinned requirements. `tzdata` in the
existing lock supplies ZoneInfo data on Windows; do not change the computer timezone or
implement a manual DST offset. This phase uses the reviewed 2026 XNYS calendar only.

In PowerShell, activate your environment as usual, then preview without keys:

```powershell
python -m etoro_demo_bot.alpaca --dry-run --timeframe 5Min --symbols IBM --start 2026-03-09T00:00:00Z --end 2026-03-10T00:00:00Z
python -m etoro_demo_bot.history.intraday_cli --help
python -m pytest -q tests/test_intraday_contracts.py
```

For an already imported, private complete five-minute manifest, use `intraday_cli` with
`--cache`, `--manifest`, `--symbol`, inclusive `--start`/`--end` dates, aware `--audit-at`
and `--calendar-verified-at` timestamps, and a new `--output` path. Quote Windows paths
that contain spaces. The cache is opened read-only and a failed qualification creates no
success report. No upstream code or real-data fixture needs to be installed.

Do not enter keys or enable networking for this phase. Five-minute `--enable-network`
fails before credential loading; the existing hourly workflow is unchanged. Five-minute
inputs cannot enter the existing scanner/strategy/replay as hourly candles. See
[FIVE_MINUTE_CONTRACTS.md](FIVE_MINUTE_CONTRACTS.md) for metadata, completeness, freshness,
point-in-time and remaining evidence requirements. No ORB trading or orders are enabled.

## Phase 14: offline intraday research (no credentials)

Use the development environment above; skip all credential and connection-test
sections for this workflow. These commands create only isolated synthetic research
state/reports, with no external requests or broker orders:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_intraday_replay.py tests/test_intraday_evaluation.py -q
.\.venv\Scripts\python.exe -m etoro_demo_bot.backtest.intraday --output .historical-data\orb-synthetic-500 --eur 500 --seed 19
.\.venv\Scripts\python.exe -m etoro_demo_bot.backtest.intraday --output .historical-data\orb-synthetic-1000 --eur 1000 --seed 19
.\.venv\Scripts\python.exe -m etoro_demo_bot.backtest.intraday.benchmark
```

Output directories must be new. An existing run is refused; never remove ordinary
safety state to rerun. JSON/CSV/Markdown and checksums distinguish synthetic fixtures,
conditional models and blocked evidence. The Monte Carlo comparison has 10,000
whole-session outcome draws, not 10,000 independent historical observations.
See [contracts, assumptions and blockers](INTRADAY_REPLAY.md). There is no genuine
Alpaca download or trading activation in these commands.
